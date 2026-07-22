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
  { id: "aoi", name: "Aoi", detail: "Portability replay", ready: true },
  { id: "fab-candidate", name: "Casual Girl", detail: "Fab compatibility review", ready: false },
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

export function App() {
  const [character, setCharacter] = useState("ada");
  const [motion, setMotion] = useState("explain");
  const [camera, setCamera] = useState("portrait");
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
  const [directingMotion, setDirectingMotion] = useState(false);
  const [motionPlan, setMotionPlan] = useState(null);
  const [wardrobe, setWardrobe] = useState(PENDING_WARDROBE);
  const [wardrobeSelection, setWardrobeSelection] = useState({
    preset: "casual",
    slots: { top: "tank", bottom: "pants", feet: "shoes_socks", hair: "style_1" },
  });
  const [wardrobeNotice, setWardrobeNotice] = useState("Licensed asset profile not installed");
  const [notice, setNotice] = useState("Connecting to the live renderer…");
  const [health, setHealth] = useState({ fay: false, ardy: false, renderer: false, stream: false, checked: false });
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
  const media = MEDIA[character];
  const videoSource = media[motion] || media.idle;
  const systemsReady = health.fay && health.ardy;
  const streamRequested = health.renderer && health.stream && statusFresh;
  const liveStage = streamRequested && streamState === "live" && Boolean(liveFrameUrl);
  const liveLabel = !health.checked ? "Checking" : liveStage ? "Stage live" : streamRequested && streamState === "error" ? "Replay fallback" : streamRequested ? "Stream connecting" : health.renderer ? "Renderer linked" : systemsReady ? "Systems ready" : "Limited preview";
  const characterName = character === "ada" ? "Ada" : "Aoi";
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
      setHealth({ fay: Boolean(payload.fay), ardy: Boolean(payload.ardy), renderer: Boolean(payload.renderer), stream: Boolean(payload.stream), checked: true });
      setStatusFresh(true);
      window.clearTimeout(statusStaleTimerRef.current);
      statusStaleTimerRef.current = window.setTimeout(() => setStatusFresh(false), 12000);
    } catch {
      setHealth({ fay: false, ardy: false, renderer: false, stream: false, checked: true });
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
        if (!cancelled && payload?.profileId === "casual-girl") setWardrobe(payload);
      })
      .catch(() => { /* The sealed pending manifest remains visible in static preview. */ });
    return () => { cancelled = true; };
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
    if (!aliveMode || !health.renderer || !health.ardy || listening || sending) return undefined;
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
  }, [activeSheet, aliveMode, health.ardy, health.renderer, listening, sending]);

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

  async function playMotion(nextMotion) {
    const selected = MOTIONS.find((item) => item.id === nextMotion);
    setMotion(nextMotion);
    setPlaying(true);
    setNotice(health.renderer
      ? `Sending ${selected?.label || "motion"} to the live renderer…`
      : `${selected?.label || "Motion"} · verified ${character === "ada" ? "Ada" : "Aoi"} replay`);
    try {
      const response = await fetch("/api/motion-command", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: nextMotion }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.live) {
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
    setDirectingMotion(true);
    setMotionPlan(null);
    setNotice("Checking the reviewed movement catalog…");
    try {
      const response = await fetch("/api/motion-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || payload.error || "That movement is not available yet.");
      setMotionPlan(payload);
      if (payload.status === "staged") {
        setNotice(`${payload.label} understood · renderer package still pending`);
        return;
      }
      if (payload.behavior) {
        setMotion(payload.behavior);
        setPlaying(true);
      }
      setNotice(payload.live
        ? `${payload.label} · moving live now`
        : `${payload.label} · routed to the verified replay fallback`);
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
      setWardrobeNotice("Wardrobe applied");
    } catch (error) {
      setWardrobeNotice(error.message || "Wardrobe was not changed");
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
    setNotice("Ada is thinking…");
    try {
      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Ada could not answer yet.");
      const reply = String(payload.reply || "").trim() || "I’m here, but I did not receive a complete reply.";
      setMessages((items) => [...items, { id: `assistant-${Date.now()}`, role: "assistant", content: reply }]);
      setNotice(health.renderer ? "Live reply sent to Ada" : "Live Fay reply · device voice preview");
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
      setNotice("Voice capture is not available here · type below instead");
      setActiveSheet("conversation");
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

  function chooseCharacter(id) {
    const candidate = CHARACTERS.find((item) => item.id === id);
    if (!candidate?.ready) {
      setNotice("Free Casual Girl saved for compatibility and license review");
      return;
    }
    if (health.renderer && id !== "ada") {
      setNotice(`${candidate.name} needs a reviewed renderer restart · keeping Ada live`);
      return;
    }
    setCharacter(id);
    setMotion(id === "ada" ? "explain" : "idle");
    setNotice(`${candidate.name} · verified private replay`);
  }

  function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    else { video.pause(); setPlaying(false); }
  }

  function recenter() {
    if (videoRef.current) videoRef.current.currentTime = 0;
    setNotice("Stage recentered");
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
      <section className="avatar-stage" aria-label={`${character === "ada" ? "Ada" : "Aoi"} avatar stage`}>
        <video ref={videoRef} className={`avatar-video ${liveStage ? "is-behind-live" : ""}`} key={videoSource} autoPlay muted loop playsInline poster={media.poster} aria-hidden={liveStage} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}>
          <source src={videoSource} type="video/mp4" />
        </video>
        {liveStage && <img className="avatar-live-frame" src={liveFrameUrl} alt={`${character === "ada" ? "Ada" : "Aoi"} live renderer stream`} draggable="false" />}

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
              <button className={`rail-button ${activeSheet === "motion" ? "is-active" : ""}`} onClick={() => setActiveSheet("motion")} type="button" aria-label="Open movement director" aria-expanded={activeSheet === "motion"}>
                <PersonSimpleRun size={24} weight="light" />
              </button>
              <button className="rail-button" onClick={recenter} type="button" aria-label="Recenter avatar stage">
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

            <div className={`stage-toast ${noticeVisible ? "is-visible" : ""}`} aria-live="polite" aria-atomic="true">
              <span>{notice}</span>
            </div>

            <nav className="companion-dock" aria-label="Companion controls">
              <button className={`dock-round ${listening ? "is-listening" : ""}`} onClick={toggleListening} type="button" aria-label={listening ? "Stop listening" : `Talk to ${characterName}`}>
                {listening ? <CircleNotch size={24} weight="bold" className="spin" /> : <Microphone size={24} weight="regular" />}
              </button>
              <button className={`dock-round ${activeSheet === "settings" ? "is-active" : ""}`} onClick={() => setActiveSheet("settings")} type="button" aria-label="Open camera settings" aria-expanded={activeSheet === "settings"}>
                <Camera size={24} weight="regular" />
              </button>
              <button className={`dock-round ${activeSheet === "motion" ? "is-active" : ""}`} onClick={() => setActiveSheet("motion")} type="button" aria-label="Direct a body movement" aria-expanded={activeSheet === "motion"}>
                <PersonSimpleRun size={24} weight="regular" />
              </button>
              <button className={`conversation-launch ${activeSheet === "conversation" ? "is-active" : ""}`} onClick={() => setActiveSheet("conversation")} type="button" aria-label={`Open text conversation with ${characterName}`} aria-expanded={activeSheet === "conversation"}>
                <span className="conversation-placeholder">Ask {characterName} anything</span>
                <span className="conversation-text-mode"><ChatCircleDots size={19} weight="regular" /><TextT size={18} weight="bold" /><span>Text</span></span>
              </button>
            </nav>
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
                    <article className={`message ${message.role}`} key={message.id}><small>{message.role === "assistant" ? (character === "ada" ? "Ada" : "Aoi") : message.role === "user" ? "You" : "System"}</small><p>{message.content}</p></article>
                  ))}
                  {sending && <div className="thinking" aria-label={`${character === "ada" ? "Ada" : "Aoi"} is thinking`}><span /><span /><span /></div>}
                </div>
                <div className="sheet-composer">
                  <button className={`voice-preview ${deviceVoice ? "is-on" : ""}`} onClick={() => setDeviceVoice((value) => !value)} type="button"><span className="toggle-track"><span /></span>Device voice preview</button>
                  <form className="composer" onSubmit={(event) => { event.preventDefault(); sendMessage(); }}>
                    <ChatCircleDots size={20} /><input ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Type a message" maxLength={2000} aria-label={`Message ${character === "ada" ? "Ada" : "Aoi"}`} />
                    <button type="submit" disabled={!draft.trim() || sending} aria-label="Send message">{sending ? <CircleNotch className="spin" size={18} /> : <ArrowRight size={18} weight="bold" />}</button>
                  </form>
                </div>
              </>
            ) : activeSheet === "motion" ? (
              <div className="motion-director-content">
                <div className="sheet-truth"><span className={`status-dot ${health.ardy ? "is-ready" : ""}`} />{health.ardy ? "ARDY online" : "Catalog preview"}<span aria-hidden="true">·</span><span>Fixed safe parameters</span></div>
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
                  <div className="panel-heading"><span>Camera</span><span className="camera-note">Full body is the next runtime package</span></div>
                  <div className="camera-options">
                    <button className={camera === "full-body" ? "is-selected" : ""} onClick={() => { setCamera("full-body"); setNotice("Full-body framing selected · new runtime package in progress"); }} type="button"><Person size={21} /><span><strong>Full body</strong><small>Target framing</small></span></button>
                    <button className={camera === "portrait" ? "is-selected" : ""} onClick={() => { setCamera("portrait"); setNotice("Portrait · current verified capture"); }} type="button"><UserCircle size={21} /><span><strong>Portrait</strong><small>Available now</small></span></button>
                    <button onClick={recenter} type="button"><ArrowsInSimple size={21} /><span><strong>Recenter</strong><small>Restart replay</small></span></button>
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
                  <div className="wardrobe-audit-note"><Info size={15} weight="fill" /><span><strong>Full undress unavailable.</strong> {wardrobe.fullyUnclothed.reason} We will not claim a complete body mesh until the licensed asset is installed and inspected.</span></div>
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
