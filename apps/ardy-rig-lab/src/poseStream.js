import {
  FPS,
  FRAME_SECONDS,
  createNeutralFrame,
  interpolatePoseFrame,
  validatePoseBatch,
} from "./poseProtocol.js";

const BEHAVIORS = new Set([
  "idle", "listen", "explain", "wave", "jog_in_place", "run_in_place",
  "jumping_jacks", "stretch", "dance_relaxed",
]);

function boundedNumber(value, minimum, maximum, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(maximum, Math.max(minimum, number));
}

export class PoseStream {
  constructor({
    fetchImpl = (...args) => globalThis.fetch(...args),
    endpoint = "/v2/poses",
    onState = () => {},
  } = {}) {
    this.fetchImpl = fetchImpl;
    this.endpoint = endpoint;
    this.onState = onState;
    this.currentFrame = createNeutralFrame();
    this.queue = [];
    this.accumulator = 0;
    this.mode = "reference";
    this.active = false;
    this.fetching = false;
    this.sequence = 0;
    this.prompt = "";
    this.behavior = "explain";
    this.intensity = 0.5;
    this.duration = 4;
    this.targetFrames = 0;
    this.requestedFrames = 0;
    this.playedFrames = 0;
    this.lastError = "";
    this.generation = 0;
  }

  snapshot() {
    return {
      mode: this.mode,
      active: this.active,
      fetching: this.fetching,
      sequence: this.sequence,
      bufferedFrames: this.queue.length,
      requestedFrames: this.requestedFrames,
      playedFrames: this.playedFrames,
      targetFrames: Number.isFinite(this.targetFrames) ? this.targetFrames : null,
      prompt: this.prompt,
      behavior: this.behavior,
      lastError: this.lastError,
    };
  }

  _emit() {
    this.onState(this.snapshot());
  }

  async start({ mode, prompt, behavior, intensity, duration }) {
    if (!["once", "loop"].includes(mode)) throw new Error("Motion mode must be once or loop.");
    const normalizedPrompt = String(prompt || "").trim();
    if (normalizedPrompt.length > 512) throw new Error("Prompt must be 512 characters or fewer.");
    if (!BEHAVIORS.has(behavior)) throw new Error("Choose one supported ARDY base behavior.");

    this.generation += 1;
    this.active = true;
    this.fetching = false;
    this.mode = mode;
    this.prompt = normalizedPrompt;
    this.behavior = behavior;
    this.intensity = boundedNumber(intensity, 0, 1, 0.5);
    this.duration = boundedNumber(duration, 0.2, 10, 4);
    this.targetFrames = mode === "once" ? Math.ceil(this.duration * FPS) : Number.POSITIVE_INFINITY;
    this.requestedFrames = 0;
    this.playedFrames = 0;
    this.queue = [];
    this.accumulator = 0;
    this.lastError = "";
    this._emit();
    await this._fillBuffer(this.generation);
  }

  stop() {
    this.generation += 1;
    this.active = false;
    this.mode = this.playedFrames > 0 ? "stopped" : "reference";
    this.queue = [];
    this.accumulator = 0;
    this.fetching = false;
    this._emit();
  }

  resetReference() {
    this.stop();
    this.currentFrame = createNeutralFrame();
    this.mode = "reference";
    this.playedFrames = 0;
    this.requestedFrames = 0;
    this._emit();
  }

  update(deltaSeconds) {
    const delta = Math.min(0.25, Math.max(0, Number(deltaSeconds) || 0));
    this.accumulator += delta;

    while (this.accumulator >= FRAME_SECONDS) {
      this.accumulator -= FRAME_SECONDS;
      if (this.queue.length > 0) {
        this.currentFrame = this.queue.shift();
        this.playedFrames += 1;
        if (
          this.mode === "once"
          && this.playedFrames >= this.targetFrames
          && this.queue.length === 0
        ) {
          this.active = false;
          this.mode = "complete";
          this._emit();
        }
      } else if (this.active && !this.fetching) {
        this.mode = this.mode === "loop" ? "loop" : "buffering";
        this._emit();
      }
    }

    if (
      this.active
      && !this.fetching
      && this.queue.length <= 4
      && (this.mode === "loop" || this.requestedFrames < this.targetFrames)
    ) {
      void this._fillBuffer(this.generation);
    }

    // Keep the original positions-only return value for existing renderers.
    return this.sampleFrame().positions;
  }

  sampleFrame() {
    const next = this.queue[0];
    if (!next) return this.currentFrame;
    return interpolatePoseFrame(
      this.currentFrame,
      next,
      this.accumulator / FRAME_SECONDS,
    );
  }

  samplePose() {
    return this.sampleFrame();
  }

  async _fillBuffer(generation) {
    if (!this.active || this.fetching || generation !== this.generation) return;
    if (this.mode !== "loop" && this.requestedFrames >= this.targetFrames) return;
    this.fetching = true;
    this._emit();

    const request = {
      behavior: this.behavior,
      intensity: this.intensity,
      duration: this.duration,
      afterSequence: this.sequence,
    };
    if (this.prompt) request.prompt = this.prompt;

    try {
      const response = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.error || `ARDY returned HTTP ${response.status}.`);
      }
      const batch = validatePoseBatch(payload);
      if (generation !== this.generation || !this.active) return;

      const remaining = this.mode === "loop"
        ? batch.frames.length
        : Math.max(0, this.targetFrames - this.requestedFrames);
      const acceptedFrames = batch.frames.slice(0, remaining);
      this.queue.push(...acceptedFrames);
      this.requestedFrames += acceptedFrames.length;
      this.sequence = batch.sequence;
      this.mode = this.mode === "loop" ? "loop" : "once";
      this.lastError = "";
    } catch (error) {
      if (generation !== this.generation) return;
      this.active = false;
      this.queue = [];
      this.mode = "error";
      this.lastError = error.message || "ARDY pose generation failed.";
    } finally {
      if (generation === this.generation) {
        this.fetching = false;
        this._emit();
      }
    }
  }
}
