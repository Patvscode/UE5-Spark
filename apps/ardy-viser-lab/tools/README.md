# Casual Girl FBX conversion

This converter keeps private character geometry outside Git while turning an
Unreal skeletal FBX into the sealed NPZ consumed by `wardrobe.py`.

It uses the single-file [ufbx](https://github.com/ufbx/ufbx) parser locally.
No system package, `sudo`, service, CUDA, or driver change is required.

On the DGX Spark:

```bash
proof="$HOME/Workspace/02_Experiments/ue5-spark-cooker/private-export-proofs/ufbx"
git clone --depth 1 https://github.com/ufbx/ufbx.git "$proof/src"

apps/ardy-viser-lab/tools/build_ufbx_dumper.sh \
  "$proof/src" \
  "$proof/bin/ufbx_dump_skin"

apps/ardy-viser-lab/tools/fbx_to_wardrobe.py \
  --dumper "$proof/bin/ufbx_dump_skin" \
  /private/export/SK_Body.fbx \
  /private/casual-girl/body.npz
```

Repeat the final command for every modular part. All output files contain the
same exact Core27 bone order. UE5 twist, extra-spine, neck, finger, hair, and
cloth-jiggle influences are collapsed onto their nearest Core27 control while
their vertices and normalized weights are retained.

Casual Girl's base is split into torso/head, arms, and legs. Compose the
full removable body after converting those three exports:

```bash
apps/ardy-viser-lab/tools/merge_wardrobe_parts.py \
  --coverage "complete modular body: torso/head + arms + legs" \
  /private/casual-girl/body.npz \
  /private/casual-girl/torso_head.npz \
  /private/casual-girl/arms.npz \
  /private/casual-girl/legs.npz
```

The converter normalizes the FBX at load time to right-handed, Y-up,
+Z-forward meters, matching ARDY/Viser. It bakes the mesh instance transform
into the vertices and records global bind transforms in WXYZ quaternion form.

Casual Girl FBX/NPZ files and textures remain private and must never be added to
Git. Only this converter source belongs in the project repository.
