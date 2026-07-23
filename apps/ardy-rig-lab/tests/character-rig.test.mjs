import assert from "node:assert/strict";
import test from "node:test";

import * as THREE from "three";

import { CharacterRig } from "../src/characterRig.js";
import { analyzeImportedModel } from "../src/modelImporter.js";
import {
  CORE27_JOINTS,
  CORE27_PARENT_INDICES,
  createNeutralFrame,
  NEUTRAL_CORE27_POSITIONS,
} from "../src/poseProtocol.js";

function makeCharacter() {
  const root = new THREE.Group();
  root.name = "TestCharacter";
  const geometry = new THREE.BoxGeometry(0.3, 1.7, 0.2);
  const vertexCount = geometry.getAttribute("position").count;
  geometry.setAttribute(
    "skinIndex",
    new THREE.Uint16BufferAttribute(new Uint16Array(vertexCount * 4), 4),
  );
  const skinWeights = new Float32Array(vertexCount * 4);
  for (let index = 0; index < vertexCount; index += 1) skinWeights[index * 4] = 1;
  geometry.setAttribute("skinWeight", new THREE.Float32BufferAttribute(skinWeights, 4));
  const mesh = new THREE.SkinnedMesh(
    geometry,
    new THREE.MeshBasicMaterial(),
  );
  mesh.name = "Body";
  const bones = CORE27_JOINTS.map((name, index) => {
    const bone = new THREE.Bone();
    bone.name = name;
    const parentIndex = CORE27_PARENT_INDICES[index];
    const position = NEUTRAL_CORE27_POSITIONS[index];
    const parentPosition = parentIndex < 0
      ? [0, 0, 0]
      : NEUTRAL_CORE27_POSITIONS[parentIndex];
    bone.position.set(
      position[0] - parentPosition[0],
      position[1] - parentPosition[1],
      position[2] - parentPosition[2],
    );
    return bone;
  });
  bones.forEach((bone, index) => {
    const parentIndex = CORE27_PARENT_INDICES[index];
    if (parentIndex < 0) mesh.add(bone);
    else bones[parentIndex].add(bone);
  });

  const helperBone = new THREE.Bone();
  helperBone.name = "arm_twist_helper";
  helperBone.position.set(0.04, 0.02, 0);
  helperBone.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.13);
  bones[CORE27_JOINTS.indexOf("RightArm")].add(helperBone);

  mesh.bind(new THREE.Skeleton([...bones, helperBone]));
  root.add(mesh);
  const analysis = analyzeImportedModel(root, {
    format: "glb",
    sourceName: "test-character.glb",
  });
  const profile = {
    name: "Test character",
    modelName: "test-character.glb",
    boneMap: { ...analysis.autoMap.jointToBoneId },
    rotationOffsetsDegrees: {},
    transform: {},
    meshVisible: true,
    skeletonVisible: true,
  };
  return { analysis, profile, root, mesh, bones, helperBone };
}

function quaternionClose(actual, expected, tolerance = 1e-6) {
  const direct = actual.angleTo(expected);
  assert.ok(direct <= tolerance, `quaternions differ by ${direct} radians`);
}

test("retargets all mapped Core27 local quaternions from bind pose parent-first", () => {
  const { analysis, profile, bones, helperBone } = makeCharacter();
  profile.rotationOffsetsDegrees.RightForeArm = [0, 0, 15];
  const rig = new CharacterRig(analysis, profile);
  const frame = createNeutralFrame();
  const armIndex = CORE27_JOINTS.indexOf("RightArm");
  const forearmIndex = CORE27_JOINTS.indexOf("RightForeArm");
  const armMotion = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(0, 0, 1),
    Math.PI / 4,
  );
  const forearmMotion = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(1, 0, 0),
    Math.PI / 6,
  );
  frame.joints[armIndex] = armMotion.toArray();
  frame.joints[forearmIndex] = forearmMotion.toArray();

  // Deliberately corrupt both mapped and helper transforms. applyPose must
  // start clean and must never zero an unmapped helper's authored bind pose.
  bones[armIndex].quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), 2);
  helperBone.position.set(9, 9, 9);
  helperBone.quaternion.identity();
  rig.applyPose(frame);

  quaternionClose(bones[armIndex].quaternion, armMotion);
  const expectedForearm = forearmMotion.clone().multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, 15 * Math.PI / 180)),
  );
  quaternionClose(bones[forearmIndex].quaternion, expectedForearm);
  assert.deepEqual(helperBone.position.toArray(), [0.04, 0.02, 0]);
  quaternionClose(
    helperBone.quaternion,
    new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.13),
  );

  // The child world orientation proves the parent was evaluated before it.
  const expectedWorld = armMotion.clone().multiply(expectedForearm);
  const actualWorld = bones[forearmIndex].getWorldQuaternion(new THREE.Quaternion());
  quaternionClose(actualWorld, expectedWorld);
  assert.equal(rig.getStatus().mappedCount, CORE27_JOINTS.length);
  rig.dispose();
});

