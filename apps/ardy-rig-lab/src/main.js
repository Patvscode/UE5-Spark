import "./styles.css";

import { RigScene } from "./rigScene.js";
import {
  CORE27_JOINTS,
  SOURCE_REVISION,
  createNeutralFrame,
  defaultRigMapping,
  sanitizeRigMapping,
} from "./poseProtocol.js";
import { PoseStream } from "./poseStream.js";

const elements = {
  canvas: document.querySelector("#rig-canvas"),
  connectionBadge: document.querySelector("#connection-badge"),
  connectionLabel: document.querySelector("#connection-label"),
  motionState: document.querySelector("#motion-state"),
  prompt: document.querySelector("#motion-prompt"),
  behavior: document.querySelector("#behavior"),
  duration: document.querySelector("#duration"),
  intensity: document.querySelector("#intensity"),
  intensityValue: document.querySelector("#intensity-value"),
  runOnce: document.querySelector("#run-once"),
  runLoop: document.querySelector("#run-loop"),
  stop: document.querySelector("#stop-motion"),
  notice: document.querySelector("#motion-notice"),
  resetView: document.querySelector("#reset-view"),
  rigScale: document.querySelector("#rig-scale"),
  rigYaw: document.querySelector("#rig-yaw"),
  mirrorX: document.querySelector("#mirror-x"),
  rigOffsets: [
    document.querySelector("#rig-offset-x"),
    document.querySelector("#rig-offset-y"),
    document.querySelector("#rig-offset-z"),
  ],
  jointSelect: document.querySelector("#joint-select"),
  jointOffsets: [
    document.querySelector("#joint-offset-x"),
    document.querySelector("#joint-offset-y"),
    document.querySelector("#joint-offset-z"),
  ],
  resetJoint: document.querySelector("#reset-joint"),
  resetRig: document.querySelector("#reset-rig"),
};

let rigMapping = defaultRigMapping();
let providerHealth = {
  checked: false,
  ready: false,
  dynamicTextReady: false,
  provider: "",
  detail: "Checking protocol v2.",
};
let currentPositions = createNeutralFrame().positions;
const visibleComponents = Object.fromEntries(
  [...document.querySelectorAll("[data-component]")].map((input) => [input.dataset.component, input.checked]),
);

const scene = new RigScene(elements.canvas);
scene.updatePose(currentPositions, rigMapping);

function streamStateChanged(state) {
  elements.stop.disabled = !state.active;
  elements.runOnce.disabled = state.fetching || !providerHealth.ready;
  elements.runLoop.disabled = state.fetching || !providerHealth.ready;
  elements.motionState.textContent = {
    reference: "Reference pose",
    once: state.fetching ? "Generating" : "Once · live",
    loop: state.fetching && state.bufferedFrames === 0 ? "Generating" : "Loop · live",
    buffering: "Buffering",
    complete: "Run complete",
    stopped: "Stopped",
    error: "Pose error",
  }[state.mode] || state.mode;
  elements.motionState.classList.toggle("is-live", ["once", "loop"].includes(state.mode));
  elements.motionState.classList.toggle("is-error", state.mode === "error");

  if (state.mode === "error") {
    elements.notice.textContent = `${state.lastError} Holding the last verified pose; no fallback motion is simulated.`;
  } else if (state.mode === "complete") {
    elements.notice.textContent = `Completed ${state.playedFrames} real Core27 frames. Holding the final generated pose.`;
  } else if (state.mode === "stopped") {
    elements.notice.textContent = "Stopped. Holding the last received Core27 frame.";
  } else if (state.active) {
    elements.notice.textContent = `${state.bufferedFrames} real frames buffered · sequence ${state.sequence || "pending"} · ${state.mode === "loop" ? "looping" : `${state.playedFrames}/${state.targetFrames} played`}.`;
  }
}

const poseStream = new PoseStream({ onState: streamStateChanged });
streamStateChanged(poseStream.snapshot());

function providerIsExact(payload) {
  return payload?.protocolVersion === 2
    && payload?.fps === 20
    && payload?.coordinateSystem === "ardy-rh-x-left-y-up-z-forward-meters"
    && payload?.source?.system === "nv-tlabs/ardy"
    && payload?.source?.revision === SOURCE_REVISION
    && payload?.source?.skeleton === "Core27"
    && JSON.stringify(payload?.source?.jointOrder) === JSON.stringify(CORE27_JOINTS);
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/ardy-health", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !providerIsExact(payload)) {
      throw new Error(
        payload?.protocolVersion && payload.protocolVersion !== 2
          ? `Protocol v${payload.protocolVersion} is running; this lab requires v2.`
          : payload?.detail || "The strict ARDY v2 descriptor is unavailable.",
      );
    }
    providerHealth = {
      checked: true,
      ready: true,
      dynamicTextReady: payload.dynamicTextReady === true,
      provider: String(payload.provider || "unknown"),
      detail: payload.dynamicTextReady === true
        ? "Real dynamic text conditioning is ready."
        : "Base behavior poses are available; dynamic text conditioning is not ready.",
    };
    elements.connectionBadge.className = `connection-badge ${providerHealth.dynamicTextReady ? "is-ready" : "is-limited"}`;
    elements.connectionLabel.textContent = providerHealth.dynamicTextReady
      ? "ARDY v2 ready"
      : `v2 ${providerHealth.provider || "limited"}`;
  } catch (error) {
    providerHealth = {
      checked: true,
      ready: false,
      dynamicTextReady: false,
      provider: "",
      detail: error.message || "ARDY v2 is unavailable.",
    };
    elements.connectionBadge.className = "connection-badge is-offline";
    elements.connectionLabel.textContent = "ARDY v2 offline";
    if (!poseStream.active) {
      elements.notice.textContent = `${providerHealth.detail} The visible rig is the labeled neutral reference pose.`;
    }
  }
  const busy = poseStream.fetching;
  elements.runOnce.disabled = busy || !providerHealth.ready;
  elements.runLoop.disabled = busy || !providerHealth.ready;
}

