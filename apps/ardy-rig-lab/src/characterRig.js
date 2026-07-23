import * as THREE from "three";

import { sanitizeCharacterProfile } from "./characterProfile.js";
import { disposeObject3D } from "./modelImporter.js";
import {
  CORE27_JOINTS,
  CORE27_PARENT_INDICES,
} from "./poseProtocol.js";

const DEGREES_TO_RADIANS = Math.PI / 180;
const ROOT_TIME_EPSILON = 1e-6;

function finiteVector(value, length) {
  return Array.isArray(value)
    && value.length === length
    && value.every((entry) => Number.isFinite(Number(entry)));
}

function cloneProfile(profile) {
  return JSON.parse(JSON.stringify(profile));
}

function bindTransformFor(record) {
  const fallback = record.bone;
  const bind = record.bindLocal || {};
  return {
    position: finiteVector(bind.position, 3)
      ? new THREE.Vector3().fromArray(bind.position)
      : fallback.position.clone(),
    quaternion: finiteVector(bind.quaternion, 4)
      ? new THREE.Quaternion().fromArray(bind.quaternion).normalize()
      : fallback.quaternion.clone(),
    scale: finiteVector(bind.scale, 3)
      ? new THREE.Vector3().fromArray(bind.scale)
      : fallback.scale.clone(),
  };
}

function normalizedQuaternion(values, target) {
  target.fromArray(values);
  if (target.lengthSq() < Number.EPSILON) target.identity();
  return target.normalize();
}

function validPoseFrame(frame) {
  return frame
    && finiteVector(frame.root, 7)
    && Array.isArray(frame.joints)
    && frame.joints.length === CORE27_JOINTS.length
    && frame.joints.every((quaternion) => finiteVector(quaternion, 4));
}

/**
 * Owns one imported skinned character and retargets ARDY Core27 local
 * quaternion frames onto its reviewed skeleton mapping.
 *
 * Transform layers intentionally remain separate:
 *
 *     container
 *       rootMotionGroup     ARDY's optional anchored travel (world meters)
 *         placementGroup    user calibration, orientation, and model units
 *           imported model
 *
 * This prevents a centimeter-to-meter model scale from shrinking root travel.
 */
export class CharacterRig {
  constructor(analysis, profile = {}) {
    const activeSkeleton = analysis?.inventory?.activeSkeleton;
    if (!analysis?.root?.isObject3D) {
      throw new Error("CharacterRig requires an imported Three.js model root.");
    }
    if (!analysis?.inventory?.rigged || !activeSkeleton?.bones?.length) {
      throw new Error("CharacterRig requires a SkinnedMesh with a usable skeleton.");
    }

    this.analysis = analysis;
    this.modelRoot = analysis.root;
    this.activeSkeleton = activeSkeleton;
    this.boneRecords = [...activeSkeleton.bones];
    this.boneById = new Map(this.boneRecords.map((record) => [record.id, record]));
    this.bindPose = new Map(
      this.boneRecords.map((record) => [record.bone, bindTransformFor(record)]),
    );
    this.originalMeshVisibility = new Map();
    this.modelRoot.traverse((object) => {
      if (object.isMesh || object.isPoints || object.isLine) {
        this.originalMeshVisibility.set(object, object.visible);
      }
    });

    this.container = new THREE.Group();
    this.container.name = "imported-character";
    this.object3D = this.container;
    this.rootMotionGroup = new THREE.Group();
    this.rootMotionGroup.name = "character-root-motion";
    this.placementGroup = new THREE.Group();
    this.placementGroup.name = "character-placement";
    this.container.add(this.rootMotionGroup);
    this.rootMotionGroup.add(this.placementGroup);
    this.placementGroup.add(this.modelRoot);

    this.skeletonHelper = new THREE.SkeletonHelper(this.modelRoot);
    this.skeletonHelper.name = "imported-character-skeleton";
    this.skeletonHelper.renderOrder = 1000;
    this.skeletonHelper.material.opacity = 0.84;
    this.skeletonHelper.material.transparent = true;
    this.skeletonHelper.material.depthTest = false;
    this.skeletonHelper.setColors(
      new THREE.Color(0x55e6bd),
      new THREE.Color(0xa99cff),
    );
    // SkeletonHelper normally belongs directly to the Scene and references the
    // root's world matrix. Here it is the model's sibling, so the root's local
    // matrix produces the same final transform without applying our groups twice.
    this.skeletonHelper.matrix = this.modelRoot.matrix;
    this.placementGroup.add(this.skeletonHelper);

    this.selectionMarker = new THREE.Mesh(
      new THREE.SphereGeometry(0.045, 18, 12),
      new THREE.MeshBasicMaterial({
        color: 0xffcf78,
        depthTest: false,
        depthWrite: false,
        transparent: true,
        opacity: 0.95,
      }),
    );
    this.selectionMarker.name = "selected-character-bone";
    this.selectionMarker.renderOrder = 1001;
    this.selectionMarker.visible = false;
    this.rootMotionGroup.add(this.selectionMarker);

    this.profile = null;
    this.mapping = [];
    this.mappingByJoint = new Map();
    this.selectedJoint = null;
    this.rootAnchorPosition = null;
    this.rootAnchorQuaternion = null;
    this.lastPoseTime = null;
    this.disposed = false;
    this._sourceQuaternion = new THREE.Quaternion();
    this._offsetQuaternion = new THREE.Quaternion();
    this._resultQuaternion = new THREE.Quaternion();
    this._anchorQuaternionInverse = new THREE.Quaternion();
    this._rootPosition = new THREE.Vector3();
    this._rootQuaternion = new THREE.Quaternion();
    this._markerWorldPosition = new THREE.Vector3();

    this.setProfile(profile);
    this.resetPose();
  }

