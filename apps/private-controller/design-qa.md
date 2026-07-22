# Design QA

## Evidence

- Source visual truth: `/Users/patrickmello/.codex/generated_images/019f7b48-0d14-7751-87d2-08d1b4193263/exec-5d4f19a0-a8ba-4d9f-bef3-cbe1d032d105.png`
- Source pixels: 1672 × 941 at 1× density.
- Desktop source crop: 1180 × 793 pixels from the app-owned desktop region.
- Desktop implementation: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-desktop-match.jpg`, 1180 × 793 CSS pixels at 1× density.
- Normalized desktop comparison: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-comparison-desktop.jpg`, source and implementation side by side without scaling.
- Mobile implementation: `/Users/patrickmello/UE5-Spark/apps/private-controller/qa-deployed-mobile.jpg`, 390 × 844 CSS pixels at 1× density.
- State: Ada selected, Explain initially selected, Full body selected as the pending target, Fay and ARDY ready, renderer honestly reported as verified replay.

## Full-view comparison

The implementation preserves the selected direction's three-region desktop
composition: narrow movement rail, dominant black avatar stage, and conversation
plus camera rail. Mobile collapses the same hierarchy into brand, stage, motion
shelf, transcript, camera controls, and composer. The reference uses a generated
full-body concept image; the implementation intentionally uses the real measured
Ada renderer capture and labels the full-body package as pending. That difference
is an explicit product truth boundary, not an attempted visual substitute.

No focused crop was required: the full-view comparison renders the typography,
control borders, icon treatment, camera selection, status indicators, stage
caption, and composer at readable size.

## Required fidelity surfaces

- Fonts and typography: DM Sans matches the compact utilitarian controls and
  Cormorant Garamond recreates the high-contrast ADA wordmark. Weight, line
  height, hierarchy, and wrapping remain legible at both tested breakpoints.
- Spacing and layout rhythm: rail widths, stage dominance, 8–12 pixel control
  gaps, rounded panels, and mobile shelf spacing follow the reference. No
  horizontal overflow was observed at 390 CSS pixels.
- Colors and tokens: near-black canvas, graphite panels, quiet gray copy, mint
  readiness/selection, and warm microphone treatment match the reference's
  palette without decorative gradients.
- Image quality and asset fidelity: the stage uses real private Ada/Aoi captures
  at their native aspect ratio. No placeholder, CSS drawing, generated stand-in,
  or public licensed asset is used. The actual Ada media is chest-up until the
  reviewed FullBody package is cooked; the interface states this directly.
- Copy and content: live conversation, verified replay, renderer state, camera
  availability, and the disabled Fab candidate are named precisely. The product
  does not claim that prerecorded movement is a live video stream.

## Interaction verification

- The private HTTPS deployment loaded with Fay and ARDY reported ready.
- Wave changed the selected motion, stage caption, and playing media to the real
  `/media/ada-wave.mp4` asset; the browser reported ready state 4 and playback.
- The same-origin chat form sent `Reply with exactly: Mobile trial ready.` and
  displayed Fay's exact `Mobile trial ready.` response.
- Pause/play, Portrait/Full body selection, recenter, device-voice toggle, Ada/Aoi
  replay switching, disabled Fab candidate behavior, loading, and error states
  are implemented.
- Initial deployed-page console inspection returned no warnings or errors.
- Microphone permission was not accepted during automated QA. The control falls
  back to the text composer when browser speech recognition is unavailable.

## Comparison history

1. First desktop pass found that the source's full-body concept could not be
   represented honestly by the existing chest-up runtime capture. The UI was
   kept on real media and given explicit `Verified replay`, `Full-body target`,
   `Available now`, and pending-package labels instead of presenting generated
   imagery as runtime evidence.
2. Mobile verification confirmed the stage, controls, transcript, and camera
   sections fit at 390 × 844 with no horizontal overflow. No P0, P1, or P2 visual
   issues remained after the truth-labeling and responsive pass.

## Follow-up polish

- Replace the chest-up replay with qualified front and side FullBody captures
  after the new sealed package passes its render gate.
- Test Safari microphone permission and speech recognition on the user's iPhone;
  retain typed conversation as the dependable fallback.

final result: passed
