import assert from "node:assert/strict";
import test from "node:test";

import * as THREE from "three";

import { CORE27_JOINTS } from "../src/poseProtocol.js";
import {
  analyzeImportedModel,
  autoMapCore27Bones,
  disposeObject3D,
  inventorySkinnedModel,
  modelFormatForFile,
  normalizeBoneName,
} from "../src/modelImporter.js";

const unrealBoneNames = [
  "pelvis",
  "spine_01",
  "spine_02",
  "spine_03",
  "spine_04",
  "neck_01",
  "head",
  "clavicle_r",
  "upperarm_r",
  "lowerarm_r",
  "hand_r",
  "hand_end_r",
  "thumb_01_r",
  "clavicle_l",
  "upperarm_l",
  "lowerarm_l",
  "hand_l",
  "hand_end_l",
  "thumb_01_l",
  "thigh_r",
  "calf_r",
  "foot_r",
  "ball_r",
  "thigh_l",
  "calf_l",
  "foot_l",
  "ball_l",
];

function makeSkinnedModel(names = unrealBoneNames) {
  const root = new THREE.Group();
  root.name = "ImportedModel";
  const mesh = new THREE.SkinnedMesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial(),
  );
  mesh.name = "Body";
  const bones = names.map((name) => {
    const bone = new THREE.Bone();
    bone.name = name;
    return bone;
  });
  bones.forEach((bone, index) => {
    if (index === 0) mesh.add(bone);
    else bones[index - 1].add(bone);
  });
  mesh.bind(new THREE.Skeleton(bones));
  root.add(mesh);
  return { root, mesh, bones };
}

test("normalizes namespaces, rig prefixes, case, and separators", () => {
  assert.equal(normalizeBoneName("mixamorig:LeftForeArm"), "left_fore_arm");
  assert.equal(normalizeBoneName("Armature|DEF-upper_arm.R"), "upper_arm_r");
  assert.equal(normalizeBoneName("Bip001_RightHandThumb1"), "right_hand_thumb1");
  assert.equal(modelFormatForFile("person.GLB"), "glb");
  assert.equal(modelFormatForFile({ name: "person.gltf", type: "" }), "gltf");
  assert.equal(modelFormatForFile({ name: "person.vrm", type: "" }), "vrm");
  assert.equal(modelFormatForFile({ name: "person.unknown", type: "application/fbx" }), "fbx");
});

test("inventories unique SkinnedMesh skeleton bones and maps Unreal names to Core27", () => {
  const { root, bones } = makeSkinnedModel();
  const inventory = inventorySkinnedModel(root);
  assert.equal(inventory.rigged, true);
  assert.equal(inventory.skinnedMeshes.length, 1);
  assert.equal(inventory.skeletons.length, 1);
  assert.equal(inventory.bones.length, 27);

  const mapping = autoMapCore27Bones(inventory);
  assert.equal(mapping.mappedCount, CORE27_JOINTS.length);
  assert.equal(mapping.coverage, 1);
  assert.equal(mapping.jointToBone.Hips, bones[0]);
  assert.equal(mapping.jointToBone.RightArm.name, "upperarm_r");
  assert.equal(mapping.jointToBone.LeftToeBase.name, "ball_l");
  assert.deepEqual(mapping.unmappedJoints, []);

  const repeated = autoMapCore27Bones([...inventory.bones].reverse());
  assert.deepEqual(repeated.jointToBoneName, mapping.jointToBoneName);
});

test("keeps skeletons separate and exposes stable path IDs for rig profiles", () => {
  const root = new THREE.Group();
  root.name = "MultiRig";
  const face = makeSkinnedModel(["jaw", "eye_l", "eye_r"]);
  const body = makeSkinnedModel();
  root.add(face.root, body.root);

  const inventory = inventorySkinnedModel(root);
  assert.equal(inventory.skeletonGroups.length, 2);
  assert.equal(inventory.activeSkeleton.bones.length, 27);
  assert.equal(inventory.bones.length, 27);
  assert.equal(inventory.allBones.length, 30);
  assert.equal(inventory.activeSkeleton.autoMap.mappedCount, 27);
  assert.match(inventory.activeSkeleton.id, /ImportedModel\[1\]/);

  const leftHand = inventory.bones.find((record) => record.name === "hand_l");
  assert.match(leftHand.id, /skeleton:.*:bone:/);
  assert.equal(leftHand.skeletonId, inventory.activeSkeleton.id);
  assert.equal(leftHand.bindLocal.quaternion.length, 4);
  assert.equal(leftHand.bindWorldMatrix.length, 16);
  assert.equal(leftHand.inverseBindMatrix.length, 16);

  const mapping = autoMapCore27Bones(inventory);
  assert.equal(mapping.skeletonId, inventory.activeSkeleton.id);
  assert.equal(mapping.jointToBoneId.LeftHand, leftHand.id);
});

test("does not fabricate a skeleton for an unrigged mesh", () => {
  const root = new THREE.Group();
  root.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()));

  const inventory = inventorySkinnedModel(root);
  assert.equal(inventory.rigged, false);
  assert.equal(inventory.diagnostic.code, "unrigged-model");
  assert.match(inventory.diagnostic.message, /will not invent skin weights/i);

  const analysis = analyzeImportedModel(root, { format: "glb", sourceName: "prop.glb" });
  assert.equal(analysis.ok, false);
  assert.equal(analysis.autoMap, null);
  assert.equal(analysis.diagnostic.code, "unrigged-model");
});

test("safe disposal releases shared GPU resources once and detaches the model", () => {
  const parent = new THREE.Group();
  const root = new THREE.Group();
  parent.add(root);

  const geometry = new THREE.BoxGeometry();
  const texture = new THREE.Texture();
  const material = new THREE.MeshStandardMaterial({ map: texture });
  root.add(new THREE.Mesh(geometry, material));
  root.add(new THREE.Mesh(geometry, material));

  let geometryDisposals = 0;
  let materialDisposals = 0;
  let textureDisposals = 0;
  geometry.dispose = () => { geometryDisposals += 1; };
  material.dispose = () => { materialDisposals += 1; };
  texture.dispose = () => { textureDisposals += 1; };

  const counts = disposeObject3D(root);
  assert.deepEqual(counts, {
    geometries: 1,
    materials: 1,
    textures: 1,
    skeletons: 0,
  });
  assert.equal(geometryDisposals, 1);
  assert.equal(materialDisposals, 1);
  assert.equal(textureDisposals, 1);
  assert.equal(root.parent, null);
});
