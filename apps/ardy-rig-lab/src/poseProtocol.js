export const PROTOCOL_VERSION = 2;
export const FPS = 20;
export const FRAME_SECONDS = 1 / FPS;
export const COORDINATE_SYSTEM = "ardy-rh-x-left-y-up-z-forward-meters";
export const SOURCE_REVISION = "693f74d13b3d04a0a22ce127ee79c929dd89756b";

export const CORE27_HIERARCHY = Object.freeze([
  ["Hips", null],
  ["Spine", "Hips"],
  ["Spine1", "Spine"],
  ["Spine2", "Spine1"],
  ["Spine3", "Spine2"],
  ["Neck", "Spine3"],
  ["Head", "Neck"],
  ["RightShoulder", "Spine3"],
  ["RightArm", "RightShoulder"],
  ["RightForeArm", "RightArm"],
  ["RightHand", "RightForeArm"],
  ["RightHandEnd", "RightHand"],
  ["RightHandThumb1", "RightHand"],
  ["LeftShoulder", "Spine3"],
  ["LeftArm", "LeftShoulder"],
  ["LeftForeArm", "LeftArm"],
  ["LeftHand", "LeftForeArm"],
  ["LeftHandEnd", "LeftHand"],
  ["LeftHandThumb1", "LeftHand"],
  ["RightUpLeg", "Hips"],
  ["RightLeg", "RightUpLeg"],
  ["RightFoot", "RightLeg"],
  ["RightToeBase", "RightFoot"],
  ["LeftUpLeg", "Hips"],
  ["LeftLeg", "LeftUpLeg"],
  ["LeftFoot", "LeftLeg"],
  ["LeftToeBase", "LeftFoot"],
]);

export const CORE27_JOINTS = Object.freeze(CORE27_HIERARCHY.map(([name]) => name));
export const CORE27_PARENT_INDICES = Object.freeze(CORE27_HIERARCHY.map(([, parent]) => (
  parent === null ? -1 : CORE27_JOINTS.indexOf(parent)
)));

export const NEUTRAL_CORE27_POSITIONS = Object.freeze([
  [0.00, 1.00, 0.00],
  [0.00, 1.10, 0.00],
  [0.00, 1.20, 0.00],
  [0.00, 1.32, 0.00],
  [0.00, 1.44, 0.00],
  [0.00, 1.56, 0.00],
  [0.00, 1.72, 0.00],
  [-0.14, 1.46, 0.00],
  [-0.31, 1.44, 0.00],
  [-0.55, 1.31, 0.00],
  [-0.75, 1.20, 0.00],
  [-0.86, 1.16, 0.00],
  [-0.78, 1.17, 0.06],
  [0.14, 1.46, 0.00],
  [0.31, 1.44, 0.00],
  [0.55, 1.31, 0.00],
  [0.75, 1.20, 0.00],
  [0.86, 1.16, 0.00],
  [0.78, 1.17, 0.06],
  [-0.10, 0.91, 0.00],
  [-0.10, 0.51, 0.01],
  [-0.10, 0.10, 0.05],
  [-0.10, 0.04, 0.24],
  [0.10, 0.91, 0.00],
  [0.10, 0.51, 0.01],
  [0.10, 0.10, 0.05],
  [0.10, 0.04, 0.24],
].map((value) => Object.freeze(value)));

const BATCH_FIELDS = new Set(["version", "sequence", "fps", "coordinateSystem", "source", "frames"]);
const SOURCE_FIELDS = new Set([
  "system", "revision", "skeleton", "jointOrder", "rotationSpace",
  "quaternionOrder", "positionSpace", "contactOrder",
]);
const FRAME_FIELDS = new Set(["time", "root", "joints", "positions", "contacts"]);
const CONTACT_ORDER = ["left_heel", "left_toe", "right_heel", "right_toe"];

function hasExactKeys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finiteVector(value, length) {
  return Array.isArray(value)
    && value.length === length
    && value.every((entry) => typeof entry === "number" && Number.isFinite(entry));
}

function normalizedQuaternion(value) {
  if (!finiteVector(value, 4)) return false;
  const length = Math.hypot(...value);
  return Math.abs(length - 1) <= 0.005;
}

function closeVectors(left, right, tolerance = 0.00001) {
  return left.every((value, index) => Math.abs(value - right[index]) <= tolerance);
}

function sourceIsExact(source) {
  return hasExactKeys(source, SOURCE_FIELDS)
    && source.system === "nv-tlabs/ardy"
    && source.revision === SOURCE_REVISION
    && source.skeleton === "Core27"
    && source.rotationSpace === "local"
    && source.quaternionOrder === "xyzw"
    && source.positionSpace === "global"
    && JSON.stringify(source.jointOrder) === JSON.stringify(CORE27_JOINTS)
    && JSON.stringify(source.contactOrder) === JSON.stringify(CONTACT_ORDER);
}

