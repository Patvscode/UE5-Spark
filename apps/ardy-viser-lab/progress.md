Original prompt: Use NVIDIA's original ARDY Viser app as the base, support only NVIDIA Original and Casual Girl, and give full Casual Girl hair/clothing add/remove/swap controls.

## 2026-07-23

- Confirmed the installed official ARDY demo is pinned at revision
  `693f74d13b3d04a0a22ce127ee79c929dd89756b` and licensed Apache-2.0.
- Confirmed its Viser 1.0.16 runtime exposes `add_mesh_skinned()` with live bone
  handles, so modular Casual Girl pieces can use the official ARDY pose stream.
- Chose a project-owned overlay rather than modifying the vendor checkout.
- Scoped the new lab to exactly `NVIDIA Original` and `Casual Girl`; Ada and Aoi
  are not loaded or shown here.
- Added the sealed private wardrobe manifest/NPZ loader, two-character UI, live
  Casual Girl character adapter, and an isolated container launcher.
- Casual Girl's Unreal assets remain private and are never added to Git.
- Fixed live wardrobe swaps so every newly rebuilt piece immediately inherits
  the last rendered ARDY pose. Previously, swapping while playback was paused
  left that one piece at the bind-pose origin until the next animation frame,
  which could make it appear displaced near the character's feet.
- Exported the real Casual Girl body, arms, legs, two hairstyles, underwear,
  three valid tops, two bottoms, and two footwear variants from the isolated
  Unreal copy. The original UAssets were restored and hash-matched.
- Converted every valid part to the exact Core27 bone order and merged the real
  torso/head, arms, and legs into one complete body:
  - 56,822 body vertices
  - 101,118 body triangles
  - all 27 Core bones active
- Created and validated the private 11-part manifest. `SK_Top_2` was omitted
  because its stock FBX export contains no mesh/Skin deformer.
- Deployed the isolated user service on loopback port 2334 and exposed it only
  to the private tailnet on port 8477.
- Stopped, without disabling or deleting, the previous packaged avatar,
  duplicate ARDY daemon, private controller, and prior rig-lab service so the
  official app has enough unified memory and cannot capture the desktop mouse.
- Live browser QA passed:
  - exactly two characters: NVIDIA Original and Casual Girl
  - both characters rendered and switched without errors
  - every valid hair/clothing option was present
  - `None` removal and alternate-piece swaps updated live
  - no browser console errors were observed

## Next gate

- Preserve the passing source milestone in Git.
- Add exact material textures in a later visual-fidelity pass; the first live
  lab intentionally uses reviewed per-part colors while preserving real
  geometry and skinning.
