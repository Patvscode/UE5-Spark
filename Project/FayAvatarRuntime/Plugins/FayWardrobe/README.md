# Fay Wardrobe

`FayWardrobe` is a content-free runtime boundary for modular character clothes
and hair. A reviewed profile maps small logical IDs to component groups already
inside a locally licensed avatar Blueprint. The browser, Fay, MCP, and command
line never supply asset paths or component names.

Configuration is transactional: every slot, item, preset, and component is
validated before visibility changes. Failure leaves the actor untouched. When
the component is reset or destroyed it restores the visibility state it found.

Ordinarily, exactly one `UFayWardrobeBindingComponent` inside a reviewed private
character Blueprint selects a cooked `UFayWardrobeProfileAsset` and complete
default preset. The GameMode resolves that binding after spawn. The native
Casual Girl adapter instead constructs its one installed `casual` preset from
fixed component names compiled into the application; no client constructs that
profile. Characters without either reviewed route keep wardrobe control
disabled.

The component deliberately has no network listener. A private command broker
may call only `ApplyPreset`, `ApplyCompleteSelection`, or `SetSlotItem` after
the sealed profile succeeds. It may not construct profiles from user input.
Hidden component groups also stop ticking and their original visibility/tick
state is restored on reset.

`bAllowFullyUnclothed` defaults to false. Each private item declares whether it
provides anatomical coverage. The runtime derives fully-unclothed state from
the complete selected set for both presets and individual slot changes; the
profile flag is accepted only after manual body/LOD/material inspection.
Hiding outer garments is not treated as proof that a complete base body exists.
