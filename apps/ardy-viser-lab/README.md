# ARDY Viser Character Lab

This project-owned overlay keeps NVIDIA's official ARDY Interactive Demo as the
motion-generation and 3D-navigation runtime, while limiting the character picker
to:

1. **NVIDIA Original** — the official ARDY Core27 skin.
2. **Casual Girl** — a private modular character with independently selectable
   hair, tops, bottoms, footwear, underwear, and body visibility.

The overlay imports the pinned Apache-2.0 ARDY runtime already present in the
`ue5-spark-ardy-demo:0.1.0` image. It does not modify the vendor checkout or
replace NVIDIA's generation, constraint, timeline, camera, or playback code.

## Private asset layout

Casual Girl data is deliberately not committed. The private directory mounted at
`/characters/casual-girl` must contain:

```text
manifest.json
body.npz
underwear.npz
hair_1.npz
hair_2.npz
top_1.npz
top_3.npz
top_4.npz
shorts.npz
pants.npz
shoes.npz
shoes_socks.npz
```

Every `.npz` is a modular skinned mesh in ARDY coordinates. See
`wardrobe.py::load_part()` for the sealed schema.

The acquired sample's `SK_Top_2` stock FBX export contains a skeleton but no
skinned geometry, so the live manifest deliberately omits it. The three valid
tops remain independently swappable.

## Run on DGX Spark

```bash
scripts/run-ardy-viser-lab-container.sh \
  /path/to/ardy-models \
  /path/to/text-encoder-cache \
  /path/to/private/casual-girl
```

The container listens only on `127.0.0.1:2334`. A separate tailnet-only proxy
can expose that loopback endpoint without changing NVIDIA's original demo on
port 2333.

The installed user service is:

```bash
systemctl --user start ue5-spark-ardy-viser-lab.service
systemctl --user stop ue5-spark-ardy-viser-lab.service
```

## Controls

The **Character & Wardrobe** folder contains the two-character selector and all
Casual Girl modular controls. Selecting `None` removes a category. Swapping a
dropdown changes that category without restarting ARDY or regenerating motion.

The generated motion, prompt timeline, waypoints, constraints, playback, and
camera controls remain NVIDIA's original implementation.

The current private build contains 11 selectable skinned parts: one complete
body assembled from the real torso/head, arms, and legs exports plus ten
wardrobe/hair pieces. Private geometry and generated exports stay outside Git.
