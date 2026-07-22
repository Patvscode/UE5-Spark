# Companion-mode design QA

## Evidence

- Source visual truth: `/tmp/codex-remote-attachments/019f7b48-0d14-7751-87d2-08d1b4193263/14EAFA76-E97A-49AA-8570-4E6BCD578A4E/1-Photo-1.jpg`.
- Source pixels: 590 × 1280. The app-owned region was normalized to 390 × 844 at 1× for comparison; the source OS status bar was not recreated.
- Browser-rendered mobile implementation: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-companion-mobile.png`, 390 × 844 CSS pixels normalized to a 390 × 844 image at 1×.
- Same-size comparison: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-comparison-companion-mobile.png`, source and implementation side by side at 390 × 844 each.
- Browser-rendered desktop implementation: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-companion-desktop.png`, 1280 × 720 CSS pixels normalized to 1×.
- State: Ada replay fallback, autonomous Alive mode enabled, no sheet open, dark stage, right shortcut rail, and bottom companion dock.
- Capture method: the in-app browser rendered the real Vite app inside a same-origin 390 × 844 iframe. Two browser viewport captures were stitched at the exact scroll boundary because the browser surface itself remained 1280 × 720.

## Full-view comparison

The implementation now follows the reference hierarchy closely: the character owns the viewport, identity is quiet in the upper-left, shortcuts sit in a slim right rail, and voice/text controls form one bottom dock. Technical status, transcripts, movement details, camera settings, and wardrobe controls are absent from the default stage and open only in dismissible sheets.

The source uses an anime full-body render and branded purple environment. The implementation intentionally uses the real Ada Unreal capture on its real black stage, with no copied branding or synthetic background. Ada is chest-up because that is what the current renderer camera provides; CSS cannot reveal body pixels the renderer did not capture. This is a runtime-package constraint rather than a UI substitution.

Focused region comparison was not necessary after the same-size mobile pass: the name, right rail, character crop, and bottom dock are all legible at 390 × 844 in the combined evidence.

## Required fidelity surfaces

- Fonts and typography: DM Sans gives the identity and controls the same direct sans-serif character as the reference. Name, status, placeholder, and Text mode maintain clear optical hierarchy without recreating the reference logo.
- Spacing and layout rhythm: the stage is uninterrupted; edge controls stay inside iPhone safe-area offsets; the right rail has consistent 9-pixel rhythm; and the four-part bottom dock fits without horizontal overflow at 390 CSS pixels.
- Colors and visual tokens: translucent charcoal controls, white text, mint Alive state, and the real black renderer background preserve contrast. The reference's branded purple treatment was intentionally not copied.
- Image quality and asset fidelity: the character remains real Ada media or the private live Unreal frame. No generated stand-in, CSS illustration, fake full body, or copied character asset is used. Phosphor supplies every interface icon.
- Copy and content: `Ada`, truthful readiness, `Ask Ada anything`, and `Text` are concise. Runtime limitations remain in the relevant sheets instead of covering the character.

## Interaction verification

- Opened and dismissed the movement director from the right rail.
- Confirmed Wave, Explain, and Listen remain functional quick actions inside the sheet.
- Hid all companion chrome and restored it with the single remaining affordance.
- Confirmed the Alive control is visibly enabled and exposes pressed state to assistive technology.
- Confirmed the phone-camera control is explicit opt-in and says that its local preview is not yet sent to Fay or Unreal.
- Browser console contained no errors or warnings after the final reload and interaction pass.
- Production build completed successfully.

## Comparison history

1. Earlier deployed screen had a P1 hierarchy problem: stacked motion, conversation, and camera panels reduced the character to a small preview. The app was changed to a fixed full-viewport stage with on-demand sheets.
2. The first immersive version still placed a permanent caption and motion shelf over Ada's torso. Those P1 obstructions were removed; quick motions moved into the movement sheet, status became a short-lived toast, and shortcuts moved to the edge rail.
3. The 390 × 844 browser pass found no horizontal overflow or persistent central obstruction. The character, rail, and bottom dock remain readable and operable. No actionable P0, P1, or P2 visual issue remains.

## Follow-up polish

- Replace the current portrait renderer camera with the qualified full-body v30 package; that is the remaining visible difference with the reference's character freedom.
- Validate the local camera-permission state on the user's actual iPhone before connecting any reviewed gaze bridge.

final result: passed
