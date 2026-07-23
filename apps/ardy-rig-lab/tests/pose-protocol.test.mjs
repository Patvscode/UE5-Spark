import assert from "node:assert/strict";
import test from "node:test";

import {
  CORE27_JOINTS,
  createNeutralFrame,
  defaultRigMapping,
  transformPosePositions,
  validatePoseBatch,
} from "../src/poseProtocol.js";
import { PoseStream } from "../src/poseStream.js";
import { jsonResponse, poseBatch } from "./helpers.mjs";

test("strict protocol validator accepts the pinned Core27 envelope", () => {
  const batch = poseBatch();
  assert.equal(validatePoseBatch(batch), batch);
  assert.equal(batch.source.jointOrder.length, 27);
  assert.equal(batch.source.jointOrder[0], "Hips");
  assert.equal(batch.source.jointOrder.at(-1), "LeftToeBase");
});

test("strict protocol validator rejects incompatible or malformed motion", () => {
  const wrongVersion = poseBatch();
  wrongVersion.version = 1;
  assert.throws(() => validatePoseBatch(wrongVersion), /version/);

  const wrongSkeleton = poseBatch();
  wrongSkeleton.source.jointOrder = [...CORE27_JOINTS].reverse();
  assert.throws(() => validatePoseBatch(wrongSkeleton), /skeleton|coordinate/);

  const wrongRoot = poseBatch();
  wrongRoot.frames[0].root[0] += 1;
  assert.throws(() => validatePoseBatch(wrongRoot), /root and Hips/);
});

test("rig mapping applies bounded global and per-joint calibration", () => {
  const neutral = createNeutralFrame().positions;
  const mapping = defaultRigMapping();
  mapping.scale = 1.25;
  mapping.yawDegrees = 90;
  mapping.offset = [0.2, -0.1, 0.3];
  mapping.jointOffsetsCm.Head = [10, 0, 0];
  const transformed = transformPosePositions(neutral, mapping);

  assert.equal(transformed.length, 27);
  assert.deepEqual(
    transformed[0].map((value) => Number(value.toFixed(3))),
    [0.2, 1.15, 0.3],
  );
  assert.notDeepEqual(transformed[CORE27_JOINTS.indexOf("Head")], neutral[CORE27_JOINTS.indexOf("Head")]);
});

test("once mode plays only validated service frames and completes", async () => {
  const requests = [];
  const stream = new PoseStream({
    fetchImpl: async (_url, options) => {
      requests.push(JSON.parse(options.body));
      return jsonResponse(poseBatch(1));
    },
  });
  await stream.start({
    mode: "once",
    prompt: "wave naturally",
    behavior: "wave",
    intensity: 0.5,
    duration: 0.4,
  });
  for (let index = 0; index < 8; index += 1) stream.update(0.05);

  assert.equal(requests.length, 1);
  assert.equal(requests[0].prompt, "wave naturally");
  assert.equal(stream.snapshot().playedFrames, 8);
  assert.equal(stream.snapshot().mode, "complete");
  assert.equal(stream.snapshot().active, false);
});

test("invalid service data fails closed without synthesized frames", async () => {
  const stream = new PoseStream({
    fetchImpl: async () => jsonResponse({ version: 2, frames: [] }),
  });
  await stream.start({
    mode: "once",
    prompt: "",
    behavior: "idle",
    intensity: 0.5,
    duration: 1,
  });
  assert.equal(stream.snapshot().mode, "error");
  assert.equal(stream.snapshot().playedFrames, 0);
  assert.deepEqual(stream.currentFrame.positions, createNeutralFrame().positions);
});
