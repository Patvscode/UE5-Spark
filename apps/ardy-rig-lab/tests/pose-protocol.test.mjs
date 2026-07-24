import assert from "node:assert/strict";
import test from "node:test";

import {
  CORE27_JOINTS,
  createNeutralFrame,
  defaultRigMapping,
  interpolatePoseFrame,
  interpolateQuaternion,
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

test("XYZW quaternion interpolation follows the shortest normalized arc", () => {
  const quarterTurn = [0, 0, Math.SQRT1_2, Math.SQRT1_2];
  const midpoint = interpolateQuaternion([0, 0, 0, 1], quarterTurn, 0.5);
  const signFlippedMidpoint = interpolateQuaternion([0, 0, 0, 1], quarterTurn.map((value) => -value), 0.5);

  assert.deepEqual(
    midpoint.map((value) => Number(value.toFixed(6))),
    [0, 0, 0.382683, 0.92388],
  );
  assert.deepEqual(
    signFlippedMidpoint.map((value) => Number(value.toFixed(6))),
    midpoint.map((value) => Number(value.toFixed(6))),
  );
  assert.ok(Math.abs(Math.hypot(...midpoint) - 1) < 1e-12);
});

test("full pose interpolation samples root, joints, positions, contacts, and time", () => {
  const left = createNeutralFrame();
  const right = createNeutralFrame();
  right.time = 0.05;
  right.root[0] = 0.2;
  right.root.splice(3, 4, 0, 0, 1, 0);
  right.positions[0][0] = 0.2;
  right.positions[CORE27_JOINTS.indexOf("Head")][2] = 0.4;
  right.joints[CORE27_JOINTS.indexOf("Head")] = [0, 0, 1, 0];
  right.contacts = [1, 0.75, 0.5, 0.25];

  const sampled = interpolatePoseFrame(left, right, 0.5);
  assert.equal(sampled.time, 0.025);
  assert.equal(sampled.root[0], 0.1);
  assert.deepEqual(
    sampled.root.slice(3).map((value) => Number(value.toFixed(6))),
    [0, 0, 0.707107, 0.707107],
  );
  assert.equal(sampled.positions[0][0], sampled.root[0]);
  assert.equal(sampled.positions[CORE27_JOINTS.indexOf("Head")][2], 0.2);
  assert.deepEqual(
    sampled.joints[CORE27_JOINTS.indexOf("Head")].map((value) => Number(value.toFixed(6))),
    [0, 0, 0.707107, 0.707107],
  );
  assert.deepEqual(sampled.contacts, [0.5, 0.375, 0.25, 0.125]);
  assert.deepEqual(left.contacts, [0, 0, 0, 0]);
});

test("PoseStream exposes a full interpolated sample while update stays positions-only", () => {
  const stream = new PoseStream();
  const next = createNeutralFrame();
  next.time = 0.05;
  next.root[2] = 0.2;
  next.positions[0][2] = 0.2;
  next.root.splice(3, 4, 0, 0, 1, 0);
  next.joints[0] = [0, 0, 1, 0];
  next.contacts = [1, 0, 1, 0];
  stream.queue = [next];

  const positions = stream.update(0.025);
  const frame = stream.sampleFrame();
  assert.ok(Array.isArray(positions));
  assert.equal(positions.length, CORE27_JOINTS.length);
  assert.equal(frame.root[2], 0.1);
  assert.equal(frame.positions[0][2], 0.1);
  assert.deepEqual(frame.contacts, [0.5, 0, 0.5, 0]);
  assert.deepEqual(stream.samplePose(), frame);
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
