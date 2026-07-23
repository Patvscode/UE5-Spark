import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, ArrowsInSimple, Camera, CaretDown, CaretUp, ChatCircleDots, Check,
  CircleNotch, CoatHanger, Ear, HandWaving, Info, Microphone, Pause, Person,
  PersonSimpleRun, Play, Sparkle, TextT, UserCircle, X,
} from "@phosphor-icons/react";

const MOTIONS = [
  { id: "wave", label: "Wave", Icon: HandWaving },
  { id: "explain", label: "Explain", Icon: Person },
  { id: "listen", label: "Listen", Icon: Ear },
];

const CHARACTERS = [
  { id: "ada", name: "Ada", detail: "Primary MetaHuman", ready: true },
  { id: "aoi", name: "Aoi", detail: "Portable MetaHuman", ready: true },
  { id: "casual-girl", name: "Casual Girl", detail: "UE5 ARKit character", ready: true },
];

const MEDIA = {
  ada: {
    idle: "/media/ada-idle.mp4", wave: "/media/ada-wave.mp4",
    explain: "/media/ada-explain.mp4", listen: "/media/ada-listen.mp4",
    poster: "/media/ada-poster.png",
  },
  aoi: {
    idle: "/media/aoi-motion.mp4", wave: "/media/aoi-motion.mp4",
    explain: "/media/aoi-explain.mp4", listen: "/media/aoi-motion.mp4",
    poster: "/media/aoi-poster.png",
  },
};

const MOTION_COMMAND_EXAMPLES = [
  "Jumping jacks", "Jog in place", "Run in place", "Stretch", "Wave",
];

const MOVEMENT_ROUTES = [
  { command: "jumping jacks", pattern: /\bjumping jacks?\b/i },
  { command: "jog in place", pattern: /\bjog(?:ging)? in place\b/i },
  { command: "run in place", pattern: /\brun(?:ning)? in place\b/i },
  { command: "stretch", pattern: /\b(?:do (?:a )?)?stretch(?: your (?:arms|body))?\b/i },
  { command: "dance", pattern: /\b(?:dance|dancing)(?: casually| in place)?\b/i },
  { command: "wave", pattern: /\b(?:wave|wave hello|greet me)\b/i },
  { command: "explain with your hands", pattern: /\b(?:explain|talk)(?: it)? with your hands\b/i },
  { command: "listen", pattern: /\b(?:listening pose|listen to me)\b/i },
  { command: "idle", pattern: /\b(?:go idle|stand naturally|relax your body)\b/i },
];

const LOOP_REQUEST_PATTERN = /\b(?:keep|loop|repeat|repeatedly|continuously|over and over)\b/i;
const STOP_MOVEMENT_PATTERN = /\b(?:stop (?:the )?(?:move|motion|movement|moving|wave|dance|jogging|running|repeating|loop|that)|end (?:the )?(?:movement|loop))\b/i;

function movementRouteFor(message) {
  const reviewed = MOVEMENT_ROUTES.find((route) => route.pattern.test(message));
  if (reviewed) return reviewed.command;
  return /\b(?:do|perform|show me|start|begin|keep)\b.*\b(?:move|motion|pose|jog|run|jump|walk|dance|wave|stretch)\b/i.test(message)
    ? message
    : null;
}

const ALIVE_ACTIONS = [
  { behavior: "idle", label: "relaxed weight shift", weight: 5, duration: [3.4, 5.2], intensity: [0.3, 0.46] },
  { behavior: "listen", label: "attentive listening", weight: 3, duration: [2.8, 4.4], intensity: [0.34, 0.5] },
  { behavior: "explain", label: "small conversational gesture", weight: 2, duration: [3.2, 4.8], intensity: [0.38, 0.56] },
];

const PENDING_WARDROBE = {
  profileId: "casual-girl",
  displayName: "Casual Girl",
  installed: false,
  state: "asset-profile-pending",
  presets: [
    { id: "underwear", label: "Underwear", slots: { top: "none", bottom: "shorts", feet: "barefoot", hair: "style_1" } },
    { id: "casual", label: "Casual", slots: { top: "tank", bottom: "pants", feet: "shoes_socks", hair: "style_1" } },
    { id: "hoodie", label: "Hoodie", slots: { top: "crop_hoodie", bottom: "shorts", feet: "shoes_socks", hair: "style_2" } },
  ],
  slots: {
    top: ["none", "tank", "sweater", "off_shoulder", "crop_hoodie"].map((id) => ({ id, label: id.replaceAll("_", " ") })),
    bottom: ["shorts", "pants"].map((id) => ({ id, label: id })),
    feet: ["barefoot", "shoes_socks"].map((id) => ({ id, label: id.replaceAll("_", " ") })),
    hair: ["style_1", "style_2"].map((id) => ({ id, label: id.replaceAll("_", " ") })),
  },
  fullyUnclothed: { enabled: false, reason: "Complete base-body geometry has not been audited." },
};

const DEFAULT_AI_CONTROL = {
  schemaVersion: 1,
  controlConfigId: "ue5-spark-local-ai-control-v1",
  defaultMode: "ai_motion",
  selectedMode: "ai_motion",
  assetAwareEnabled: false,
  assetAwareNotice: "Asset-aware mode can share selected context with configured AI services as a controller-wide setting.",
  modes: [
    { id: "deterministic", label: "Deterministic", description: "Reviewed catalog matching only.", requiresExplicitLocalOptIn: false },
    { id: "ai_motion", label: "AI motion", description: "Generic motion intent without character asset input.", requiresExplicitLocalOptIn: false },
    { id: "asset_aware_ai", label: "Asset-aware AI", description: "Local asset context after explicit opt-in.", requiresExplicitLocalOptIn: true },
  ],
};

