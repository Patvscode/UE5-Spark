# Fay Body Motion

This source-only runtime plugin separates avatar intent, motion generation, and
character retargeting from Fay transport and StreamingADA facial animation.

The current verified boundary provides:

- a fixed behavior allowlist (`idle`, `listen`, `wave`, `invite`, `think`,
  `warn`, `nod`, `shake`, and `explain`);
- deterministic baked-montage precedence for timing-critical gestures;
- character-neutral procedural arm/wrist fallbacks for `wave`, `invite`,
  `think`, `warn`, and `explain` when no reviewed montage is configured;
- automatic fallback to ordinary idle when a service, batch, adapter, or
  unsupported clip is unavailable;
- a strict loopback ARDY client for versioned 20 FPS Core27 batches;
- an eight-frame/400 ms buffer with render-rate quaternion interpolation;
- rejection of malformed, oversized, stale, out-of-order, non-finite, or
  non-Core27 data; and
- forced exclusion of facial, neck, and head ownership from generated motion.

The ARDY client, provider, and guarded UE 5.8 post-evaluation retarget adapter
compile for Linux ARM64. The adapter preserves Ada's proven StreamingADA Body
`ULiveLinkInstance`, calibrates generated rotations against the first buffered
pose, and directly excludes neck, head, and sparse hand endpoints. Missing
bones, malformed data, a buffer underrun, or daemon loss returns control to the
ordinary evaluated pose. The adapter is enabled only after the reviewed
MetaHuman body mapping validates at runtime.

Procedural gestures are deliberately applied after ordinary body evaluation,
use the same reviewed MetaHuman bone map as generated motion, and never touch
the face, neck, or head chain. `nod` and `shake` are accepted by this provider
while their bounded head curves remain exclusively owned by
`FayMetaHumanRuntime`. The procedural angles are a dependable source fallback;
they still require rendered tuning on each new skeleton family, while a
compatible private montage transparently takes precedence.

Licensed character assets, animation montages, checkpoints, prompt embeddings,
and cooked packages are not part of this repository.

For bounded isolation testing, `-FayDisableArdy=1` disables the loopback ARDY
client before its first health probe and disables that component's tick. Baked
and procedural fallbacks remain available. The default is unchanged and keeps
ARDY enabled.