test("accepts stable IDs only and ignores duplicate or foreign bone mappings", () => {
  const { analysis, profile } = makeCharacter();
  profile.boneMap.Head = "Head";
  profile.boneMap.LeftHand = profile.boneMap.RightHand;
  const rig = new CharacterRig(analysis, profile);
  const status = rig.getStatus();

  assert.equal(status.mappedCount, CORE27_JOINTS.length - 2);
  assert.ok(status.missingJoints.includes("Head"));
  assert.ok(status.missingJoints.includes("LeftHand"));
  assert.equal(status.skeletonId, analysis.inventory.activeSkeleton.id);
  rig.dispose();
});

test("locks root travel by default and applies opt-in first-frame anchored deltas", () => {
  const { analysis, profile } = makeCharacter();
  const locked = new CharacterRig(analysis, profile);
  const movingFrame = createNeutralFrame();
  movingFrame.time = 4;
  movingFrame.root = [12, 3, -5, 0, Math.sin(Math.PI / 8), 0, Math.cos(Math.PI / 8)];
  locked.applyPose(movingFrame);
  assert.deepEqual(locked.rootMotionGroup.position.toArray(), [0, 0, 0]);
  quaternionClose(locked.rootMotionGroup.quaternion, new THREE.Quaternion());
  assert.equal(locked.getStatus().rootMotion, false);
  locked.dispose({ disposeModel: false });

  const movingProfile = { ...profile, rootMotion: true };
  const rig = new CharacterRig(analysis, movingProfile);
  const first = createNeutralFrame();
  first.time = 10;
  first.root = [2, 1, 3, 0, Math.sin(Math.PI / 8), 0, Math.cos(Math.PI / 8)];
  rig.applyPose(first);
  assert.deepEqual(rig.rootMotionGroup.position.toArray(), [0, 0, 0]);
  quaternionClose(rig.rootMotionGroup.quaternion, new THREE.Quaternion());

  const second = createNeutralFrame();
  second.time = 10.05;
  second.root = [3, 1.5, 5, 0, Math.sin(Math.PI / 4), 0, Math.cos(Math.PI / 4)];
  rig.applyPose(second);
  assert.deepEqual(rig.rootMotionGroup.position.toArray(), [1, 0.5, 2]);
  quaternionClose(
    rig.rootMotionGroup.quaternion,
    new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4),
  );

  // A looping stream starts a fresh anchor instead of jumping backward.
  const looped = createNeutralFrame();
  looped.time = 0;
  looped.root = [20, 8, 7, 0, 0, 0, 1];
  rig.applyPose(looped);
  assert.deepEqual(rig.rootMotionGroup.position.toArray(), [0, 0, 0]);
  quaternionClose(rig.rootMotionGroup.quaternion, new THREE.Quaternion());
  rig.dispose();
});

test("supports layered placement, visibility, selection, scale fitting, and disposal", () => {
  const { analysis, profile, mesh, root } = makeCharacter();
  profile.transform = {
    scale: 0.5,
    yawDegrees: 30,
    pitchDegrees: 10,
    rollDegrees: -5,
    offset: [1, 2, 3],
  };
  const rig = new CharacterRig(analysis, profile);
  assert.equal(rig.object3D, rig.container);
  assert.equal(rig.placementGroup.parent, rig.rootMotionGroup);
  assert.equal(rig.rootMotionGroup.parent, rig.container);
  assert.deepEqual(rig.placementGroup.position.toArray(), [1, 2, 3]);
  assert.deepEqual(rig.placementGroup.scale.toArray(), [0.5, 0.5, 0.5]);

  rig.setMeshVisible(false);
  assert.equal(mesh.visible, false);
  rig.setMeshVisible(true);
  assert.equal(mesh.visible, true);
  rig.setSelectedJoint("Head");
  rig.applyPose(createNeutralFrame());
  assert.equal(rig.selectionMarker.visible, true);
  assert.equal(rig.getStatus().selectedBoneId, profile.boneMap.Head);
  rig.setSkeletonVisible(false);
  assert.equal(rig.skeletonHelper.visible, false);
  assert.equal(rig.selectionMarker.visible, false);
  rig.setSkeletonVisible(true);

  const suggested = rig.suggestScale(1.72);
  assert.ok(Number.isFinite(suggested) && suggested > 0);
  const parent = new THREE.Group();
  parent.add(rig.container);
  const result = rig.dispose({ disposeModel: false });
  assert.equal(result, null);
  assert.equal(rig.container.parent, null);
  assert.equal(root.parent, null);
  assert.throws(() => rig.getStatus(), /disposed/);
});