function readMapping() {
  const selectedJoint = elements.jointSelect.value;
  const next = {
    ...rigMapping,
    scale: elements.rigScale.value,
    yawDegrees: elements.rigYaw.value,
    mirrorX: elements.mirrorX.checked,
    offset: elements.rigOffsets.map((input) => input.value),
    jointOffsetsCm: {
      ...rigMapping.jointOffsetsCm,
      [selectedJoint]: elements.jointOffsets.map((input) => input.value),
    },
  };
  rigMapping = sanitizeRigMapping(next);
  writeMappingInputs(false);
  scene.updatePose(currentPositions, rigMapping);
}

function writeMappingInputs(includeJoint = true) {
  elements.rigScale.value = String(rigMapping.scale);
  elements.rigYaw.value = String(rigMapping.yawDegrees);
  elements.mirrorX.checked = rigMapping.mirrorX;
  elements.rigOffsets.forEach((input, index) => {
    input.value = String(rigMapping.offset[index]);
  });
  if (includeJoint) {
    const offsets = rigMapping.jointOffsetsCm[elements.jointSelect.value] || [0, 0, 0];
    elements.jointOffsets.forEach((input, index) => {
      input.value = String(offsets[index]);
    });
  }
}

async function runMotion(mode) {
  if (!providerHealth.ready) {
    elements.notice.textContent = providerHealth.detail;
    return;
  }
  const prompt = elements.prompt.value.trim();
  if (prompt && !providerHealth.dynamicTextReady) {
    elements.notice.textContent = "Dynamic text conditioning is not ready. Clear the prompt to request the selected real base behavior without pretending the text was followed.";
    return;
  }
  try {
    await poseStream.start({
      mode,
      prompt,
      behavior: elements.behavior.value,
      intensity: elements.intensity.value,
      duration: elements.duration.value,
    });
  } catch (error) {
    elements.notice.textContent = error.message || "The pose request was not started.";
  }
}

for (const name of CORE27_JOINTS) {
  const option = document.createElement("option");
  option.value = name;
  option.textContent = name;
  elements.jointSelect.append(option);
}
elements.jointSelect.value = "Hips";
writeMappingInputs();

elements.intensity.addEventListener("input", () => {
  elements.intensityValue.textContent = `${Math.round(Number(elements.intensity.value) * 100)}%`;
});
elements.runOnce.addEventListener("click", () => runMotion("once"));
elements.runLoop.addEventListener("click", () => runMotion("loop"));
elements.stop.addEventListener("click", () => poseStream.stop());
elements.resetView.addEventListener("click", () => scene.resetView());

for (const input of [
  elements.rigScale,
  elements.rigYaw,
  elements.mirrorX,
  ...elements.rigOffsets,
  ...elements.jointOffsets,
]) {
  input.addEventListener("input", readMapping);
}
elements.jointSelect.addEventListener("change", () => {
  scene.setSelectedJoint(elements.jointSelect.value);
  writeMappingInputs(true);
});
elements.resetJoint.addEventListener("click", () => {
  rigMapping.jointOffsetsCm[elements.jointSelect.value] = [0, 0, 0];
  rigMapping = sanitizeRigMapping(rigMapping);
  writeMappingInputs(true);
  scene.updatePose(currentPositions, rigMapping);
});
elements.resetRig.addEventListener("click", () => {
  rigMapping = defaultRigMapping();
  writeMappingInputs(true);
  scene.updatePose(currentPositions, rigMapping);
});

for (const input of document.querySelectorAll("[data-component]")) {
  input.addEventListener("change", () => {
    visibleComponents[input.dataset.component] = input.checked;
    scene.setComponentVisible(input.dataset.component, input.checked);
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "f" || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  event.preventDefault();
  if (document.fullscreenElement) document.exitFullscreen();
  else document.querySelector("#app").requestFullscreen();
});

let lastTime = performance.now();
function update(deltaSeconds) {
  currentPositions = poseStream.update(deltaSeconds);
  scene.updatePose(currentPositions, rigMapping);
  scene.render();
}

function animate(now) {
  const delta = Math.min(0.1, Math.max(0, (now - lastTime) / 1000));
  lastTime = now;
  update(delta);
  requestAnimationFrame(animate);
}

window.advanceTime = (milliseconds) => {
  update(Math.max(0, Number(milliseconds) || 0) / 1000);
};

window.render_game_to_text = () => JSON.stringify({
  mode: poseStream.mode,
  coordinateSystem: "ARDY source: +X character-left, +Y up, +Z forward, metres",
  provider: {
    checked: providerHealth.checked,
    ready: providerHealth.ready,
    dynamicTextReady: providerHealth.dynamicTextReady,
    name: providerHealth.provider,
    detail: providerHealth.detail,
  },
  motion: poseStream.snapshot(),
  rig: {
    selectedJoint: elements.jointSelect.value,
    mapping: rigMapping,
    visibleComponents,
    displayedRoot: currentPositions[0],
  },
  sceneReferences: ["floor", "chair", "bed"],
  controls: "left drag orbit, right drag pan, wheel/pinch zoom, F fullscreen",
});

window.addEventListener("resize", () => scene.resize());
refreshHealth();
const healthTimer = window.setInterval(refreshHealth, 5000);
window.addEventListener("pagehide", () => window.clearInterval(healthTimer), { once: true });
requestAnimationFrame(animate);
