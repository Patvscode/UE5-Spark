# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

The selected direction is Option 3, “Full-body Stage”: a dark, movement-first responsive controller with Ada centered on a stage, allowlisted motion controls, conversation captions, full-body/portrait camera selection, and voice/text input. Keep the distinction between live backend interaction and verified prerecorded renderer media visible until live streaming is genuinely connected.

Durable mobile feedback: the avatar stage must own the full iPhone viewport. Keep only a compact floating motion shelf and bottom dock over the stage; conversation, text chat, camera, and character controls belong in dismissible sheets so the interface never turns into a tall stacked page over the character.

Durable companion-mode feedback: follow the reference hierarchy of a full-screen character, a slim right-edge shortcut rail, and one bottom conversation dock. Keep our own identity and truthful runtime labels; do not copy another product's logo or unsupported camera/upload actions. The entire visible chrome must be collapsible so the character can occupy the screen alone.

Durable movement feedback: free-text body requests belong in a dedicated movement sheet opened from the compact shelf. A local LLM may suggest only a reviewed motion-catalog ID; deterministic code owns the final ID, duration, intensity, root mode, and renderer route. Never present a staged ARDY catalog item as movement that actually occurred.

Durable agency feedback: the default companion may run a bounded Alive loop that autonomously selects only packaged, allowlisted ARDY behaviors with small timing and intensity variation. It must pause during direct user speech or explicit direction, never improvise arbitrary joint data, and never label a replay or staged behavior as live motion.

Durable vision feedback: front-camera access is always explicit opt-in. Until a reviewed gaze bridge actually consumes frames and drives Unreal, expose at most a local browser preview and state plainly that the character cannot see or track the user yet.

Durable wardrobe feedback: expose only sealed Casual Girl preset and garment IDs. Keep the whole wardrobe disabled until the licensed profile is installed, and keep full undress unavailable until an asset audit proves that the base body is complete. Never expose arbitrary Unreal asset paths through the controller.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.
