# Fay Body Motion

This source-only runtime plugin separates avatar intent, motion generation, and
character retargeting from Fay transport and StreamingADA facial animation.

The current verified boundary provides:

- a fixed behavior allowlist (`idle`, `listen`, `wave`, `invite`, `think`,
  `warn`, `nod`, `shake`, and `explain`);
- deterministic baked-montage precedence for timing-critical gestures;
- automatic fallback to baked idle when a clip, service, batch, or adapter is
  unavailable;
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

Licensed character assets, animation montages, checkpoints, prompt embeddings,
and cooked packages are not part of this repository.
