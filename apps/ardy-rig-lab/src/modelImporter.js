import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { CORE27_JOINTS } from "./poseProtocol.js";

export const SUPPORTED_MODEL_EXTENSIONS = Object.freeze(["glb", "gltf", "vrm", "fbx"]);

const CORE27_ALIASES = Object.freeze({
  Hips: ["hips", "hip", "pelvis", "root_hips", "root_pelvis"],
  Spine: ["spine", "spine_01", "spine01", "lower_spine"],
  Spine1: ["spine1", "spine_02", "spine02", "mid_spine"],
  Spine2: ["spine2", "spine_03", "spine03", "upper_spine"],
  Spine3: ["spine3", "spine_04", "spine04", "chest", "upper_chest"],
  Neck: ["neck", "neck_01", "neck01"],
  Head: ["head", "head_01", "head01"],
  RightShoulder: [
    "right_shoulder", "shoulder_r", "r_shoulder", "clavicle_r", "r_clavicle",
  ],
  RightArm: [
    "right_arm", "right_upper_arm", "right_upperarm", "upperarm_r", "upper_arm_r",
    "r_upperarm", "r_upper_arm",
  ],
  RightForeArm: [
    "right_forearm", "right_fore_arm", "right_lower_arm", "lowerarm_r", "lower_arm_r",
    "forearm_r", "r_forearm", "r_lowerarm",
  ],
  RightHand: ["right_hand", "hand_r", "r_hand", "right_wrist", "wrist_r"],
  RightHandEnd: [
    "right_hand_end", "hand_end_r", "r_hand_end", "right_wrist_end", "wrist_end_r",
  ],
  RightHandThumb1: [
    "right_hand_thumb1", "right_thumb1", "thumb1_r", "thumb_01_r", "r_thumb1",
  ],
  LeftShoulder: [
    "left_shoulder", "shoulder_l", "l_shoulder", "clavicle_l", "l_clavicle",
  ],
  LeftArm: [
    "left_arm", "left_upper_arm", "left_upperarm", "upperarm_l", "upper_arm_l",
    "l_upperarm", "l_upper_arm",
  ],
  LeftForeArm: [
    "left_forearm", "left_fore_arm", "left_lower_arm", "lowerarm_l", "lower_arm_l",
    "forearm_l", "l_forearm", "l_lowerarm",
  ],
  LeftHand: ["left_hand", "hand_l", "l_hand", "left_wrist", "wrist_l"],
  LeftHandEnd: [
    "left_hand_end", "hand_end_l", "l_hand_end", "left_wrist_end", "wrist_end_l",
  ],
  LeftHandThumb1: [
    "left_hand_thumb1", "left_thumb1", "thumb1_l", "thumb_01_l", "l_thumb1",
  ],
  RightUpLeg: [
    "right_up_leg", "right_upleg", "right_thigh", "thigh_r", "upperleg_r",
    "upper_leg_r", "r_thigh", "r_upleg",
  ],
  RightLeg: [
    "right_leg", "right_lower_leg", "right_calf", "calf_r", "lowerleg_r",
    "lower_leg_r", "r_calf", "r_leg",
  ],
  RightFoot: ["right_foot", "foot_r", "r_foot", "right_ankle", "ankle_r"],
  RightToeBase: [
    "right_toe_base", "right_toebase", "right_toe", "toe_r", "toebase_r",
    "toe_base_r", "ball_r", "r_ball",
  ],
  LeftUpLeg: [
    "left_up_leg", "left_upleg", "left_thigh", "thigh_l", "upperleg_l",
    "upper_leg_l", "l_thigh", "l_upleg",
  ],
  LeftLeg: [
    "left_leg", "left_lower_leg", "left_calf", "calf_l", "lowerleg_l",
    "lower_leg_l", "l_calf", "l_leg",
  ],
  LeftFoot: ["left_foot", "foot_l", "l_foot", "left_ankle", "ankle_l"],
  LeftToeBase: [
    "left_toe_base", "left_toebase", "left_toe", "toe_l", "toebase_l",
    "toe_base_l", "ball_l", "l_ball",
  ],
});

const RIG_PREFIX = /^(?:(?:mixamo(?:rig)?|armature|skeleton|rig|deform|def|jnt|joint|bone|bip0*\d*)(?:_+|$))+/;

function diagnostic(code, message, severity = "error") {
  return Object.freeze({ code, message, severity });
}

