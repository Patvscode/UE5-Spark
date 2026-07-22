import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, ArrowsInSimple, Camera, ChatCircleDots, Check, CircleNotch,
  Ear, HandWaving, Info, Microphone, Pause, Person, Play, SlidersHorizontal,
  Sparkle, UserCircle, X,
} from "@phosphor-icons/react";

const MOTIONS = [
  { id: "wave", label: "Wave", Icon: HandWaving, duration: 2.4 },
  { id: "explain", label: "Explain", Icon: Person, duration: 5 },
  { id: "listen", label: "Listen", Icon: Ear, duration: 3 },
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
  const [notice, setNotice] = useState("Connecting to the live renderer…");
  const [health, setHealth] = useState({ fay: false, ardy: false, renderer: false, stream: false, checked: false });
  const [statusFresh, setStatusFresh] = useState(false);
  const [liveFrameUrl, setLiveFrameUrl] = useState(null);
  const [streamState, setStreamState] = useState("replay");
  const videoRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const statusStaleTimerRef = useRef(null);
  const media = MEDIA[character];
  const videoSource = media[motion] || media.idle;
  const systemsReady = health.fay && health.ardy;
  const streamRequested = health.renderer && health.stream && statusFresh;
  const liveStage = streamRequested && streamState === "live" && Boolean(liveFrameUrl);
  const liveLabel = !health.checked ? "Checking" : liveStage ? "Stage live" : streamRequested && streamState === "error" ? "Replay fallback" : streamRequested ? "Stream connecting" : health.renderer ? "Renderer linked" : systemsReady ? "Systems ready" : "Limited preview";
  const stageModeLabel = liveStage ? "Live Unreal preview" : health.renderer && health.stream ? "Live preview connecting" : health.renderer ? "Renderer live · preview unavailable" : "Verified replay";

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

  useEffect(() => () => {
    recognitionRef.current?.abort?.();
    window.speechSynthesis?.cancel?.();
  }, []);

  useEffect(() => {
    if (!activeSheet) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setActiveSheet(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    if (activeSheet === "conversation") {
      window.setTimeout(() => inputRef.current?.focus(), 120);
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
      const response = await fetch("/api/action", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ behavior: nextMotion, intensity: 0.65, duration: selected?.duration || 2 }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.live) {
        setNotice(liveStage
          ? `${selected?.label || "Motion"} · moving live now`
          : `${selected?.label || "Motion"} sent live · preview connecting`);
      }
    } catch { /* Replay remains available with Unreal offline. */ }
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

  return (
    <main className="app-shell">
      <section className="avatar-stage" aria-label={`${character === "ada" ? "Ada" : "Aoi"} avatar stage`}>
        <div className="stage-topbar">
          <div className="stage-identity">
            <span className="stage-name">{character === "ada" ? "Ada" : "Aoi"}</span>
            <span className={`status-dot ${systemsReady ? "is-ready" : ""}`} aria-hidden="true" />
            <span className="stage-status">{liveLabel}</span>
          </div>
          <div className="stage-actions">
            <div className="stage-mode"><Sparkle size={14} weight="fill" /><span>{stageModeLabel}</span></div>
            {!liveStage && <button className="icon-button" onClick={togglePlayback} type="button" aria-label={playing ? "Pause avatar replay" : "Play avatar replay"}>{playing ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}</button>}
          </div>
        </div>
        <video ref={videoRef} className={`avatar-video ${liveStage ? "is-behind-live" : ""}`} key={videoSource} autoPlay muted loop playsInline poster={media.poster} aria-hidden={liveStage} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}>
          <source src={videoSource} type="video/mp4" />
        </video>
        {liveStage && <img className="avatar-live-frame" src={liveFrameUrl} alt={`${character === "ada" ? "Ada" : "Aoi"} live renderer stream`} draggable="false" />}
        <div className="stage-caption" aria-live="polite">
          <span>{notice}</span>
          <span className="camera-readout"><Camera size={13} />{camera === "full-body" ? "Full-body target" : "Portrait capture"}</span>
        </div>

        <section className="motion-shelf" aria-label="Motion controls">
          <span className="motion-mode">{health.renderer ? "Real-time · ARDY + baked" : "Replay"}</span>
          <div className="motion-list">
            {MOTIONS.map(({ id, label, Icon }) => (
              <button className={`motion-button ${motion === id ? "is-active" : ""}`} key={id} onClick={() => playMotion(id)} type="button" aria-pressed={motion === id}>
                <Icon size={20} weight="light" /><span>{label}</span>{motion === id && <Check className="motion-check" size={13} weight="bold" />}
              </button>
            ))}
          </div>
        </section>

        <nav className="stage-dock" aria-label="Avatar controls">
          <button className={`dock-button ${activeSheet === "conversation" ? "is-active" : ""}`} onClick={() => setActiveSheet("conversation")} type="button" aria-label="Open conversation" aria-expanded={activeSheet === "conversation"}>
            <ChatCircleDots size={23} weight="light" /><span>Chat</span>
          </button>
          <button className={`talk-button ${listening ? "is-listening" : ""}`} onClick={toggleListening} type="button" aria-label={listening ? "Stop listening" : `Talk to ${character === "ada" ? "Ada" : "Aoi"}`}>
            {listening ? <CircleNotch size={25} weight="bold" className="spin" /> : <Microphone size={25} weight="fill" />}<span>{listening ? "Listening" : "Talk"}</span>
          </button>
          <button className={`dock-button ${activeSheet === "settings" ? "is-active" : ""}`} onClick={() => setActiveSheet("settings")} type="button" aria-label="Open camera and character settings" aria-expanded={activeSheet === "settings"}>
            <SlidersHorizontal size={23} weight="light" /><span>Setup</span>
          </button>
        </nav>
      </section>

      {activeSheet && (
        <div className="sheet-layer">
          <button className="sheet-backdrop" onClick={() => setActiveSheet(null)} type="button" aria-label="Close panel" />
          <aside className={`bottom-sheet ${activeSheet}-sheet`} role="dialog" aria-modal="true" aria-label={activeSheet === "conversation" ? "Conversation" : "Camera and character settings"}>
            <div className="sheet-handle" aria-hidden="true" />
            <header className="sheet-header">
              <div>
                <p className="eyebrow">{activeSheet === "conversation" ? "Live Fay conversation" : "Stage setup"}</p>
                <h2>{activeSheet === "conversation" ? `Talk with ${character === "ada" ? "Ada" : "Aoi"}` : "Camera & character"}</h2>
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
                <div className="prototype-note"><Info size={15} weight="fill" /><span>{liveStage ? "The visible stage is the live renderer stream." : "Conversation is live. The visible stage is using the measured private replay fallback."}</span></div>
              </div>
            )}
          </aside>
        </div>
      )}
    </main>
  );
}
