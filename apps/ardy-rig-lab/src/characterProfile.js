import { CORE27_JOINTS } from "./poseProtocol.js";

export const CHARACTER_PROFILE_VERSION = 1;
export const CHARACTER_PROFILE_KIND = "ue5-spark-ardy-character-profile";

function finiteOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function bounded(value, minimum, maximum, fallback) {
  return Math.min(maximum, Math.max(minimum, finiteOr(value, fallback)));
}

function cleanText(value, fallback, maximumLength = 96) {
  const text = String(value || "").trim().replace(/\s+/g, " ");
  return (text || fallback).slice(0, maximumLength);
}

function cleanModelId(value) {
  const text = String(value || "").trim();
  return /^[a-f0-9]{16,64}$/i.test(text) ? text.toLowerCase() : "";
}

function cleanStableId(value, maximumLength = 2048) {
  const text = String(value || "").trim();
  return text.length <= maximumLength && !/[\u0000-\u001f\u007f]/.test(text) ? text : "";
}

export function defaultCharacterProfile({
  modelId = "",
  modelName = "Imported character",
  name = "",
} = {}) {
  const reviewedModelName = cleanText(modelName, "Imported character");
  return {
    kind: CHARACTER_PROFILE_KIND,
    version: CHARACTER_PROFILE_VERSION,
    name: cleanText(name, reviewedModelName),
    modelId: cleanModelId(modelId),
    modelName: reviewedModelName,
    skeletonId: "",
    boneMap: Object.fromEntries(CORE27_JOINTS.map((joint) => [joint, null])),
    transform: {
      scale: 1,
      yawDegrees: 0,
      pitchDegrees: 0,
      rollDegrees: 0,
      offset: [0, 0, 0],
    },
    rotationOffsetsDegrees: Object.fromEntries(
      CORE27_JOINTS.map((joint) => [joint, [0, 0, 0]]),
    ),
    rootMotion: false,
    meshVisible: true,
    skeletonVisible: true,
  };
}

export function sanitizeCharacterProfile(value, {
  availableBones = null,
  modelId = undefined,
  modelName = undefined,
} = {}) {
  const fallback = defaultCharacterProfile({
    modelId: modelId ?? value?.modelId,
    modelName: modelName ?? value?.modelName,
    name: value?.name,
  });
  const boneNames = Array.isArray(availableBones)
    ? new Set(availableBones.map((name) => String(name)))
    : null;
  const boneMap = {};
  const rotationOffsetsDegrees = {};
  const assignedBoneIds = new Set();
  for (const joint of CORE27_JOINTS) {
    const candidate = value?.boneMap?.[joint];
    const accepted = typeof candidate === "string"
      && candidate.length > 0
      && candidate.length <= 2048
      && (!boneNames || boneNames.has(candidate))
      ? candidate
      : null;
    boneMap[joint] = accepted && !assignedBoneIds.has(accepted) ? accepted : null;
    if (boneMap[joint]) assignedBoneIds.add(boneMap[joint]);
    rotationOffsetsDegrees[joint] = [0, 1, 2].map((axis) => (
      bounded(value?.rotationOffsetsDegrees?.[joint]?.[axis], -180, 180, 0)
    ));
  }
  const transform = {
    scale: bounded(value?.transform?.scale, 0.001, 100, 1),
    yawDegrees: bounded(value?.transform?.yawDegrees, -180, 180, 0),
    pitchDegrees: bounded(value?.transform?.pitchDegrees, -180, 180, 0),
    rollDegrees: bounded(value?.transform?.rollDegrees, -180, 180, 0),
    offset: [0, 1, 2].map((axis) => (
      bounded(value?.transform?.offset?.[axis], -20, 20, 0)
    )),
  };
  return {
    kind: CHARACTER_PROFILE_KIND,
    version: CHARACTER_PROFILE_VERSION,
    name: cleanText(value?.name, fallback.name),
    modelId: cleanModelId(modelId ?? value?.modelId),
    modelName: cleanText(modelName ?? value?.modelName, fallback.modelName),
    skeletonId: cleanStableId(value?.skeletonId),
    boneMap,
    transform,
    rotationOffsetsDegrees,
    rootMotion: value?.rootMotion === true,
    meshVisible: value?.meshVisible !== false,
    skeletonVisible: value?.skeletonVisible !== false,
  };
}

export function characterProfileSummary(profileValue) {
  const profile = sanitizeCharacterProfile(profileValue);
  const mappedJoints = CORE27_JOINTS.filter((joint) => profile.boneMap[joint]);
  const required = [
    "Hips", "Spine", "Spine3", "Neck", "Head",
    "RightArm", "RightForeArm", "RightHand",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightUpLeg", "RightLeg", "RightFoot",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
  ];
  const missingRequired = required.filter((joint) => !profile.boneMap[joint]);
  return {
    mappedCount: mappedJoints.length,
    totalCount: CORE27_JOINTS.length,
    mappedJoints,
    missingRequired,
    ready: missingRequired.length === 0,
  };
}

export function parseCharacterProfile(text, options = {}) {
  if (typeof text !== "string" || text.length < 2 || text.length > 512 * 1024) {
    throw new Error("Character profile file is empty or too large.");
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error("Character profile is not valid JSON.");
  }
  if (
    payload?.version !== CHARACTER_PROFILE_VERSION
    || (payload?.kind !== undefined && payload.kind !== CHARACTER_PROFILE_KIND)
  ) {
    throw new Error(`Character profile version ${payload?.version ?? "unknown"} is not supported.`);
  }
  return sanitizeCharacterProfile(payload, options);
}

export function serializeCharacterProfile(profileValue) {
  return `${JSON.stringify(sanitizeCharacterProfile(profileValue), null, 2)}\n`;
}
