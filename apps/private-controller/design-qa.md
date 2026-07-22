# Design QA

## Evidence

- Source visual truth: the private Product Design reference captured for this task (kept outside the repository).
- Source pixels: 1672 × 941 at 1× density.
- Desktop source crop: 1180 × 793 pixels from the app-owned desktop region.
- Desktop implementation: private QA capture `qa-desktop-match.jpg`, 1180 × 793 CSS pixels at 1× density (ignored by Git).
- Normalized desktop comparison: private QA capture `qa-comparison-desktop.jpg`, source and implementation side by side without scaling (ignored by Git).
- Mobile implementation: private QA capture `qa-deployed-mobile.jpg`, 390 × 844 CSS pixels at 1× density (ignored by Git).
- Current live state: Ada selected, Fay and ARDY ready, the native Unreal
  renderer and fresh frame stream both ready, Portrait framing, and the compact
  mobile stage using the real renderer rather than replay media.

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
- Image quality and asset fidelity: the ready path uses fresh 960 × 540 frames
  from the exact native Unreal window. Mobile crops the black 16:9 studio frame
  with `object-fit: cover` so Ada fills the portrait viewport without inventing
  visual content. Retained real Ada/Aoi captures remain only as the explicit
  unavailable-stream fallback. No placeholder, CSS drawing, generated stand-in,
  or public licensed asset is used.
- Copy and content: live renderer, stream, action, conversation, replay fallback,
  camera availability, and the disabled Fab candidate are named precisely. The
  product does not claim that an unavailable stream or prerecorded movement is
  live.

## Interaction verification

- The private HTTPS deployment simultaneously reported Fay, ARDY, native
  renderer, and fresh frame stream ready.
- The browser decoded the live 960 × 540 frame at 390 × 844, used the mobile
  `cover` crop, and showed no horizontal or page-height overflow.
- Explain dispatched a live request and Unreal logged the real ARDY generated
  provider, bounded playback, crossfade, and return to baked idle. Ada's face
  remained visible in the sampled action and post-action frames.
- The same-origin chat form sent `Reply with exactly: Phone prototype ready.`
  and displayed the exact `Phone prototype ready.` response. Fay accepted the
  reply for transparent TTS and Unreal completed its facial playback.
- Wave remains a deterministic real-time body fallback; retained MP4 media is
  exercised only when the live stream is unavailable.
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
3. Live-stream verification found that `contain` made Ada too small in a tall
   phone viewport. The final mobile pass uses a centered `cover` crop, keeps the
   face unobstructed, confines motion/chat controls to the lower portion, and
   leaves conversation/setup in dismissible sheets.

## Follow-up polish

- Replace the chest-up replay with qualified front and side FullBody captures
  after the new sealed package passes its render gate.
- Test Safari microphone permission and speech recognition on the user's iPhone;
  retain typed conversation as the dependable fallback.

final result: passed
