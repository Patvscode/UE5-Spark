# Free Casual Girl integration

The selected second female character is the free Fab listing
[Free Casual Girl Sample (Modular)](https://www.fab.com/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300).
It is a private deployment asset, not repository content.

## What is confirmed

- The Personal and Professional Fab Standard License offers are free.
- The seller describes an Unreal asset pack on the UE5 Epic Skeleton with four
  outfits, two hairstyles, IK bones, and 52 Apple/ARKit facial blendshapes.
- The declared Engine range stops at UE 5.7 and Linux is not in the declared
  target-platform list. UE 5.8 and LinuxArm64 therefore require an isolated
  import, resave, and real cook rather than an assumption.
- Fab's `NoAI` tag forbids use of the asset in generative-AI data collection.
  This project must not train or condition ARDY, Qwen, or another model on its
  meshes, textures, renders, or gallery images. Ordinary licensed rendering and
  deterministic rig control remain separate from model training.

The [Fab Standard License](https://www.fab.com/eula?lang=en) permits modifying
and incorporating the asset into a project. It does not permit redistributing
the asset by itself. Source assets and cooked packages remain private and are
excluded by this repository's ignore rules.

## One user action required

Open the listing while signed into Epic/Fab, choose the free Personal license,
and select **Add to My Library**. Do not send credentials or browser tokens to
the project. The Editor can then install the owned asset from the Fab library.

## Safe import gate

1. Enable Fab only in a disposable staging project. Fab startup can change a
   renderer setting and Add to Project writes the seller's pack at the project
   root, so never enable it in the sealed runtime project.
2. After building the staging Editor and before Add to Project, seal its
   non-content state with `scripts/fab-staging-manifest.py create`. After the
   import, run `verify` against the same private manifest. Any `.uproject`,
   Config, Plugins, Source, or Binaries change fails the gate.
3. Migrate reviewed assets with Unreal's asset tools into
   `/Game/FayFab/CasualGirl`; do not import directly into the sealed v29 tree.
4. Set `FAY_FAB_STAGING_BASELINE_VERIFIED=1` only after that verification, set
   `FAY_FAB_CHARACTER_ASSET` to the migrated Blueprint object path, and run
   `scripts/audit-fab-casual-girl.py` through the graphical UE 5.8 Editor.
5. Review the emitted component, dependency, class, skeleton hierarchy, LOD,
   physics, material, and ARKit morph markers.
6. Manually inspect every body LOD with garments hidden. Confirm whether the
   underwear is a removable mesh, a material layer, or baked into the body.
7. Reject unexpected native binaries, Editor-only hard dependencies, missing
   body regions, broken physics, or Apple-only runtime requirements.
8. Up-convert and resave only inside the private content workspace, then cook a
   minimal LinuxArm64 test before adding it to the production package.

The public pending wardrobe profile is
`config/wardrobe-profiles/CasualGirl.pending.json`. It exposes logical choices,
not asset paths. `allowFullyUnclothed` remains false until the complete body and
all LODs pass the manual audit. This prevents a control from revealing holes,
masked geometry, or an intentionally simplified base body.

## Runtime adapter work

This character is not a MetaHuman. It needs a separate `UE5EpicArkit` adapter:

- a UE5 Epic Skeleton body profile and calibrated ARDY IK Retargeter;
- a direct 52-morph ARKit face adapter rather than MetaHuman's 251 raw controls;
- a project-owned wrapper Blueprint around the seller's private Blueprint;
- reviewed component IDs for every garment and hairstyle;
- an allowlisted wardrobe component that accepts preset/item IDs only; and
- conservative cloth, hair, texture, and LOD settings for the Spark.

The content-free `FayArkitRuntime` adapter and the Casual Girl selection path
have passed focused Linux ARM64 translation-unit compilation on the Spark. This
proves the source is valid for the target architecture; it does not prove the
seller's mesh, morph names, Blueprint dependencies, retargeting, or cooked
runtime until the licensed UE content is imported and audited.

ARDY must not drive face, neck, head, detailed fingers, or any secondary breast
bones. Clothing and hair physics run after the final body pose. The asset is
promoted only after front/side full-body captures, speech/face validation,
wardrobe transitions, failure fallback, and a native LinuxArm64 soak pass.

The runtime wardrobe profile can group several reviewed mesh components into
one logical outfit and stops hidden cloth/hair components from ticking. A
reviewed binding on the private wrapper Blueprint selects the profile and its
complete default preset. Individual slot changes are checked again for body
coverage, so they cannot bypass the independent fully-unclothed approval gate.