export function App() {
  const [character, setCharacter] = useState("ada");
  const [motion, setMotion] = useState("explain");
  const [camera, setCamera] = useState("fit");
  const [messages, setMessages] = useState([{
    id: "welcome", role: "assistant",
    content: "Hello, I’m Ada. Talk to me or try one of the real-time movement controls.",
  }]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [deviceVoice, setDeviceVoice] = useState(true);
  const [activeSheet, setActiveSheet] = useState(null);
  const [chromeHidden, setChromeHidden] = useState(false);
  const [noticeVisible, setNoticeVisible] = useState(true);
  const [aliveMode, setAliveMode] = useState(true);
  const [visionState, setVisionState] = useState("off");
  const [motionDraft, setMotionDraft] = useState("");
  const [motionMode, setMotionMode] = useState("once");
  const [motionLoop, setMotionLoop] = useState(null);
  const [stageZoom, setStageZoom] = useState(1);
  const [showZoom, setShowZoom] = useState(false);
  const [directingMotion, setDirectingMotion] = useState(false);
  const [motionPlan, setMotionPlan] = useState(null);
  const [aiControl, setAiControl] = useState(DEFAULT_AI_CONTROL);
  const [aiControlSaving, setAiControlSaving] = useState(false);
  const [assetContextAcknowledged, setAssetContextAcknowledged] = useState(false);
  const [wardrobe, setWardrobe] = useState(PENDING_WARDROBE);
  const [wardrobeSelection, setWardrobeSelection] = useState({
    preset: "casual",
    slots: { top: "tank", bottom: "pants", feet: "shoes_socks", hair: "style_1" },
  });
  const [wardrobeNotice, setWardrobeNotice] = useState("Asset profile not installed");
  const [notice, setNotice] = useState("Connecting to the live renderer…");
  const [health, setHealth] = useState({ fay: false, ardy: false, renderer: false, stream: false, checked: false, activeCharacter: null, requestedCharacter: null, availableCharacters: [], rendererSwitchState: "unmanaged", rendererSwitchSupported: false });
  const [statusFresh, setStatusFresh] = useState(false);
  const [liveFrameUrl, setLiveFrameUrl] = useState(null);
  const [streamState, setStreamState] = useState("replay");
  const videoRef = useRef(null);
  const inputRef = useRef(null);
  const motionInputRef = useRef(null);
  const recognitionRef = useRef(null);
  const cameraStreamRef = useRef(null);
  const cameraPreviewRef = useRef(null);
  const statusStaleTimerRef = useRef(null);
  const selectedCharacter = CHARACTERS.find((item) => item.id === character) || CHARACTERS[0];
  const media = MEDIA[character] || null;
  const videoSource = media ? (media[motion] || media.idle) : null;
  const systemsReady = health.fay && health.ardy;
  const streamRequested = health.renderer && health.stream && statusFresh;
  const exactRendererSelected = health.activeCharacter === character && health.rendererSwitchState !== "switching" && health.rendererSwitchState !== "starting";
  const liveStage = exactRendererSelected && streamRequested && streamState === "live" && Boolean(liveFrameUrl);
  const characterSwitching = health.requestedCharacter === character && ["starting", "switching", "rollback"].includes(health.rendererSwitchState);
  const liveLabel = !health.checked ? "Checking"
    : liveStage ? "Stage live"
      : characterSwitching ? `Loading ${selectedCharacter.name}`
        : streamRequested && exactRendererSelected && streamState === "error" ? "Replay fallback"
          : streamRequested && exactRendererSelected ? "Stream connecting"
            : media ? "Verified replay" : health.rendererSwitchSupported ? "Ready to launch" : "Renderer unavailable";
  const characterName = selectedCharacter.name;
  const selectedAiControl = aiControl.modes.find((item) => item.id === aiControl.selectedMode) || aiControl.modes[1];
  const stageMediaStyle = { "--stage-zoom": stageZoom };
  const sheetMeta = activeSheet === "conversation"
    ? { eyebrow: "Live Fay conversation", title: `Talk with ${characterName}`, label: "Conversation" }
    : activeSheet === "motion"
      ? { eyebrow: "Sealed ARDY catalog", title: "Describe a move", label: "Movement director" }
      : { eyebrow: "Stage setup", title: "Camera & character", label: "Camera, character, and wardrobe settings" };

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const payload = await response.json();
      setHealth({
        fay: Boolean(payload.fay), ardy: Boolean(payload.ardy), renderer: Boolean(payload.renderer), stream: Boolean(payload.stream), checked: true,
        activeCharacter: typeof payload.activeCharacter === "string" ? payload.activeCharacter : null,
        requestedCharacter: typeof payload.requestedCharacter === "string" ? payload.requestedCharacter : null,
        availableCharacters: Array.isArray(payload.availableCharacters) ? payload.availableCharacters : [],
        rendererSwitchState: typeof payload.rendererSwitchState === "string" ? payload.rendererSwitchState : "unmanaged",
        rendererSwitchSupported: Boolean(payload.rendererSwitchSupported),
      });
      setStatusFresh(true);
      window.clearTimeout(statusStaleTimerRef.current);
      statusStaleTimerRef.current = window.setTimeout(() => setStatusFresh(false), 12000);
    } catch {
      setHealth({ fay: false, ardy: false, renderer: false, stream: false, checked: true, activeCharacter: null, requestedCharacter: null, availableCharacters: [], rendererSwitchState: "unmanaged", rendererSwitchSupported: false });
      setStatusFresh(false);
      window.clearTimeout(statusStaleTimerRef.current);
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const timer = window.setInterval(refreshHealth, 5000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(statusStaleTimerRef.current);
    };
  }, [refreshHealth]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/wardrobe", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((payload) => {
        if (!cancelled && payload?.profileId === "casual-girl") {
          setWardrobe(payload);
          setWardrobeNotice(payload.installed
            ? "Casual default outfit ready · additional outfits pending"
            : "Asset profile not installed");
        }
      })
      .catch(() => { /* The sealed pending manifest remains visible in static preview. */ });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => fetch("/api/ai-control", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((payload) => {
        if (
          !cancelled
          && payload?.controlConfigId === "ue5-spark-local-ai-control-v1"
          && Array.isArray(payload.modes)
        ) {
          setAiControl(payload);
          setAssetContextAcknowledged(payload.selectedMode === "asset_aware_ai");
        }
      })
      .catch(() => { /* Static preview retains the safe ai_motion default. */ });
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.load();
    video.play().catch(() => setPlaying(false));
  }, [videoSource]);

  useEffect(() => {
    if (!liveFrameUrl) return undefined;
    return () => URL.revokeObjectURL(liveFrameUrl);
  }, [liveFrameUrl]);

  useEffect(() => {
    if (!streamRequested) {
      setStreamState("replay");
      setLiveFrameUrl(null);
      return undefined;
    }

    let cancelled = false;
    let frameSequence = 0;
    let frameTimer = null;
    let activeController = null;
    let pendingImage = null;
    let pendingUrl = null;
    let inFlight = false;

    const discardPending = () => {
      if (pendingImage) {
        pendingImage.onload = null;
        pendingImage.onerror = null;
        pendingImage.src = "";
        pendingImage = null;
      }
      if (pendingUrl) {
        URL.revokeObjectURL(pendingUrl);
        pendingUrl = null;
      }
    };

    const scheduleNext = (delay = 100) => {
      window.clearTimeout(frameTimer);
      if (cancelled || document.hidden) return;
      frameTimer = window.setTimeout(requestFrame, delay);
    };

    const fallBackAndRetry = () => {
      inFlight = false;
      discardPending();
      if (cancelled || document.hidden) return;
      setStreamState("error");
      setLiveFrameUrl(null);
      scheduleNext(350);
    };

    async function requestFrame() {
      if (cancelled || document.hidden || inFlight) return;
      inFlight = true;
      setStreamState((current) => current === "live" ? current : "connecting");
      activeController = new AbortController();
      try {
        const response = await fetch(`/live/frame.jpg?sequence=${frameSequence++}&t=${Date.now()}`, {
          cache: "no-store",
          signal: activeController.signal,
        });
        if (!response.ok) throw new Error(`Frame request failed: ${response.status}`);
        const frameBlob = await response.blob();
        if (!frameBlob.size || (frameBlob.type && !frameBlob.type.startsWith("image/"))) {
          throw new Error("Frame response was not an image");
        }
        if (cancelled || document.hidden) {
          inFlight = false;
          return;
        }

        pendingUrl = URL.createObjectURL(frameBlob);
        pendingImage = new Image();
        pendingImage.onload = () => {
          if (cancelled || document.hidden) {
            inFlight = false;
            discardPending();
            return;
          }
          const decodedUrl = pendingUrl;
          pendingUrl = null;
          pendingImage = null;
          inFlight = false;
          setLiveFrameUrl(decodedUrl);
          setStreamState("live");
          scheduleNext(100);
        };
        pendingImage.onerror = fallBackAndRetry;
        pendingImage.src = pendingUrl;
      } catch (error) {
        inFlight = false;
        if (cancelled || document.hidden) return;
        if (error?.name === "AbortError") {
          scheduleNext(0);
          return;
        }
        fallBackAndRetry();
      } finally {
        activeController = null;
      }
    }

    const handleVisibility = () => {
      window.clearTimeout(frameTimer);
      if (document.hidden) {
        activeController?.abort();
        discardPending();
        inFlight = false;
        return;
      }
      scheduleNext(0);
    };

    document.addEventListener("visibilitychange", handleVisibility);
    setStreamState("connecting");
    scheduleNext(0);

    return () => {
      cancelled = true;
      window.clearTimeout(frameTimer);
      activeController?.abort();
      discardPending();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [streamRequested]);

  useEffect(() => {
    if (liveStage) setNotice("Live Unreal preview · real-time motion");
  }, [liveStage]);

  useEffect(() => {
    setNoticeVisible(true);
    const timer = window.setTimeout(() => setNoticeVisible(false), 3800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!aliveMode || motionLoop || !health.renderer || !health.ardy || !exactRendererSelected || listening || sending) return undefined;
    let cancelled = false;
    let timer = null;
    let controller = null;

    const chooseAction = () => {
      const total = ALIVE_ACTIONS.reduce((sum, item) => sum + item.weight, 0);
      let choice = Math.random() * total;
      for (const item of ALIVE_ACTIONS) {
        choice -= item.weight;
        if (choice <= 0) return item;
      }
      return ALIVE_ACTIONS[0];
    };
    const ranged = ([minimum, maximum]) => minimum + Math.random() * (maximum - minimum);
    const schedule = (first = false) => {
      if (cancelled) return;
      const delay = first ? 2200 + Math.random() * 2200 : 6500 + Math.random() * 7500;
      timer = window.setTimeout(run, delay);
    };
    async function run() {
      if (cancelled) return;
      if (document.hidden || activeSheet === "motion") {
        schedule();
        return;
      }
      const action = chooseAction();
      controller = new AbortController();
      try {
        const response = await fetch("/api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            behavior: action.behavior,
            duration: Number(ranged(action.duration).toFixed(2)),
            intensity: Number(ranged(action.intensity).toFixed(2)),
          }),
          signal: controller.signal,
        });
        const payload = await response.json().catch(() => ({}));
        if (!cancelled && response.ok && payload.live) {
          if (MOTIONS.some((item) => item.id === action.behavior)) setMotion(action.behavior);
          setNotice(`Alive · ${action.label}`);
        }
      } catch (error) {
        if (error?.name !== "AbortError") setNotice("Alive motion paused · renderer unavailable");
      } finally {
        controller = null;
        schedule();
      }
    }

    schedule(true);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller?.abort();
    };
  }, [activeSheet, aliveMode, exactRendererSelected, health.ardy, health.renderer, listening, motionLoop, sending]);

  useEffect(() => {
    if (!motionLoop) return undefined;
    let cancelled = false;
    let timer = null;

    const schedule = (duration) => {
      if (cancelled) return;
      timer = window.setTimeout(repeat, Math.max(0.8, Number(duration) || 2) * 1000 + 180);
    };
    async function repeat() {
      if (cancelled || document.hidden) {
        schedule(1);
        return;
      }
      try {
        const response = await fetch("/api/motion-command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: motionLoop.command }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.status === "staged") throw new Error(payload.detail || "Repeated movement stopped");
        if (payload.behavior) {
          setMotion(payload.behavior);
          setPlaying(true);
        }
        setNotice(`${payload.label || motionLoop.label} · repeating until you stop it`);
        schedule(payload.duration || motionLoop.duration);
      } catch (error) {
        if (cancelled) return;
        setMotionLoop(null);
        setMotionMode("once");
        setNotice(error.message || "Repeated movement stopped");
      }
    }

    schedule(motionLoop.duration);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [motionLoop]);

  useEffect(() => {
    if (cameraPreviewRef.current && cameraStreamRef.current) {
      cameraPreviewRef.current.srcObject = cameraStreamRef.current;
      cameraPreviewRef.current.play().catch(() => {});
    }
  }, [activeSheet, visionState]);

  useEffect(() => () => {
    recognitionRef.current?.abort?.();
    window.speechSynthesis?.cancel?.();
    cameraStreamRef.current?.getTracks?.().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    if (!activeSheet) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setActiveSheet(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    if (activeSheet === "conversation") {
      window.setTimeout(() => inputRef.current?.focus(), 120);
    } else if (activeSheet === "motion") {
      window.setTimeout(() => motionInputRef.current?.focus(), 120);
    }
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activeSheet]);

  async function requestMovement(command) {
    const request = { command };
    if (aiControl.selectedMode === "asset_aware_ai" && assetContextAcknowledged) {
      request.context = {
        schemaVersion: 1,
        characterProfile: character,
        wardrobePreset: character === "casual-girl"
          ? wardrobeSelection.preset
          : "not-applicable",
        cameraFraming: camera,
        stageZoom: Number(stageZoom.toFixed(2)),
        rendererState: liveStage
          ? "live-preview"
          : health.renderer ? "renderer-unstreamed" : "verified-replay",
      };
    }
    const response = await fetch("/api/motion-command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.detail || payload.error || "That movement is not available yet.");
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function applyMovementPayload(payload) {
    setMotionPlan(payload);
    if (payload.behavior) {
      setMotion(payload.behavior);
      setPlaying(true);
    }
  }

  function beginMotionLoop(command, payload) {
    setMotionMode("loop");
    setMotionLoop({
      command,
      label: payload.label || "Movement",
      duration: Number(payload.duration) || 2,
      startedAt: Date.now(),
    });
  }

  async function stopMotionLoop({ announce = true } = {}) {
    if (!motionLoop) return;
    setMotionLoop(null);
    setMotionMode("once");
    if (announce) setNotice(`${motionLoop.label} loop stopped`);
    try {
      const payload = await requestMovement("idle");
      applyMovementPayload(payload);
    } catch { /* The current bounded action will still end on its own. */ }
  }

  async function playMotion(nextMotion) {
    const selected = MOTIONS.find((item) => item.id === nextMotion);
    setMotionLoop(null);
    setMotionMode("once");
    setMotion(nextMotion);
    setPlaying(true);
    setNotice(exactRendererSelected
      ? `Sending ${selected?.label || "motion"} to the live renderer…`
      : `${selected?.label || "Motion"} · verified ${characterName} replay`);
    try {
      const payload = await requestMovement(nextMotion);
      applyMovementPayload(payload);
      if (payload.live) {
        setNotice(liveStage
          ? `${selected?.label || "Motion"} · moving live now`
          : `${selected?.label || "Motion"} sent live · preview connecting`);
      }
    } catch { /* Replay remains available with Unreal offline. */ }
  }

  async function directMovement(event) {
    event.preventDefault();
    const command = motionDraft.trim();
    if (!command || directingMotion) return;
    if (STOP_MOVEMENT_PATTERN.test(command)) {
      const hadLoop = Boolean(motionLoop);
      setMotionDraft("");
      await stopMotionLoop();
      if (!hadLoop) setNotice("No repeated movement is running");
      return;
    }
    const resolvedCommand = movementRouteFor(command) || command;
    const repeatRequested = motionMode === "loop" || LOOP_REQUEST_PATTERN.test(command);
    setMotionLoop(null);
    setDirectingMotion(true);
    setMotionPlan(null);
    setNotice("Checking the reviewed movement catalog…");
    try {
      const payload = await requestMovement(resolvedCommand);
      applyMovementPayload(payload);
      setMotionDraft("");
      if (payload.status === "staged") {
        setMotionMode("once");
        setNotice(`${payload.label} understood · renderer package still pending`);
        return;
      }
      if (repeatRequested) {
        beginMotionLoop(resolvedCommand, payload);
        setNotice(`${payload.label} · repeating until you stop it`);
      } else {
        setNotice(payload.live
          ? `${payload.label} · running once now`
          : `${payload.label} · one verified replay`);
      }
    } catch (error) {
      setMotionPlan({ error: error.message || "Movement director is unavailable." });
      setNotice("Movement was not sent");
    } finally {
      setDirectingMotion(false);
    }
  }

  async function applyWardrobe() {
    if (!wardrobe.installed) {
      setWardrobeNotice("Profile pending · nothing was changed");
      return;
    }
    setWardrobeNotice("Applying reviewed wardrobe…");
    try {
      const response = await fetch("/api/wardrobe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profileId: wardrobe.profileId,
          preset: wardrobeSelection.preset,
          slots: wardrobeSelection.slots,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Wardrobe adapter is not ready.");
      setWardrobeNotice(payload.status === "applied"
        ? "Casual outfit applied live"
        : "Casual outfit queued for the live renderer");
    } catch (error) {
      setWardrobeNotice(error.message || "Wardrobe was not changed");
    }
  }

  async function selectAiControlMode(mode) {
    if (aiControlSaving || mode === aiControl.selectedMode) return;
    const selected = aiControl.modes.find((item) => item.id === mode);
    if (!selected) return;
    if (selected.requiresExplicitLocalOptIn && !assetContextAcknowledged) {
      setNotice("Confirm controller-wide asset context before enabling asset-aware AI");
      return;
    }
    setAiControlSaving(true);
    try {
      const body = mode === "asset_aware_ai"
        ? { mode, acknowledgeAssetContext: true }
        : { mode };
      const response = await fetch("/api/ai-control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || payload.error || "AI-control mode was not changed.");
      setAiControl(payload);
      if (mode !== "asset_aware_ai") setAssetContextAcknowledged(false);
      setNotice(`${selected.label} mode active`);
    } catch (error) {
      setNotice(error.message || "AI-control mode was not changed");
    } finally {
      setAiControlSaving(false);
    }
  }

  function speak(text) {
    if (!deviceVoice || !window.speechSynthesis || !text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.96;
    window.speechSynthesis.speak(utterance);
  }

  async function sendMessage(textOverride) {
    const message = (textOverride ?? draft).trim();
    if (!message || sending) return;
    setMessages((items) => [...items, { id: `user-${Date.now()}`, role: "user", content: message }]);
    setDraft("");
    setSending(true);
    setNotice(`${characterName} is thinking…`);
    try {
      if (STOP_MOVEMENT_PATTERN.test(message)) {
        const hadLoop = Boolean(motionLoop);
        await stopMotionLoop();
        const reply = hadLoop ? "Okay — I stopped the repeated movement." : "There isn’t a repeated movement running right now.";
        setMessages((items) => [...items, { id: `assistant-${Date.now()}`, role: "assistant", content: reply }]);
        setNotice(hadLoop ? "Repeated movement stopped" : "No repeated movement is running");
        speak(reply);
        return;
      }

      const movementCommand = movementRouteFor(message);
      if (movementCommand) {
        try {
          setMotionLoop(null);
          const payload = await requestMovement(movementCommand);
          applyMovementPayload(payload);
          let reply;
          if (payload.status === "staged") {
            setMotionMode("once");
            reply = `I understand ${payload.label.toLowerCase()}, but that movement is not installed in the current renderer yet.`;
            setNotice(`${payload.label} understood · renderer package pending`);
          } else if (LOOP_REQUEST_PATTERN.test(message)) {
            beginMotionLoop(movementCommand, payload);
            reply = `${payload.label} — I’ll repeat it until you tell me to stop.`;
            setNotice(`${payload.label} · repeating until stopped`);
          } else {
            setMotionMode("once");
            reply = payload.live
              ? `${payload.label} — doing it once now.`
              : `${payload.label} — playing the verified fallback once.`;
            setNotice(`${payload.label} · one time`);
          }
          setMessages((items) => [...items, { id: `assistant-${Date.now()}`, role: "assistant", content: reply }]);
          speak(reply);
          return;
        } catch (error) {
          if (error.status !== 422) throw error;
          // Unknown movement wording falls through to Fay instead of pretending it ran.
        }
      }

      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Ada could not answer yet.");
      const reply = String(payload.reply || "").trim() || "I’m here, but I did not receive a complete reply.";
      setMessages((items) => [...items, { id: `assistant-${Date.now()}`, role: "assistant", content: reply }]);
      setNotice(health.renderer ? `Live reply sent to ${characterName}` : "Live Fay reply · device voice preview");
      speak(reply);
    } catch (error) {
      setMessages((items) => [...items, { id: `error-${Date.now()}`, role: "system", content: error.message || "Conversation is unavailable." }]);
      setNotice("Conversation service needs attention");
    } finally { setSending(false); }
  }

  function toggleListening() {
    if (listening) {
      recognitionRef.current?.stop?.();
      setListening(false);
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setNotice("Voice capture is not available here · use the message field");
      window.setTimeout(() => inputRef.current?.focus(), 0);
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.onstart = () => { setListening(true); setNotice("Listening… tap again to stop"); };
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0]?.transcript || "").join(" ").trim();
      setDraft(transcript);
      if (event.results[event.results.length - 1]?.isFinal && transcript) sendMessage(transcript);
    };
    recognition.onerror = () => { setListening(false); setNotice("I couldn’t hear that · try text below"); };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
  }

  async function chooseCharacter(id) {
    const candidate = CHARACTERS.find((item) => item.id === id);
    if (!candidate) return;
    setCharacter(id);
    setMotion(id === "ada" ? "explain" : "idle");
    setPlaying(true);
    setActiveSheet(null);
    if (!health.rendererSwitchSupported || !health.availableCharacters.includes(id)) {
      setNotice(MEDIA[id] ? `${candidate.name} · verified private replay selected` : `${candidate.name} is not in the active renderer package`);
      return;
    }
    setNotice(`Loading ${candidate.name} in Unreal…`);
    try {
      const response = await fetch("/api/character", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: id }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Character switch was not accepted.");
      setNotice(payload.status === "ready" ? `${candidate.name} is live` : `${candidate.name} is starting in Unreal…`);
      refreshHealth();
    } catch (error) {
      setNotice(error.message || `${candidate.name} could not be started`);
    }
  }

  function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    else { video.pause(); setPlaying(false); }
  }

  function finishReplay() {
    if (motionLoop || motion === "idle") return;
    setMotion("idle");
    setPlaying(true);
  }

  function recenter() {
    if (videoRef.current) videoRef.current.currentTime = 0;
    setStageZoom(1);
    setCamera("fit");
    setNotice("Fit shows the entire rendered frame");
  }

  async function toggleVisionPreview() {
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
      if (cameraPreviewRef.current) cameraPreviewRef.current.srcObject = null;
      setVisionState("off");
      setNotice("Phone camera off");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setVisionState("unsupported");
      setNotice("Front-camera preview is unavailable in this browser");
      return;
    }
    setVisionState("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      });
      cameraStreamRef.current = stream;
      if (cameraPreviewRef.current) {
        cameraPreviewRef.current.srcObject = stream;
        await cameraPreviewRef.current.play().catch(() => {});
      }
      setVisionState("local");
      setNotice("Front camera on locally · gaze bridge not connected yet");
    } catch {
      setVisionState("denied");
      setNotice("Camera permission was not granted");
    }
  }

  return (
    <main className="app-shell">
      <section className="avatar-stage" aria-label={`${characterName} avatar stage`}>
        {media ? (
          <video ref={videoRef} className={`avatar-video ${liveStage ? "is-behind-live" : ""}`} style={stageMediaStyle} key={videoSource} autoPlay muted loop={motion === "idle" || Boolean(motionLoop)} playsInline poster={media.poster} aria-hidden={liveStage} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={finishReplay}>
            <source src={videoSource} type="video/mp4" />
          </video>
        ) : (
          <div className="avatar-pending-stage" role="status">
            <UserCircle size={84} weight="light" />
            <strong>{characterName}</strong>
            <span>Selected · renderer package pending</span>
          </div>
        )}
        {liveStage && <img className="avatar-live-frame" style={stageMediaStyle} src={liveFrameUrl} alt={`${characterName} live renderer stream`} draggable="false" />}

        {!chromeHidden ? (
          <>
            <header className="companion-header">
              <div className="companion-identity">
                <span className="companion-name">{characterName}</span>
                <span className="companion-presence">
                  <span className={`status-dot ${systemsReady ? "is-ready" : ""}`} aria-hidden="true" />
                  {liveLabel}
                </span>
              </div>
            </header>

            <nav className="companion-rail" aria-label="Stage shortcuts">
              <button className={`rail-button alive-toggle ${aliveMode ? "is-alive" : ""}`} onClick={() => { setAliveMode((value) => !value); setNotice(aliveMode ? "Alive motion paused" : "Alive motion enabled"); }} type="button" aria-label={aliveMode ? "Pause autonomous movement" : "Enable autonomous movement"} aria-pressed={aliveMode}>
                <Sparkle size={24} weight={aliveMode ? "fill" : "light"} />
              </button>
              <button className="rail-button" onClick={() => motionInputRef.current?.focus()} type="button" aria-label="Focus movement command">
                <PersonSimpleRun size={24} weight="light" />
              </button>
              <button className={`rail-button ${showZoom ? "is-active" : ""}`} onClick={() => setShowZoom((value) => !value)} type="button" aria-label="Adjust avatar framing" aria-expanded={showZoom}>
                <ArrowsInSimple size={24} weight="light" />
              </button>
              <button className={`rail-button ${activeSheet === "settings" ? "is-active" : ""}`} onClick={() => setActiveSheet("settings")} type="button" aria-label="Open character and wardrobe settings" aria-expanded={activeSheet === "settings"}>
                <CoatHanger size={24} weight="light" />
              </button>
              {!liveStage && (
                <button className="rail-button" onClick={togglePlayback} type="button" aria-label={playing ? "Pause avatar replay" : "Play avatar replay"}>
                  {playing ? <Pause size={22} weight="fill" /> : <Play size={22} weight="fill" />}
                </button>
              )}
              <button className="rail-collapse" onClick={() => setChromeHidden(true)} type="button" aria-label="Hide companion controls">
                <CaretDown size={25} weight="bold" />
              </button>
            </nav>

            {showZoom && (
              <div className="stage-zoom-panel" role="group" aria-label="Avatar distance">
                <span className="zoom-readout"><strong>Distance</strong><small>{stageZoom.toFixed(1)}×</small></span>
                <input type="range" min="0.75" max="3" step="0.05" value={stageZoom} onChange={(event) => { setStageZoom(Number(event.target.value)); setCamera("custom"); }} aria-label="Avatar zoom" />
                <button className="zoom-fit" onClick={recenter} type="button">Fit</button>
                <button className="zoom-close" onClick={() => setShowZoom(false)} type="button" aria-label="Close distance control"><X size={15} /></button>
              </div>
            )}

            <div className={`stage-toast ${noticeVisible ? "is-visible" : ""}`} aria-live="polite" aria-atomic="true">
              <span>{notice}</span>
            </div>

            <div className="command-stack">
              <form className="inline-motion-composer" onSubmit={directMovement}>
                <PersonSimpleRun size={20} weight="regular" aria-hidden="true" />
                <input id="inline-motion-command" ref={motionInputRef} value={motionDraft} onChange={(event) => setMotionDraft(event.target.value)} placeholder="Movement: wave, stretch…" maxLength={160} autoComplete="off" enterKeyHint="go" aria-label="Movement command" />
                <span className="motion-mode-toggle" aria-label="Movement repetition">
                  <button className={motionMode === "once" ? "is-selected" : ""} onClick={() => { if (motionLoop) stopMotionLoop(); else setMotionMode("once"); }} type="button" aria-pressed={motionMode === "once"}>Once</button>
                  <button className={motionMode === "loop" ? "is-selected" : ""} onClick={() => { if (motionLoop) stopMotionLoop(); else setMotionMode("loop"); }} type="button" aria-pressed={motionMode === "loop"}>{motionLoop ? "Stop" : "Loop"}</button>
                </span>
                <button className="inline-send motion-send" type="submit" disabled={!motionDraft.trim() || directingMotion} aria-label={motionMode === "loop" ? "Start repeating movement" : "Run movement once"}>{directingMotion ? <CircleNotch className="spin" size={17} /> : <ArrowRight size={17} weight="bold" />}</button>
              </form>

              <nav className="companion-dock" aria-label="Companion controls">
                <button className={`dock-round ${listening ? "is-listening" : ""}`} onClick={toggleListening} type="button" aria-label={listening ? "Stop listening" : `Talk to ${characterName}`}>
                  {listening ? <CircleNotch size={24} weight="bold" className="spin" /> : <Microphone size={24} weight="regular" />}
                </button>
                <button className={`dock-round ${showZoom ? "is-active" : ""}`} onClick={() => setShowZoom((value) => !value)} type="button" aria-label="Adjust avatar distance" aria-expanded={showZoom}>
                  <Camera size={24} weight="regular" />
                </button>
                <form className="inline-chat-composer" onSubmit={(event) => { event.preventDefault(); sendMessage(); }}>
                  <input ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={`Ask ${characterName} anything…`} maxLength={2000} autoComplete="off" enterKeyHint="send" aria-label={`Message ${characterName}`} />
                  <button className="chat-history-button" onClick={() => setActiveSheet("conversation")} type="button" aria-label="Open conversation history"><TextT size={17} weight="bold" /></button>
                  <button className="inline-send chat-send" type="submit" disabled={!draft.trim() || sending} aria-label="Send message">{sending ? <CircleNotch className="spin" size={17} /> : <ArrowRight size={17} weight="bold" />}</button>
                </form>
              </nav>
            </div>
          </>
        ) : (
          <button className="restore-chrome" onClick={() => setChromeHidden(false)} type="button" aria-label="Show companion controls">
            <CaretUp size={24} weight="bold" />
          </button>
        )}
      </section>

      {activeSheet && (
        <div className="sheet-layer">
          <button className="sheet-backdrop" onClick={() => setActiveSheet(null)} type="button" aria-label="Close panel" />
          <aside className={`bottom-sheet ${activeSheet}-sheet`} role="dialog" aria-modal="true" aria-label={sheetMeta.label}>
            <div className="sheet-handle" aria-hidden="true" />
            <header className="sheet-header">
              <div>
                <p className="eyebrow">{sheetMeta.eyebrow}</p>
                <h2>{sheetMeta.title}</h2>
              </div>
              <button className="sheet-close" onClick={() => setActiveSheet(null)} type="button" aria-label="Close panel"><X size={20} /></button>
            </header>

            {activeSheet === "conversation" ? (
              <>
                <div className="sheet-truth"><span className={`status-dot ${systemsReady ? "is-ready" : ""}`} />{health.fay ? "Fay conversation live" : "Conversation limited"}<span aria-hidden="true">·</span><span>{liveStage ? "Stage stream live" : "Stage is replay"}</span></div>
                <div className="transcript" aria-live="polite">
                  {messages.map((message) => (
                    <article className={`message ${message.role}`} key={message.id}><small>{message.role === "assistant" ? characterName : message.role === "user" ? "You" : "System"}</small><p>{message.content}</p></article>
                  ))}
                  {sending && <div className="thinking" aria-label={`${characterName} is thinking`}><span /><span /><span /></div>}
                </div>
                <div className="sheet-composer">
                  <button className={`voice-preview ${deviceVoice ? "is-on" : ""}`} onClick={() => setDeviceVoice((value) => !value)} type="button"><span className="toggle-track"><span /></span>Device voice preview</button>
                  <form className="composer" onSubmit={(event) => { event.preventDefault(); sendMessage(); }}>
                    <ChatCircleDots size={20} /><input ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Type a message" maxLength={2000} aria-label={`Message ${characterName}`} />
                    <button type="submit" disabled={!draft.trim() || sending} aria-label="Send message">{sending ? <CircleNotch className="spin" size={18} /> : <ArrowRight size={18} weight="bold" />}</button>
                  </form>
                </div>
              </>
            ) : activeSheet === "motion" ? (
              <div className="motion-director-content">
                <div className="sheet-truth"><span className={`status-dot ${health.ardy ? "is-ready" : ""}`} />{health.ardy ? "ARDY online" : "Catalog preview"}<span aria-hidden="true">·</span><span>{selectedAiControl?.label || "AI motion"}</span></div>
                <div className="motion-quick-actions" aria-label="Quick movements">
                  {MOTIONS.map(({ id, label, Icon }) => (
                    <button className={motion === id ? "is-active" : ""} key={id} onClick={() => playMotion(id)} type="button" aria-pressed={motion === id}>
                      <Icon size={22} weight="light" /><span>{label}</span>{motion === id && <Check size={13} weight="bold" />}
                    </button>
                  ))}
                </div>
                <p className="motion-director-intro">Describe the body movement you want. The local planner may classify it, but only a reviewed catalog ID with fixed timing and root control can be used.</p>
                <div className="motion-examples" aria-label="Movement examples">
                  {MOTION_COMMAND_EXAMPLES.map((example) => (
                    <button key={example} onClick={() => { setMotionDraft(example); motionInputRef.current?.focus(); }} type="button">{example}</button>
                  ))}
                </div>
                <form className="motion-command-form" onSubmit={directMovement}>
                  <label htmlFor="motion-command">Movement command</label>
                  <div className="motion-command-input">
                    <PersonSimpleRun size={21} />
                    <input id="motion-command" ref={motionInputRef} value={motionDraft} onChange={(event) => setMotionDraft(event.target.value)} placeholder="Try: do jumping jacks" maxLength={160} autoComplete="off" />
                    <button type="submit" disabled={!motionDraft.trim() || directingMotion} aria-label="Plan movement">{directingMotion ? <CircleNotch className="spin" size={18} /> : <ArrowRight size={18} weight="bold" />}</button>
                  </div>
                </form>
                {motionPlan && (
                  <div className={`motion-plan ${motionPlan.error ? "is-error" : motionPlan.status === "staged" ? "is-staged" : "is-routed"}`} aria-live="polite">
                    {motionPlan.error ? (
                      <><strong>Nothing was sent</strong><p>{motionPlan.error}</p></>
                    ) : (
                      <>
                        <div className="motion-plan-heading"><strong>{motionPlan.label}</strong><span>{motionPlan.status === "staged" ? "Recognized · package pending" : motionPlan.live ? "Moving live" : "Routed"}</span></div>
                        <dl>
                          <div><dt>Catalog ID</dt><dd>{motionPlan.catalogId}</dd></div>
                          <div><dt>Duration</dt><dd>{motionPlan.duration}s</dd></div>
                          <div><dt>Intensity</dt><dd>{Math.round(motionPlan.intensity * 100)}%</dd></div>
                          <div><dt>Root</dt><dd>{motionPlan.rootMode}</dd></div>
                        </dl>
                        <p>{motionPlan.detail || (motionPlan.live ? "The reviewed action was sent to Unreal." : "The reviewed replay fallback is active.")}</p>
                      </>
                    )}
                  </div>
                )}
                <div className="prototype-note"><Info size={15} weight="fill" /><span>New full-body entries are staged honestly until their ARDY pose, retarget, and renderer package pass review. A recognized command does not mean the avatar moved.</span></div>
              </div>
            ) : (
              <div className="settings-content">
                <section className="sheet-section">
                  <div className="panel-heading"><span>Framing</span><span className="camera-note">Fit reveals the whole current frame</span></div>
                  <div className="camera-options">
                    <button className={camera === "fit" ? "is-selected" : ""} onClick={() => { setCamera("fit"); setStageZoom(1); setNotice("Entire rendered frame visible · a wider Unreal camera is still pending"); }} type="button"><Person size={21} /><span><strong>Fit frame</strong><small>Available now</small></span></button>
                    <button className={camera === "portrait" ? "is-selected" : ""} onClick={() => { setCamera("portrait"); setStageZoom(1.7); setNotice("Closer portrait framing"); }} type="button"><UserCircle size={21} /><span><strong>Closer</strong><small>1.7× crop</small></span></button>
                    <button onClick={recenter} type="button"><ArrowsInSimple size={21} /><span><strong>Reset</strong><small>Fit current frame</small></span></button>
                  </div>
                </section>
                <section className="sheet-section vision-section">
                  <div className="panel-heading"><span>Phone camera</span><span className={`section-state ${visionState === "local" ? "is-ready" : ""}`}>{visionState === "local" ? "Local preview on" : "Opt-in only"}</span></div>
                  <div className="vision-layout">
                    {visionState === "local" && <video ref={cameraPreviewRef} className="vision-preview" muted playsInline aria-label="Private front camera preview" />}
                    <div className="vision-copy">
                      <strong>{visionState === "local" ? "Your camera is active on this phone" : "Let Ada see your position later"}</strong>
                      <small>This preview stays in your browser. No frames are sent to Fay or Unreal until the reviewed gaze bridge is built.</small>
                      <button onClick={toggleVisionPreview} type="button" disabled={visionState === "requesting"}>{visionState === "requesting" ? "Requesting permission…" : visionState === "local" ? "Turn camera off" : "Enable local preview"}</button>
                    </div>
                  </div>
                </section>
                <section className="sheet-section ai-control-section">
                  <div className="panel-heading"><span>Motion control</span><span className="section-meta">Controller-wide · resets to AI motion</span></div>
                  <div className="ai-control-options" role="radiogroup" aria-label="AI motion control mode">
                    {aiControl.modes.map((item) => (
                      <button
                        className={aiControl.selectedMode === item.id ? "is-selected" : ""}
                        key={item.id}
                        onClick={() => selectAiControlMode(item.id)}
                        type="button"
                        role="radio"
                        aria-checked={aiControl.selectedMode === item.id}
                        disabled={aiControlSaving || (item.requiresExplicitLocalOptIn && !assetContextAcknowledged)}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                  <p className="ai-control-description">{selectedAiControl?.description}</p>
                  <label className="asset-context-opt-in">
                    <input
                      type="checkbox"
                      checked={assetContextAcknowledged}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setAssetContextAcknowledged(checked);
                        if (!checked && aiControl.selectedMode === "asset_aware_ai") {
                          selectAiControlMode("ai_motion");
                        }
                      }}
                    />
                    <span><strong>Enable asset-aware mode for this controller</strong><small>{aiControl.assetAwareNotice} This shared setting is reflected on every connected client. The current v1 adapter sends the selected profile, applicable outfit preset, framing, zoom, and renderer state. Future adapters can add other explicitly selected context through a new validated version.</small></span>
                  </label>
                </section>
                <section className="sheet-section">
                  <div className="panel-heading"><span>Character</span><span className="section-meta">Reviewed profiles only</span></div>
                  <div className="character-list">
                    {CHARACTERS.map((item) => (
                      <button className={`character-button ${character === item.id ? "is-active" : ""} ${!item.ready ? "is-pending" : ""}`} key={item.id} onClick={() => chooseCharacter(item.id)} type="button" aria-pressed={character === item.id}>
                        <UserCircle size={29} weight="light" /><span><strong>{item.name}</strong><small>{item.detail}</small></span>{character === item.id && <Check size={16} weight="bold" />}
                      </button>
                    ))}
                  </div>
                </section>
                <section className="sheet-section wardrobe-section">
                  <div className="panel-heading"><span>Casual Girl wardrobe</span><span className={`section-state ${wardrobe.installed ? "is-ready" : ""}`}>{wardrobe.installed ? "Installed" : "Profile pending"}</span></div>
                  <div className="wardrobe-pending"><CoatHanger size={19} /><span><strong>Sealed controls are ready</strong><small>{wardrobeNotice}</small></span></div>
                  <div className="wardrobe-group">
                    <span className="wardrobe-label">Outfit preset</span>
                    <div className="wardrobe-presets">
                      {wardrobe.presets.map((preset) => (
                        <button className={wardrobeSelection.preset === preset.id ? "is-selected" : ""} key={preset.id} onClick={() => setWardrobeSelection((current) => ({ preset: preset.id, slots: preset.slots || current.slots }))} type="button" disabled={!wardrobe.installed}>{preset.label}</button>
                      ))}
                    </div>
                  </div>
                  <div className="wardrobe-slots">
                    {Object.entries(wardrobe.slots).map(([slot, values]) => (
                      <div className="wardrobe-slot" key={slot}>
                        <span>{slot}</span>
                        <div>
                          {values.map((value) => (
                            <button className={wardrobeSelection.slots[slot] === value.id ? "is-selected" : ""} key={value.id} onClick={() => setWardrobeSelection((current) => ({ ...current, slots: { ...current.slots, [slot]: value.id } }))} type="button" disabled={!wardrobe.installed}>{value.label}</button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  <button className="wardrobe-apply" onClick={applyWardrobe} type="button" disabled={!wardrobe.installed}>Apply reviewed outfit</button>
                  <div className="wardrobe-audit-note"><Info size={15} weight="fill" /><span><strong>Full undress unavailable.</strong> {wardrobe.fullyUnclothed.reason} We will not claim a complete body mesh until the asset profile is installed and inspected.</span></div>
                </section>
                <div className="prototype-note"><Info size={15} weight="fill" /><span>{liveStage ? "The visible stage is the live renderer stream." : "Conversation is live. The visible stage is using the measured private replay fallback."}</span></div>
              </div>
            )}
          </aside>
        </div>
      )}
    </main>
  );
}