  _assertActive() {
    if (this.disposed) throw new Error("CharacterRig has already been disposed.");
  }

  _resolveMapping() {
    const claimedBoneIds = new Set();
    this.mapping = [];
    this.mappingByJoint.clear();

    CORE27_JOINTS.forEach((joint, jointIndex) => {
      const boneId = this.profile.boneMap[joint];
      const record = boneId ? this.boneById.get(boneId) : null;
      if (!record || claimedBoneIds.has(record.id)) return;
      claimedBoneIds.add(record.id);
      const offset = this.profile.rotationOffsetsDegrees[joint];
      const entry = {
        joint,
        jointIndex,
        parentIndex: CORE27_PARENT_INDICES[jointIndex],
        boneId: record.id,
        record,
        bind: this.bindPose.get(record.bone),
        offsetQuaternion: new THREE.Quaternion().setFromEuler(new THREE.Euler(
          offset[0] * DEGREES_TO_RADIANS,
          offset[1] * DEGREES_TO_RADIANS,
          offset[2] * DEGREES_TO_RADIANS,
          "XYZ",
        )),
      };
      this.mapping.push(entry);
      this.mappingByJoint.set(joint, entry);
    });

    // CORE27_JOINTS is parent-first by contract. Keep the sort explicit so a
    // future skeleton-order change cannot silently break retarget evaluation.
    this.mapping.sort((left, right) => left.jointIndex - right.jointIndex);
  }

  _applyPlacementTransform() {
    const { transform } = this.profile;
    this.placementGroup.position.fromArray(transform.offset);
    this.placementGroup.rotation.set(
      transform.pitchDegrees * DEGREES_TO_RADIANS,
      transform.yawDegrees * DEGREES_TO_RADIANS,
      transform.rollDegrees * DEGREES_TO_RADIANS,
      "YXZ",
    );
    this.placementGroup.scale.setScalar(transform.scale);
    this.placementGroup.updateMatrix();
  }

  _restoreBindPose() {
    for (const record of this.boneRecords) {
      const bind = this.bindPose.get(record.bone);
      record.bone.position.copy(bind.position);
      record.bone.quaternion.copy(bind.quaternion);
      record.bone.scale.copy(bind.scale);
      record.bone.updateMatrix();
    }
  }