function objectPath(object) {
  const parts = [];
  let current = object;
  while (current) {
    const label = current.name || current.type || "Object3D";
    const peers = current.parent?.children?.filter(
      (child) => (child.name || child.type || "Object3D") === label,
    ) || [];
    const ordinal = peers.length > 1 ? peers.indexOf(current) : -1;
    parts.push(ordinal >= 0 ? `${label}[${ordinal}]` : label);
    current = current.parent;
  }
  return parts.reverse().join("/");
}

function normalizedPath(value) {
  return decodeURIComponent(String(value || "").split(/[?#]/, 1)[0])
    .replaceAll("\\", "/")
    .replace(/^\.\/+/, "")
    .toLowerCase();
}

function disposeTexture(value, textures, counts) {
  if (!value?.isTexture || textures.has(value)) return;
  textures.add(value);
  value.dispose();
  counts.textures += 1;
}

function disposeMaterial(material, materials, textures, counts) {
  if (!material || materials.has(material)) return;
  materials.add(material);

  for (const value of Object.values(material)) {
    if (Array.isArray(value)) {
      for (const item of value) disposeTexture(item, textures, counts);
    } else {
      disposeTexture(value, textures, counts);
    }
  }
  for (const uniform of Object.values(material.uniforms || {})) {
    const value = uniform?.value;
    if (Array.isArray(value)) {
      for (const item of value) disposeTexture(item, textures, counts);
    } else {
      disposeTexture(value, textures, counts);
    }
  }

  material.dispose();
  counts.materials += 1;
}

function asBoneRecord(entry, index) {
  const bone = entry?.bone?.isBone ? entry.bone : entry;
  if (!bone?.isBone) return null;
  return {
    bone,
    index,
    id: String(entry?.id ?? objectPath(bone)),
    skeletonId: entry?.skeletonId ?? null,
    name: String(entry?.name ?? bone.name ?? ""),
    normalizedName: normalizeBoneName(entry?.normalizedName ?? entry?.name ?? bone.name),
    path: String(entry?.path ?? objectPath(bone)),
  };
}

function candidateScore(normalizedBoneName, alias, aliasIndex) {
  if (!normalizedBoneName || !alias) return 0;
  if (normalizedBoneName === alias) return 10000 - aliasIndex;

  const compactName = normalizedBoneName.replaceAll("_", "");
  const compactAlias = alias.replaceAll("_", "");
  if (compactName === compactAlias) return 9000 - aliasIndex;
  if (normalizedBoneName.endsWith(`_${alias}`)) return 8000 - aliasIndex;
  if (compactName.endsWith(compactAlias)) return 7000 - aliasIndex;
  return 0;
}

function importFailure(code, message, error = null) {
  return {
    ok: false,
    rigged: false,
    format: null,
    sourceName: "",
    root: null,
    animations: [],
    inventory: null,
    autoMap: null,
    diagnostic: diagnostic(code, message),
    error,
  };
}

function modelName(file) {
  return String(file?.webkitRelativePath || file?.name || "");
}

export function normalizeBoneName(value) {
  const leaf = String(value ?? "")
    .trim()
    .split(/[|/:]/)
    .filter(Boolean)
    .at(-1) || "";
  return leaf
    .replace(/([a-z\d])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[^a-z\d]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(RIG_PREFIX, "")
    .replace(/^_+|_+$/g, "");
}

export function modelFormatForFile(fileOrName) {
  const name = typeof fileOrName === "string" ? fileOrName : modelName(fileOrName);
  const extension = name.toLowerCase().match(/\.([a-z\d]+)$/)?.[1] || "";
  if (SUPPORTED_MODEL_EXTENSIONS.includes(extension)) return extension;

  const mime = String(fileOrName?.type || "").toLowerCase();
  if (mime.includes("gltf-binary")) return "glb";
  if (mime.includes("gltf+json") || mime.endsWith("/gltf")) return "gltf";
  if (mime.includes("fbx")) return "fbx";
  return null;
}

export function inventorySkinnedModel(root) {
  const meshes = [];
  const skinnedMeshes = [];
  const skeletons = [];
  const skeletonSet = new Set();
  const groupBySkeleton = new Map();

  if (!root?.isObject3D || typeof root.traverse !== "function") {
    return {
      rigged: false,
      meshes,
      skinnedMeshes,
      skeletons,
      skeletonGroups: [],
      activeSkeleton: null,
      bones: [],
      allBones: [],
      diagnostic: diagnostic(
        "invalid-model-root",
        "The imported file did not contain a valid Three.js Object3D scene.",
      ),
    };
  }

  root.traverse((object) => {
    if (object.isMesh) {
      meshes.push({
        object,
        name: object.name || (object.isSkinnedMesh ? "SkinnedMesh" : "Mesh"),
        path: objectPath(object),
        skinned: Boolean(object.isSkinnedMesh && object.skeleton),
        visible: object.visible,
      });
    }
    if (!object.isSkinnedMesh || !object.skeleton) return;
    const skeleton = object.skeleton;
    const bones = Array.isArray(skeleton.bones) ? skeleton.bones.filter((bone) => bone?.isBone) : [];
    const meshRecord = {
      object,
      name: object.name || "SkinnedMesh",
      path: objectPath(object),
      skeleton,
      boneCount: bones.length,
    };
    skinnedMeshes.push(meshRecord);
    if (!skeletonSet.has(skeleton)) {
      skeletonSet.add(skeleton);
      skeletons.push(skeleton);
      groupBySkeleton.set(skeleton, {
        id: `skeleton:${skeletons.length - 1}:${meshRecord.path}`,
        index: skeletons.length - 1,
        skeleton,
        skinnedMeshes: [],
        bones: [],
      });
    }
    groupBySkeleton.get(skeleton).skinnedMeshes.push(meshRecord);
  });

  root.updateMatrixWorld(true);
  const skeletonGroups = [...groupBySkeleton.values()].map((group) => {
    const uniqueBones = [...new Set(group.skeleton.bones.filter((bone) => bone?.isBone))];
    group.bones = uniqueBones.map((bone, index) => {
      const path = objectPath(bone);
      return {
        bone,
        index,
        id: `${group.id}:bone:${path}`,
        skeletonId: group.id,
        name: bone.name || `Bone ${index + 1}`,
        normalizedName: normalizeBoneName(bone.name),
        path,
        skinnedMeshNames: Object.freeze(group.skinnedMeshes.map((mesh) => mesh.name)),
        bindLocal: Object.freeze({
          position: Object.freeze(bone.position.toArray()),
          quaternion: Object.freeze(bone.quaternion.toArray()),
          scale: Object.freeze(bone.scale.toArray()),
        }),
        bindWorldMatrix: Object.freeze(bone.matrixWorld.toArray()),
        inverseBindMatrix: Object.freeze(
          group.skeleton.boneInverses[index]?.toArray() || new THREE.Matrix4().toArray(),
        ),
      };
    });
    group.autoMap = autoMapCore27Bones(group.bones);
    return group;
  });
  skeletonGroups.sort((left, right) => (
    right.autoMap.mappedCount - left.autoMap.mappedCount
    || left.bones.length - right.bones.length
    || left.id.localeCompare(right.id)
  ));
  const activeSkeleton = skeletonGroups[0] || null;
  const bones = activeSkeleton?.bones || [];
  const allBones = skeletonGroups.flatMap((group) => group.bones);

  if (skinnedMeshes.length === 0) {
    return {
      rigged: false,
      meshes,
      skinnedMeshes,
      skeletons,
      skeletonGroups,
      activeSkeleton,
      bones,
      allBones,
      diagnostic: diagnostic(
        "unrigged-model",
        "No SkinnedMesh with a bound Skeleton was found. The model can be viewed as a static mesh, but Rig Lab will not invent skin weights or pretend that it is rigged.",
      ),
    };
  }
  if (bones.length === 0) {
    return {
      rigged: false,
      meshes,
      skinnedMeshes,
      skeletons,
      skeletonGroups,
      activeSkeleton,
      bones,
      allBones,
      diagnostic: diagnostic(
        "empty-skeleton",
        "A SkinnedMesh was found, but its Skeleton contains no usable bones.",
      ),
    };
  }

  return {
    rigged: true,
    meshes,
    skinnedMeshes,
    skeletons,
    skeletonGroups,
    activeSkeleton,
    bones,
    allBones,
    diagnostic: diagnostic(
      "rig-found",
      `Found ${skinnedMeshes.length} skinned mesh${skinnedMeshes.length === 1 ? "" : "es"} across ${skeletonGroups.length} skeleton${skeletonGroups.length === 1 ? "" : "s"}; selected ${activeSkeleton.id} with ${bones.length} body-rig candidates.`,
      "info",
    ),
  };
}

export function autoMapCore27Bones(source) {
  const sourceBones = Array.isArray(source)
    ? source
    : source?.activeSkeleton?.bones || source?.bones;
  const skeletonId = Array.isArray(source)
    ? sourceBones?.find((entry) => entry?.skeletonId)?.skeletonId || null
    : source?.activeSkeleton?.id || sourceBones?.find((entry) => entry?.skeletonId)?.skeletonId || null;
  const records = (Array.isArray(sourceBones) ? sourceBones : [])
    .map(asBoneRecord)
    .filter(Boolean)
    .sort((left, right) => (
      left.normalizedName.localeCompare(right.normalizedName)
      || left.path.localeCompare(right.path)
      || left.name.localeCompare(right.name)
      || left.index - right.index
    ));

  const edges = [];
  CORE27_JOINTS.forEach((joint, jointIndex) => {
    const aliases = [...new Set(
      [joint, ...(CORE27_ALIASES[joint] || [])]
        .map(normalizeBoneName)
        .filter(Boolean),
    )];
    records.forEach((record, boneIndex) => {
      let bestScore = 0;
      let bestAlias = "";
      aliases.forEach((alias, aliasIndex) => {
        const score = candidateScore(record.normalizedName, alias, aliasIndex);
        if (score > bestScore) {
          bestScore = score;
          bestAlias = alias;
        }
      });
      if (bestScore > 0) {
        edges.push({ joint, jointIndex, record, boneIndex, score: bestScore, alias: bestAlias });
      }
    });
  });
  edges.sort((left, right) => (
    right.score - left.score
    || left.jointIndex - right.jointIndex
    || left.boneIndex - right.boneIndex
  ));

  const assignedJoints = new Set();
  const assignedBones = new Set();
  const matchByJoint = new Map();
  for (const edge of edges) {
    if (assignedJoints.has(edge.joint) || assignedBones.has(edge.record.bone)) continue;
    assignedJoints.add(edge.joint);
    assignedBones.add(edge.record.bone);
    matchByJoint.set(edge.joint, edge);
  }

  const jointToBone = {};
  const jointToBoneId = {};
  const jointToBoneName = {};
  const matches = CORE27_JOINTS.map((joint) => {
    const edge = matchByJoint.get(joint);
    const bone = edge?.record.bone || null;
    jointToBone[joint] = bone;
    jointToBoneId[joint] = edge?.record.id || null;
    jointToBoneName[joint] = bone?.name || null;
    return {
      joint,
      bone,
      boneId: edge?.record.id || null,
      boneName: bone?.name || null,
      bonePath: edge?.record.path || null,
      normalizedBoneName: edge?.record.normalizedName || null,
      score: edge?.score || 0,
      matchedAlias: edge?.alias || null,
    };
  });
  const unmappedJoints = matches.filter((match) => !match.bone).map((match) => match.joint);
  const mappedCount = CORE27_JOINTS.length - unmappedJoints.length;
  const mapDiagnostic = mappedCount === 0
    ? diagnostic(
      "no-core27-matches",
      "A skeleton exists, but none of its bone names can be mapped safely to Core27. Adjust the rig names or provide manual mappings.",
    )
    : unmappedJoints.length > 0
      ? diagnostic(
        "partial-core27-map",
        `Mapped ${mappedCount} of ${CORE27_JOINTS.length} Core27 joints. Review the ${unmappedJoints.length} unmatched joints before driving the character.`,
        "warning",
      )
      : diagnostic(
        "complete-core27-map",
        `Mapped all ${CORE27_JOINTS.length} Core27 joints.`,
        "info",
      );

  return {
    skeletonId,
    jointToBone,
    jointToBoneId,
    jointToBoneName,
    matches,
    mappedCount,
    coverage: mappedCount / CORE27_JOINTS.length,
    unmappedJoints,
    diagnostic: mapDiagnostic,
  };
}

export function analyzeImportedModel(
  root,
  { animations = [], format = null, sourceName = "" } = {},
) {
  const inventory = inventorySkinnedModel(root);
  const autoMap = inventory.rigged ? autoMapCore27Bones(inventory) : null;
  const usableMap = autoMap && autoMap.mappedCount > 0;
  return {
    ok: Boolean(inventory.rigged && usableMap),
    rigged: inventory.rigged,
    format,
    sourceName,
    root,
    animations: Array.isArray(animations) ? animations : [],
    inventory,
    autoMap,
    diagnostic: inventory.rigged ? autoMap.diagnostic : inventory.diagnostic,
    error: null,
  };
}

export function selectImportedSkeleton(analysis, skeletonId) {
  const group = analysis?.inventory?.skeletonGroups?.find((entry) => entry.id === skeletonId);
  if (!group) throw new Error("The selected skeleton is not part of this imported model.");
  const inventory = {
    ...analysis.inventory,
    activeSkeleton: group,
    bones: group.bones,
  };
  const autoMap = autoMapCore27Bones(group.bones);
  return {
    ...analysis,
    ok: autoMap.mappedCount > 0,
    rigged: true,
    inventory,
    autoMap,
    diagnostic: autoMap.diagnostic,
  };
}

export function disposeObject3D(root, { detach = true } = {}) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const skeletons = new Set();
  const counts = { geometries: 0, materials: 0, textures: 0, skeletons: 0 };

  if (!root?.isObject3D || typeof root.traverse !== "function") return counts;
  root.traverse((object) => {
    const geometry = object.geometry;
    if (geometry?.dispose && !geometries.has(geometry)) {
      geometries.add(geometry);
      geometry.dispose();
      counts.geometries += 1;
    }

    const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
    for (const objectMaterial of objectMaterials) {
      disposeMaterial(objectMaterial, materials, textures, counts);
    }

    const skeleton = object.skeleton;
    if (skeleton?.dispose && !skeletons.has(skeleton)) {
      skeletons.add(skeleton);
      skeleton.dispose();
      counts.skeletons += 1;
    }
  });
  if (detach) root.removeFromParent();
  return counts;
}

export async function importModelFiles(fileList, options = {}) {
  const files = [...(fileList || [])].filter(Boolean);
  if (files.length === 0) {
    return importFailure("no-model-file", "Choose a GLB, GLTF, VRM, or FBX model file.");
  }

  const entryName = String(options.entryFileName || "");
  const candidates = files.filter((file) => modelFormatForFile(file));
  const primary = entryName
    ? candidates.find((file) => modelName(file) === entryName || file.name === entryName)
    : candidates.length === 1 ? candidates[0] : null;
  if (!primary) {
    return importFailure(
      candidates.length === 0 ? "unsupported-model-format" : "ambiguous-model-entry",
      candidates.length === 0
        ? "No supported GLB, GLTF, VRM, or FBX entry file was found."
        : "More than one model entry was selected. Pass entryFileName to choose the GLB, GLTF, VRM, or FBX to import.",
    );
  }

  const format = modelFormatForFile(primary);
  const createObjectURL = options.createObjectURL || globalThis.URL?.createObjectURL?.bind(globalThis.URL);
  const revokeObjectURL = options.revokeObjectURL || globalThis.URL?.revokeObjectURL?.bind(globalThis.URL);
  if (!createObjectURL || !revokeObjectURL) {
    return importFailure(
      "browser-file-api-unavailable",
      "This browser does not provide the object-URL APIs required for local model import.",
    );
  }

  const objectUrls = new Map();
  const lookup = new Map();
  const assets = [];
  try {
    for (const file of files) {
      const url = createObjectURL(file);
      objectUrls.set(file, url);
      const names = [file.name, file.webkitRelativePath].filter(Boolean).map(normalizedPath);
      for (const name of names) {
        lookup.set(name, url);
        assets.push({ path: name, basename: name.split("/").at(-1), url });
      }
    }
    const basenameCounts = new Map();
    for (const asset of assets) {
      basenameCounts.set(asset.basename, (basenameCounts.get(asset.basename) || 0) + 1);
    }

    const manager = new THREE.LoadingManager();
    manager.setURLModifier((requestedUrl) => {
      const requested = normalizedPath(requestedUrl);
      const suffixMatches = assets.filter((asset) => (
        requested.endsWith(`/${asset.path}`)
        || requested === asset.path
      ));
      if (suffixMatches.length === 1) return suffixMatches[0].url;
      const basename = requested.split("/").at(-1);
      return lookup.get(requested)
        || (basenameCounts.get(basename) === 1
          ? assets.find((asset) => asset.basename === basename)?.url
          : null)
        || requestedUrl;
    });

    let root;
    let animations = [];
    if (format === "fbx") {
      const payload = await new FBXLoader(manager).loadAsync(objectUrls.get(primary));
      root = payload;
      animations = payload.animations || [];
    } else {
      const payload = await new GLTFLoader(manager).loadAsync(objectUrls.get(primary));
      root = payload.scene || payload.scenes?.[0] || null;
      animations = payload.animations || [];
    }
    return analyzeImportedModel(root, {
      animations,
      format,
      sourceName: modelName(primary),
    });
  } catch (error) {
    return importFailure(
      "model-import-failed",
      `The ${format?.toUpperCase() || "model"} file could not be loaded: ${error?.message || "unknown loader error"}`,
      error,
    );
  } finally {
    for (const url of objectUrls.values()) revokeObjectURL(url);
  }
}

export async function importModelFile(file, options = {}) {
  return importModelFiles(file ? [file] : [], options);
}