export function validatePoseBatch(batch) {
  if (!hasExactKeys(batch, BATCH_FIELDS)) throw new Error("ARDY returned an invalid pose envelope.");
  if (batch.version !== PROTOCOL_VERSION || batch.fps !== FPS) {
    throw new Error("ARDY protocol version or frame rate does not match the Rig Lab.");
  }
  if (batch.coordinateSystem !== COORDINATE_SYSTEM || !sourceIsExact(batch.source)) {
    throw new Error("ARDY source skeleton or coordinate contract does not match Core27.");
  }
  if (!Number.isSafeInteger(batch.sequence) || batch.sequence < 1) {
    throw new Error("ARDY returned an invalid sequence number.");
  }
  if (!Array.isArray(batch.frames) || batch.frames.length < 1 || batch.frames.length > 8) {
    throw new Error("ARDY returned an invalid playback batch.");
  }

  let previousTime = -1;
  for (const frame of batch.frames) {
    if (!hasExactKeys(frame, FRAME_FIELDS)) throw new Error("ARDY returned an invalid frame envelope.");
    if (typeof frame.time !== "number" || !Number.isFinite(frame.time) || frame.time <= previousTime) {
      throw new Error("ARDY frame times are not strictly increasing.");
    }
    previousTime = frame.time;
    if (!finiteVector(frame.root, 7) || !normalizedQuaternion(frame.root.slice(3))) {
      throw new Error("ARDY returned an invalid root transform.");
    }
    if (
      !Array.isArray(frame.joints)
      || frame.joints.length !== CORE27_JOINTS.length
      || !frame.joints.every(normalizedQuaternion)
    ) {
      throw new Error("ARDY returned invalid Core27 joint rotations.");
    }
    if (
      !Array.isArray(frame.positions)
      || frame.positions.length !== CORE27_JOINTS.length
      || !frame.positions.every((position) => finiteVector(position, 3))
    ) {
      throw new Error("ARDY returned invalid Core27 global joint positions.");
    }
    if (!closeVectors(frame.root.slice(0, 3), frame.positions[0])) {
      throw new Error("ARDY root and Hips positions disagree.");
    }
    if (
      !finiteVector(frame.contacts, 4)
      || frame.contacts.some((value) => value < 0 || value > 1)
    ) {
      throw new Error("ARDY returned invalid foot contacts.");
    }
  }
  return batch;
}

export function createNeutralFrame() {
  return {
    time: 0,
    root: [...NEUTRAL_CORE27_POSITIONS[0], 0, 0, 0, 1],
    joints: CORE27_JOINTS.map(() => [0, 0, 0, 1]),
    positions: NEUTRAL_CORE27_POSITIONS.map((position) => [...position]),
    contacts: [0, 0, 0, 0],
  };
}

export function defaultRigMapping() {
  return {
    scale: 1,
    yawDegrees: 0,
    mirrorX: false,
    offset: [0, 0, 0],
    jointOffsetsCm: Object.fromEntries(CORE27_JOINTS.map((name) => [name, [0, 0, 0]])),
  };
}

function finiteOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function sanitizeRigMapping(value) {
  const base = defaultRigMapping();
  const scale = Math.min(1.5, Math.max(0.5, finiteOr(value?.scale, 1)));
  const yawDegrees = Math.min(180, Math.max(-180, finiteOr(value?.yawDegrees, 0)));
  const offset = [0, 1, 2].map((index) => (
    Math.min(2, Math.max(-2, finiteOr(value?.offset?.[index], 0)))
  ));
  const jointOffsetsCm = {};
  for (const name of CORE27_JOINTS) {
    jointOffsetsCm[name] = [0, 1, 2].map((index) => (
      Math.min(20, Math.max(-20, finiteOr(value?.jointOffsetsCm?.[name]?.[index], 0)))
    ));
  }
  return {
    scale,
    yawDegrees,
    mirrorX: value?.mirrorX === true,
    offset,
    jointOffsetsCm,
  };
}

export function transformPosePositions(positions, mappingValue) {
  if (
    !Array.isArray(positions)
    || positions.length !== CORE27_JOINTS.length
    || !positions.every((position) => finiteVector(position, 3))
  ) {
    throw new Error("Rig mapping requires exactly 27 finite Core27 positions.");
  }
  const mapping = sanitizeRigMapping(mappingValue);
  const yaw = mapping.yawDegrees * Math.PI / 180;
  const cosine = Math.cos(yaw);
  const sine = Math.sin(yaw);

  return positions.map((position, index) => {
    const trim = mapping.jointOffsetsCm[CORE27_JOINTS[index]].map((value) => value / 100);
    const sourceX = (mapping.mirrorX ? -position[0] : position[0]) + trim[0];
    const sourceY = position[1] + trim[1];
    const sourceZ = position[2] + trim[2];
    const scaledX = sourceX * mapping.scale;
    const scaledY = sourceY * mapping.scale;
    const scaledZ = sourceZ * mapping.scale;
    return [
      scaledX * cosine + scaledZ * sine + mapping.offset[0],
      scaledY + mapping.offset[1],
      -scaledX * sine + scaledZ * cosine + mapping.offset[2],
    ];
  });
}

export function interpolatePositions(left, right, alpha) {
  const weight = Math.min(1, Math.max(0, Number(alpha) || 0));
  return left.map((position, jointIndex) => position.map((value, axis) => (
    value + (right[jointIndex][axis] - value) * weight
  )));
}
