(() => {
  "use strict";

  const mobileQuery = window.matchMedia(
    "(max-width: 575.98px) and (pointer: coarse)",
  );
  const root = document.documentElement;
  let panel = null;
  let panelResizeObserver = null;
  let timelineOpen = false;
  let scanScheduled = false;

  function isMobile() {
    return mobileQuery.matches;
  }

  function findPanel() {
    return [...document.querySelectorAll("div.mantine-Paper-root")].find(
      (element) => {
        const style = element.getAttribute("style") || "";
        return style.includes("position: fixed") && style.includes("width: 20em");
      },
    );
  }

  function findTimeline() {
    return [...document.querySelectorAll("canvas")]
      .map((canvas) => canvas.parentElement)
      .find((element) => {
        const style = element?.getAttribute("style") || "";
        return (
          style.includes("position: fixed") &&
          style.includes("bottom: 0px") &&
          style.includes("left: 0px") &&
          style.includes("right: 0px") &&
          style.includes("z-index: 5")
        );
      });
  }

  function setTimelineOpen(nextOpen) {
    timelineOpen = Boolean(nextOpen);
    root.classList.toggle("ue5s-mobile-timeline-open", timelineOpen);
    const button = document.querySelector("#ue5s-mobile-timeline-toggle");
    if (button) {
      button.setAttribute("aria-pressed", String(timelineOpen));
      button.textContent = timelineOpen ? "Hide timeline" : "Timeline";
    }
  }

  function ensureTimelineButton() {
    let button = document.querySelector("#ue5s-mobile-timeline-toggle");
    if (button) return;
    button = document.createElement("button");
    button.id = "ue5s-mobile-timeline-toggle";
    button.type = "button";
    button.textContent = "Timeline";
    button.setAttribute("aria-label", "Show motion timeline");
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      setTimelineOpen(!timelineOpen);
    });
    document.body.append(button);
  }

  function updatePanelState() {
    if (!panel || !panel.isConnected) return;
    // Viser keeps the collapsed tab markup in the DOM at zero height, so
    // visible text is the reliable signal for its open/closed state.
    const panelOpen = panel.innerText.trim() !== "ARDY";
    root.classList.toggle("ue5s-mobile-panel-open", panelOpen);
    if (panelOpen && timelineOpen) setTimelineOpen(false);
  }

  function ensurePanelToggleHook() {
    if (!panel) return;
    const header = [...panel.querySelectorAll("div")].find((element) => {
      const style = element.getAttribute("style") || "";
      return style.includes("cursor: pointer") && style.includes("height: 3.5em");
    });
    if (!header || header.hasAttribute("data-ue5s-mobile-panel-toggle")) return;
    header.setAttribute("data-ue5s-mobile-panel-toggle", "");
    header.addEventListener("click", () => {
      window.setTimeout(updatePanelState, 250);
    });
  }

  function watchPanel(nextPanel) {
    if (panel === nextPanel) {
      ensurePanelToggleHook();
      updatePanelState();
      return;
    }
    panelResizeObserver?.disconnect();
    panel = nextPanel;
    panel.setAttribute("data-ue5s-mobile-panel", "");
    panelResizeObserver = new ResizeObserver(updatePanelState);
    panelResizeObserver.observe(panel);
    ensurePanelToggleHook();
    updatePanelState();
  }

  function deactivateMobileLayout() {
    panelResizeObserver?.disconnect();
    panelResizeObserver = null;
    panel?.removeAttribute("data-ue5s-mobile-panel");
    panel = null;
    document
      .querySelector("[data-ue5s-mobile-timeline]")
      ?.removeAttribute("data-ue5s-mobile-timeline");
    document.querySelector("#ue5s-mobile-timeline-toggle")?.remove();
    root.classList.remove(
      "ue5s-mobile-layout",
      "ue5s-mobile-panel-open",
      "ue5s-mobile-timeline-open",
    );
    timelineOpen = false;
  }

  function scan() {
    scanScheduled = false;
    if (!isMobile()) {
      deactivateMobileLayout();
      return;
    }

    root.classList.add("ue5s-mobile-layout");
    const nextPanel = findPanel();
    if (nextPanel) watchPanel(nextPanel);

    const timeline = findTimeline();
    if (timeline && !timeline.hasAttribute("data-ue5s-mobile-timeline")) {
      timeline.setAttribute("data-ue5s-mobile-timeline", "");
    }
    ensureTimelineButton();
  }

  function scheduleScan() {
    if (scanScheduled) return;
    scanScheduled = true;
    requestAnimationFrame(scan);
  }

  const mutationObserver = new MutationObserver(scheduleScan);
  mutationObserver.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  mobileQuery.addEventListener("change", scheduleScan);
  scheduleScan();
})();
