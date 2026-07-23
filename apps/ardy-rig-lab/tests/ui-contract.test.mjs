import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const main = fs.readFileSync(path.join(root, "src/main.js"), "utf8");
const scene = fs.readFileSync(path.join(root, "src/rigScene.js"), "utf8");

test("lab is isolated real WebGL with requested controls", () => {
  assert.match(html, /<canvas id="rig-canvas"/);
  assert.doesNotMatch(html, /<video|\.mp4/i);
  assert.match(scene, /from "three"/);
  assert.match(scene, /OrbitControls/);
  for (const marker of [
    "Motion prompt",
    "Run once",
    "Loop",
    "Rig mapping",
    "Joint markers",
    "Chair blocks",
    "Bed blocks",
  ]) {
    assert.match(html, new RegExp(marker));
  }
  assert.match(main, /window\.render_game_to_text/);
  assert.match(main, /window\.advanceTime/);
  assert.match(main, /dynamicTextReady/);
  assert.match(main, /no fallback motion is simulated/);
});
