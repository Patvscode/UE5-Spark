import assert from "node:assert/strict";
import test from "node:test";

import {
  characterProfileSummary,
  defaultCharacterProfile,
  parseCharacterProfile,
  sanitizeCharacterProfile,
  serializeCharacterProfile,
} from "../src/characterProfile.js";
import { CORE27_JOINTS } from "../src/poseProtocol.js";

test("character profile has a complete bounded Core27 mapping surface", () => {
  const profile = defaultCharacterProfile({
    modelId: "0123456789abcdef",
    modelName: "Test Person",
  });
  assert.equal(profile.modelId, "0123456789abcdef");
  assert.deepEqual(Object.keys(profile.boneMap), [...CORE27_JOINTS]);
  assert.deepEqual(Object.keys(profile.rotationOffsetsDegrees), [...CORE27_JOINTS]);
  assert.equal(characterProfileSummary(profile).mappedCount, 0);
  assert.equal(profile.rootMotion, false);
});

test("character profile rejects unknown bones and bounds calibration", () => {
  const profile = sanitizeCharacterProfile({
    version: 1,
    name: "  Demo   Rig ",
    modelId: "0123456789abcdef",
    modelName: "Demo",
    boneMap: { Hips: "pelvis", Head: "missing" },
    transform: {
      scale: 999,
      yawDegrees: -999,
      offset: [100, -100, 1],
    },
    rotationOffsetsDegrees: { Hips: [400, -400, 15] },
  }, { availableBones: ["pelvis"] });
  assert.equal(profile.name, "Demo Rig");
  assert.equal(profile.boneMap.Hips, "pelvis");
  assert.equal(profile.boneMap.Head, null);
  assert.equal(profile.transform.scale, 100);
  assert.equal(profile.transform.yawDegrees, -180);
  assert.deepEqual(profile.transform.offset, [20, -20, 1]);
  assert.deepEqual(profile.rotationOffsetsDegrees.Hips, [180, -180, 15]);
  assert.equal(profile.rootMotion, false);
});

test("profile JSON round trips through the reviewed schema", () => {
  const profile = defaultCharacterProfile({
    modelId: "0123456789abcdef",
    modelName: "Portable Human",
  });
  profile.boneMap.Hips = "mixamorigHips";
  const restored = parseCharacterProfile(serializeCharacterProfile(profile), {
    availableBones: ["mixamorigHips"],
  });
  assert.equal(restored.boneMap.Hips, "mixamorigHips");
  assert.throws(() => parseCharacterProfile('{"version":2}'), /not supported/);
});
