import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight, ArrowsInSimple, Camera, ChatCircleDots, Check, CircleNotch,
  Ear, HandWaving, Info, Microphone, Pause, Person, Play, SlidersHorizontal,
  Sparkle, UserCircle,
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
  const [camera, setCamera] = useState("full-body");
  const [messages, setMessages] = useState([{
    id: "welcome", role: "assistant",
    content: "Hello, I’m Ada. This trial uses the live Fay brain with verified movement replays while the full-body camera package is prepared.",
  }]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [deviceVoice, setDeviceVoice] = useState(true);
  const [notice, setNotice] = useState("Verified replay · real Ada capture");
  const [health, setHealth] = useState({ fay: false, ardy: false, renderer: false, checked: false });
  const videoRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const media = MEDIA[character];
  const videoSource = media[motion] || media.idle;
  const systemsReady = health.fay && health.ardy;
  const liveLabel = !health.checked ? "Checking" : health.renderer ? "Renderer live" : systemsReady ? "Systems ready" : "Limited preview";

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const payload = await response.json();
      setHealth({ fay: Boolean(payload.fay), ardy: Boolean(payload.ardy), renderer: Boolean(payload.renderer), checked: true });
    } catch {
      setHealth({ fay: false, ardy: false, renderer: false, checked: true });
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const timer = window.setInterval(refreshHealth, 15000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.load();
    video.play().catch(() => setPlaying(false));
  }, [videoSource]);

  useEffect(() => () => {
    recognitionRef.current?.abort?.();
    window.speechSynthesis?.cancel?.();
  }, []);

  async function playMotion(nextMotion) {
    const selected = MOTIONS.find((item) => item.id === nextMotion);
    setMotion(nextMotion);
    setPlaying(true);
    setNotice(`${selected?.label || "Motion"} · verified ${character === "ada" ? "Ada" : "Aoi"} replay`);
    try {
      const response = await fetch("/api/action", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ behavior: nextMotion, intensity: 0.65, duration: selected?.duration || 2 }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.live) setNotice(`${selected?.label || "Motion"} sent to the live renderer`);
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
      inputRef.current?.focus();
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
      <aside className="control-rail" aria-label="Character and motion controls">
        <div className="brand-row">
          <div><p className="eyebrow">Private digital human</p><h1>ADA</h1></div>
          <div className={`live-indicator ${systemsReady ? "is-ready" : ""}`}><span />{liveLabel}</div>
        </div>
        <section className="rail-section motion-section">
          <div className="section-heading"><span>Motion</span><span className="section-meta">ARDY + baked</span></div>
          <div className="motion-list">
            {MOTIONS.map(({ id, label, Icon }) => (
              <button className={`motion-button ${motion === id ? "is-active" : ""}`} key={id} onClick={() => playMotion(id)} type="button">
                <Icon size={22} weight="light" /><span>{label}</span>{motion === id && <Check className="motion-check" size={16} weight="bold" />}
              </button>
            ))}
          </div>
        </section>
        <section className="rail-section character-section">
          <div className="section-heading"><span>Character</span><SlidersHorizontal size={16} weight="light" /></div>
          <div className="character-list">
            {CHARACTERS.map((item) => (
              <button className={`character-button ${character === item.id ? "is-active" : ""} ${!item.ready ? "is-pending" : ""}`} key={item.id} onClick={() => chooseCharacter(item.id)} type="button">
                <UserCircle size={29} weight="light" /><span><strong>{item.name}</strong><small>{item.detail}</small></span>
              </button>
            ))}
          </div>
        </section>
      </aside>

      <section className="avatar-stage" aria-label={`${character === "ada" ? "Ada" : "Aoi"} avatar stage`}>
        <div className="stage-topbar">
          <div className="stage-mode"><Sparkle size={16} weight="fill" /><span>{health.renderer ? "Live renderer" : "Verified replay"}</span></div>
          <button className="icon-button" onClick={togglePlayback} type="button" aria-label={playing ? "Pause avatar replay" : "Play avatar replay"}>{playing ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}</button>
        </div>
        <video ref={videoRef} className="avatar-video" key={videoSource} autoPlay muted loop playsInline poster={media.poster} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}>
          <source src={videoSource} type="video/mp4" />
        </video>
        <div className="stage-caption"><span>{notice}</span><span className="camera-readout"><Camera size={14} />{camera === "full-body" ? "Full-body target" : "Portrait capture"}</span></div>
        <button className={`talk-button ${listening ? "is-listening" : ""}`} onClick={toggleListening} type="button" aria-label={listening ? "Stop listening" : "Talk to Ada"}>
          {listening ? <CircleNotch size={27} weight="bold" className="spin" /> : <Microphone size={27} weight="fill" />}<span>{listening ? "Listening" : "Talk"}</span>
        </button>
      </section>

      <aside className="conversation-panel" aria-label="Conversation and camera controls">
        <section className="caption-panel">
          <div className="panel-heading"><span>Conversation</span><span className={`compact-status ${systemsReady ? "is-ready" : ""}`}><span /> {liveLabel}</span></div>
          <div className="transcript" aria-live="polite">
            {messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}><small>{message.role === "assistant" ? (character === "ada" ? "Ada" : "Aoi") : message.role === "user" ? "You" : "System"}</small><p>{message.content}</p></article>
            ))}
            {sending && <div className="thinking" aria-label="Ada is thinking"><span /><span /><span /></div>}
          </div>
        </section>
        <section className="camera-panel">
          <div className="panel-heading"><span>Camera</span><span className="camera-note">Full body next</span></div>
          <div className="camera-options">
            <button className={camera === "full-body" ? "is-selected" : ""} onClick={() => { setCamera("full-body"); setNotice("Full-body framing selected · new runtime package in progress"); }} type="button"><Person size={21} /><span><strong>Full body</strong><small>Target framing</small></span></button>
            <button className={camera === "portrait" ? "is-selected" : ""} onClick={() => { setCamera("portrait"); setNotice("Portrait · current verified capture"); }} type="button"><UserCircle size={21} /><span><strong>Portrait</strong><small>Available now</small></span></button>
            <button onClick={recenter} type="button"><ArrowsInSimple size={21} /><span><strong>Recenter</strong><small>Restart view</small></span></button>
          </div>
        </section>
        <section className="composer-panel">
          <button className={`voice-preview ${deviceVoice ? "is-on" : ""}`} onClick={() => setDeviceVoice((value) => !value)} type="button"><span className="toggle-track"><span /></span>Device voice preview</button>
          <form className="composer" onSubmit={(event) => { event.preventDefault(); sendMessage(); }}>
            <ChatCircleDots size={20} /><input ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Type a message" maxLength={2000} aria-label="Message Ada" />
            <button type="submit" disabled={!draft.trim() || sending} aria-label="Send message">{sending ? <CircleNotch className="spin" size={18} /> : <ArrowRight size={18} weight="bold" />}</button>
          </form>
          <div className="prototype-note"><Info size={15} weight="fill" /><span>Conversation is live. Stage video is a measured private replay until streaming and full-body framing land.</span></div>
        </section>
      </aside>
    </main>
  );
}