  _applyRootMotion(frame) {
    const poseTime = Number(frame.time);
    if (
      this.lastPoseTime !== null
      && Number.isFinite(poseTime)
      && poseTime + ROOT_TIME_EPSILON < this.lastPoseTime
    ) {
      this.resetRootAnchor();
    }
    if (Number.isFinite(poseTime)) this.lastPoseTime = poseTime;

    if (!this.profile.rootMotion) {
      this.rootMotionGroup.position.set(0, 0, 0);
      this.rootMotionGroup.quaternion.identity();
      this.rootMotionGroup.updateMatrix();
      return;
    }

    this._rootPosition.fromArray(frame.root, 0);
    normalizedQuaternion(frame.root.slice(3, 7), this._rootQuaternion);
    if (!this.rootAnchorPosition || !this.rootAnchorQuaternion) {
      this.rootAnchorPosition = this._rootPosition.clone();
      this.rootAnchorQuaternion = this._rootQuaternion.clone();
    }

    this.rootMotionGroup.position.copy(this._rootPosition).sub(this.rootAnchorPosition);
    this._anchorQuaternionInverse.copy(this.rootAnchorQuaternion).invert();
    this.rootMotionGroup.quaternion
      .copy(this._rootQuaternion)
      .multiply(this._anchorQuaternionInverse)
      .normalize();
    this.rootMotionGroup.updateMatrix();
  }

  _updateSelectionMarker() {
    const entry = this.selectedJoint ? this.mappingByJoint.get(this.selectedJoint) : null;
    if (!entry || !this.profile.skeletonVisible) {
      this.selectionMarker.visible = false;
      return;
    }
    this.container.updateMatrixWorld(true);
    entry.record.bone.getWorldPosition(this._markerWorldPosition);
    this.rootMotionGroup.worldToLocal(this._markerWorldPosition);
    this.selectionMarker.position.copy(this._markerWorldPosition);
    this.selectionMarker.visible = true;
  }

  setProfile(profileValue = {}) {
    this._assertActive();
    // Root travel is deliberately opt-in even while older saved-profile
    // sanitizers default it on. An absent property must always mean locked.
    const rootMotion = profileValue?.rootMotion === true;
    this.profile = sanitizeCharacterProfile(
      { ...profileValue, rootMotion },
      {
        availableBones: this.boneRecords.map((record) => record.id),
        modelId: profileValue?.modelId,
        modelName: profileValue?.modelName || this.analysis.sourceName,
      },
    );
    this.profile.rootMotion = rootMotion;
    this._resolveMapping();
    this._applyPlacementTransform();
    this.setMeshVisible(this.profile.meshVisible);
    this.setSkeletonVisible(this.profile.skeletonVisible);
    this.resetRootAnchor();
    this._updateSelectionMarker();
    return this.getStatus();
  }

  getProfile() {
    this._assertActive();
    return cloneProfile(this.profile);
  }

  /**
   * Applies a complete ARDY frame. Every active-skeleton bone is first restored
   * to its captured local bind transform. Only mapped bones are then modified,
   * leaving unmapped twist/helper bones at bind while still inheriting motion.
   */
  applyPose(frame) {
    this._assertActive();
    if (!validPoseFrame(frame)) {
      throw new Error("CharacterRig requires one complete 27-joint ARDY pose frame.");
    }

    this._restoreBindPose();
    this._applyRootMotion(frame);
    this.container.updateMatrixWorld(true);

    for (const entry of this.mapping) {
      normalizedQuaternion(frame.joints[entry.jointIndex], this._sourceQuaternion);
      this._offsetQuaternion.copy(entry.offsetQuaternion);
      this._resultQuaternion
        .copy(entry.bind.quaternion)
        .multiply(this._sourceQuaternion)
        .multiply(this._offsetQuaternion)
        .normalize();
      entry.record.bone.quaternion.copy(this._resultQuaternion);
      entry.record.bone.updateMatrix();
      // Update each mapped joint parent-first. Unmapped helper bones keep their
      // bind local transform and naturally inherit their mapped ancestor.
      entry.record.bone.updateWorldMatrix(true, false);
    }

    this.modelRoot.updateMatrixWorld(true);
    this.skeletonHelper.updateMatrixWorld(true);
    this._updateSelectionMarker();
    return this.getStatus();
  }

