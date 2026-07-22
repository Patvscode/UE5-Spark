# Direct framing and command design QA

## Evidence

- User correction source: `/tmp/codex-remote-attachments/019f7b48-0d14-7751-87d2-08d1b4193263/B4B7BD6B-2CD5-4727-83F2-7C35CD962265/1-Photo-1.jpg`, 590 × 1280.
- Browser-rendered mobile implementation: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-mobile-direct-controls.png`, 390 × 844 CSS pixels at 1×.
- Combined comparison input: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-reference-comparison.png`, source and implementation side by side at 390 × 844 each.
- Capture method: the in-app browser rendered the real Vite app in a same-origin 390 × 844 frame. Two viewport captures were stitched at the exact 720-pixel browser boundary.
- State: Ada replay fallback, autonomous Alive mode on, zoom at Fit/1.0×, no modal open, persistent movement and message fields visible.

## Visual comparison

The supplied screen made Ada fill and overflow the portrait viewport because the landscape renderer image used `object-fit: cover`. The corrected screen uses `contain`, so Fit exposes every pixel in the current Unreal frame. Ada is consequently smaller at the default distance, with a nonmodal 0.75×–3.0× distance control for moving closer. This is honest framing: it does not invent legs or body pixels absent from the current Unreal camera.

The two command rows occupy only the lower edge. Movement is the slimmer upper row; speech, framing, and general chat remain in the primary lower dock. The character, right rail, and stage remain unobstructed above them. At 390 CSS pixels, labels remain legible, text fields stay at 16 pixels to avoid iOS input zoom, and there is no horizontal overflow.

## Interaction verification

- The movement input is permanently present and accepts direct text without opening a sheet.
- Once is selected by default. Loop can be selected inline; the submit control changes to the repeating-action state, and an active loop exposes Stop.
- The ordinary message field is permanently present and its send control becomes enabled after entry.
- Reviewed movement wording in general chat routes through the sealed movement endpoint; unknown wording falls back to Fay instead of pretending a motion ran.
- The distance control opens from both framing shortcuts, exposes the current multiplier and a Fit reset, and media retains `object-fit: contain` at mobile width.
- One-shot fallback clips return to idle instead of replaying forever; explicit loops repeat only until stopped or an error occurs.
- The in-app browser console contained no errors or warnings after the final reload and interaction pass.
- The production build completed successfully.

## Issue resolution

1. P1: mobile cover-crop hid most of Ada and prevented motion assessment. Resolved with full-frame containment plus direct adjustable zoom.
2. P1: movement required a blocking bottom sheet. Resolved with a permanent inline movement composer.
3. P1: the main Ask control opened another sheet instead of accepting text. Resolved with a real inline message field that can also route reviewed movements.
4. P2: movement replay semantics were ambiguous. Resolved with explicit Once/Loop/Stop controls and once-by-default behavior.

No actionable P0, P1, or P2 visual issue remains in the reviewed mobile state.

## Runtime limit

The browser can now reveal the entire current renderer frame, but a true head-to-toe view still requires the wider Unreal camera package. The UI labels Fit as the current frame rather than claiming unsupported full-body output.

final result: passed
