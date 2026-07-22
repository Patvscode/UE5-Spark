# Fay Wardrobe

`FayWardrobe` is a content-free runtime boundary for modular character clothes
and hair. A reviewed profile maps small logical IDs to component names already
inside a locally licensed avatar Blueprint. The browser, Fay, MCP, and command
line never supply asset paths or component names.

Configuration is transactional: every slot, item, preset, and component is
validated before visibility changes. Failure leaves the actor untouched. When
the component is reset or destroyed it restores the visibility state it found.

The component deliberately has no network listener. A future private command
broker may call only `ApplyPreset` or `SetSlotItem` after selecting a sealed
profile. It may not construct profiles from user input.

`bAllowFullyUnclothed` defaults to false. A preset marked fully unclothed is
accepted only when that packaged profile explicitly enables it after manual
body/LOD/material inspection. Hiding outer garments is not treated as proof
that a complete base body exists.