  resetPose({ resetRootAnchor = true } = {}) {
    this._assertActive();
    this._restoreBindPose();
    this.rootMotionGroup.position.set(0, 0, 0);
    this.rootMotionGroup.quaternion.identity();
    this.rootMotionGroup.updateMatrix();
    if (resetRootAnchor) this.resetRootAnchor();
    this.container.updateMatrixWorld(true);
    this.skeletonHelper.updateMatrixWorld(true);
    this._updateSelectionMarker();
    return this.getStatus();
  }

  resetRootAnchor() {
    this._assertActive();
    this.rootAnchorPosition = null;
    this.rootAnchorQuaternion = null;
    this.lastPoseTime = null;
  }

  setMeshVisible(visible) {
    this._assertActive();
    const enabled = Boolean(visible);
    this.profile.meshVisible = enabled;
    for (const [object, originalVisibility] of this.originalMeshVisibility) {
      object.visible = enabled && originalVisibility;
    }
    return enabled;
  }

  setSkeletonVisible(visible) {
    this._assertActive();
    const enabled = Boolean(visible);
    this.profile.skeletonVisible = enabled;
    this.skeletonHelper.visible = enabled;
    this._updateSelectionMarker();
    return enabled;
  }

  setSelectedJoint(joint = null) {
    this._assertActive();
    this.selectedJoint = CORE27_JOINTS.includes(joint) ? joint : null;
    this._updateSelectionMarker();
    return this.selectedJoint;
  }

  getBounds(target = this.modelRoot) {
    this._assertActive();
    this.container.updateMatrixWorld(true);
    return new THREE.Box3().setFromObject(target);
  }

  suggestScale(targetHeight = 1.72) {
    this._assertActive();
    const desiredHeight = Number(targetHeight);
    if (!Number.isFinite(desiredHeight) || desiredHeight <= 0) {
      throw new Error("Target character height must be a positive number.");
    }
    const bounds = this.getBounds(this.modelRoot);
    const currentHeight = bounds.getSize(new THREE.Vector3()).y;
    if (!Number.isFinite(currentHeight) || currentHeight <= Number.EPSILON) return null;
    return this.profile.transform.scale * desiredHeight / currentHeight;
  }

  getStatus() {
    this._assertActive();
    const mappedJoints = this.mapping.map((entry) => entry.joint);
    return {
      ready: mappedJoints.length > 0,
      mappedCount: mappedJoints.length,
      totalCount: CORE27_JOINTS.length,
      mappedJoints,
      missingJoints: CORE27_JOINTS.filter((joint) => !this.mappingByJoint.has(joint)),
      skeletonId: this.activeSkeleton.id,
      rootMotion: this.profile.rootMotion,
      rootAnchored: Boolean(this.rootAnchorPosition),
      selectedJoint: this.selectedJoint,
      selectedBoneId: this.selectedJoint
        ? this.mappingByJoint.get(this.selectedJoint)?.boneId || null
        : null,
      meshVisible: this.profile.meshVisible,
      skeletonVisible: this.profile.skeletonVisible,
      disposed: false,
    };
  }

  dispose({ disposeModel = true } = {}) {
    if (this.disposed) return null;

    this.skeletonHelper.removeFromParent();
    this.skeletonHelper.dispose();
    this.selectionMarker.removeFromParent();
    this.selectionMarker.geometry.dispose();
    this.selectionMarker.material.dispose();

    const disposal = disposeModel
      ? disposeObject3D(this.modelRoot)
      : (this.modelRoot.removeFromParent(), null);
    this.container.removeFromParent();
    this.rootMotionGroup.clear();
    this.placementGroup.clear();
    this.mapping = [];
    this.mappingByJoint.clear();
    this.bindPose.clear();
    this.boneById.clear();
    this.originalMeshVisibility.clear();
    this.disposed = true;
    return disposal;
  }
}

