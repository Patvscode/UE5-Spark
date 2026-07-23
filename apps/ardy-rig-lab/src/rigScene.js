import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { CharacterRig } from "./characterRig.js";
import { sanitizeCharacterProfile } from "./characterProfile.js";
import { disposeObject3D } from "./modelImporter.js";
import {
  CORE27_JOINTS,
  CORE27_PARENT_INDICES,
  transformPosePositions,
} from "./poseProtocol.js";

const UP = new THREE.Vector3(0, 1, 0);
const COLORS = {
  center: 0xa99cff,
  left: 0x55e6bd,
  right: 0xffa66b,
  skeleton: 0x9bc8dd,
  proxy: 0x426779,
};

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: 0.66,
    metalness: 0.06,
    ...options,
  });
}

function box(width, height, depth, color) {
  return new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    material(color),
  );
}

function jointColor(name) {
  if (name.startsWith("Left")) return COLORS.left;
  if (name.startsWith("Right")) return COLORS.right;
  return COLORS.center;
}

export class RigScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x071015);
    this.scene.fog = new THREE.FogExp2(0x071015, 0.055);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.02, 100);
    this.camera.position.set(2.7, 1.8, 3.5);

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.08;

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, 0.95, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.minDistance = 1.2;
    this.controls.maxDistance = 12;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.screenSpacePanning = true;

    this.scene.add(new THREE.HemisphereLight(0xbfe9ff, 0x172128, 2.1));
    const key = new THREE.DirectionalLight(0xfff2de, 3.2);
    key.position.set(3, 5, 4);
    key.castShadow = false;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x4ee3c0, 1.4);
    rim.position.set(-4, 2.5, -3);
    this.scene.add(rim);

    this.components = {};
    this.mapping = null;
    this.sourcePositions = null;
    this.selectedJoint = "Hips";
    this.characterRig = null;
    this.staticCharacter = null;
    this.characterAnalysis = null;
    this.characterProfile = null;
    this._buildEnvironment();
    this._buildRig();
    this.resetView();
    this.resize();
  }

  _buildEnvironment() {
    const floorGroup = new THREE.Group();
    floorGroup.name = "floor";
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(20, 20),
      material(0x0d171d, { roughness: 0.92 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.005;
    floorGroup.add(floor);
    const grid = new THREE.GridHelper(20, 40, 0x315967, 0x19323b);
    grid.material.transparent = true;
    grid.material.opacity = 0.68;
    floorGroup.add(grid);
    this.scene.add(floorGroup);
    this.components.floor = floorGroup;

    const chair = new THREE.Group();
    chair.name = "chair";
    const seat = box(0.66, 0.08, 0.66, 0x805d47);
    seat.position.set(1.45, 0.5, 0.1);
    chair.add(seat);
    const back = box(0.66, 0.72, 0.08, 0x664735);
    back.position.set(1.45, 0.86, -0.19);
    chair.add(back);
    for (const [x, z] of [[1.18, -0.14], [1.72, -0.14], [1.18, 0.34], [1.72, 0.34]]) {
      const leg = box(0.07, 0.5, 0.07, 0x503528);
      leg.position.set(x, 0.25, z);
      chair.add(leg);
    }
    this.scene.add(chair);
    this.components.chair = chair;

    const bed = new THREE.Group();
    bed.name = "bed";
    const frame = box(1.45, 0.22, 2.25, 0x263b48);
    frame.position.set(-1.75, 0.21, -0.2);
    bed.add(frame);
    const mattress = box(1.35, 0.18, 2.08, 0x8da5ad);
    mattress.position.set(-1.75, 0.41, -0.2);
    bed.add(mattress);
    const pillow = box(0.76, 0.15, 0.42, 0xd2dedf);
    pillow.position.set(-1.75, 0.57, -0.92);
    pillow.rotation.x = -0.08;
    bed.add(pillow);
    this.scene.add(bed);
    this.components.bed = bed;
  }

  _buildRig() {
    this.jointGroup = new THREE.Group();
    this.jointGroup.name = "joint-markers";
    this.jointMeshes = CORE27_JOINTS.map((name) => {
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.035, 16, 10),
        material(jointColor(name), { emissive: jointColor(name), emissiveIntensity: 0.15 }),
      );
      mesh.name = name;
      this.jointGroup.add(mesh);
      return mesh;
    });
    this.scene.add(this.jointGroup);
    this.components.joints = this.jointGroup;

    const segmentCount = CORE27_PARENT_INDICES.filter((index) => index >= 0).length;
    this.skeletonGeometry = new THREE.BufferGeometry();
    this.skeletonGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(new Float32Array(segmentCount * 2 * 3), 3),
    );
    this.skeletonLines = new THREE.LineSegments(
      this.skeletonGeometry,
      new THREE.LineBasicMaterial({ color: COLORS.skeleton, transparent: true, opacity: 0.9 }),
    );
    this.skeletonLines.name = "core27-skeleton";
    this.scene.add(this.skeletonLines);
    this.components.skeleton = this.skeletonLines;

    this.proxyGroup = new THREE.Group();
    this.proxyGroup.name = "proxy-body";
    this.proxyBones = [];
    const proxyGeometry = new THREE.CylinderGeometry(1, 1, 1, 10, 1);
    for (let index = 0; index < CORE27_PARENT_INDICES.length; index += 1) {
      if (CORE27_PARENT_INDICES[index] < 0) continue;
      const mesh = new THREE.Mesh(
        proxyGeometry,
        material(COLORS.proxy, { transparent: true, opacity: 0.64 }),
      );
      mesh.userData.jointIndex = index;
      this.proxyGroup.add(mesh);
      this.proxyBones.push(mesh);
    }
    this.scene.add(this.proxyGroup);
    this.components.proxy = this.proxyGroup;
  }

  updatePose(sourcePositions, mapping) {
    this.sourcePositions = sourcePositions;
    this.mapping = mapping;
    const positions = transformPosePositions(sourcePositions, mapping);
    const points = positions.map((position) => new THREE.Vector3(...position));

    points.forEach((point, index) => {
      const marker = this.jointMeshes[index];
      marker.position.copy(point);
      const selected = CORE27_JOINTS[index] === this.selectedJoint;
      marker.scale.setScalar(selected ? 1.75 : 1);
      marker.material.emissiveIntensity = selected ? 0.75 : 0.15;
    });

    const lineAttribute = this.skeletonGeometry.getAttribute("position");
    let lineIndex = 0;
    let proxyIndex = 0;
    for (let jointIndex = 0; jointIndex < CORE27_PARENT_INDICES.length; jointIndex += 1) {
      const parentIndex = CORE27_PARENT_INDICES[jointIndex];
      if (parentIndex < 0) continue;
      const child = points[jointIndex];
      const parent = points[parentIndex];
      lineAttribute.setXYZ(lineIndex * 2, parent.x, parent.y, parent.z);
      lineAttribute.setXYZ(lineIndex * 2 + 1, child.x, child.y, child.z);
      lineIndex += 1;

      const proxy = this.proxyBones[proxyIndex++];
      const direction = child.clone().sub(parent);
      const length = Math.max(0.001, direction.length());
      proxy.position.copy(parent).add(child).multiplyScalar(0.5);
      proxy.scale.set(0.025, length, 0.025);
      proxy.quaternion.setFromUnitVectors(UP, direction.normalize());
    }
    lineAttribute.needsUpdate = true;
    this.skeletonGeometry.computeBoundingSphere();
  }

  setSelectedJoint(name) {
    if (!CORE27_JOINTS.includes(name)) return;
    this.selectedJoint = name;
    if (this.sourcePositions && this.mapping) this.updatePose(this.sourcePositions, this.mapping);
  }

  setComponentVisible(component, visible) {
    if (this.components[component]) this.components[component].visible = Boolean(visible);
  }

  attachModel(analysis, profile, { disposePrevious = true } = {}) {
    if (!analysis?.root?.isObject3D) {
      throw new Error("RigScene requires a successfully imported Three.js model.");
    }
    this.removeModel({ disposeModel: disposePrevious });
    this.characterAnalysis = analysis;

    if (analysis.rigged && analysis.inventory?.activeSkeleton?.bones?.length) {
      this.characterRig = new CharacterRig(analysis, profile);
      this.characterProfile = this.characterRig.getProfile();
      this.scene.add(this.characterRig.object3D);
      return this.characterRig.getStatus();
    }

    this.characterProfile = sanitizeCharacterProfile(profile, {
      modelId: profile?.modelId,
      modelName: profile?.modelName || analysis.sourceName,
      availableBones: [],
    });
    const container = new THREE.Group();
    container.name = "static-imported-character";
    const placement = new THREE.Group();
    placement.name = "static-character-placement";
    container.add(placement);
    placement.add(analysis.root);
    this.scene.add(container);
    this.staticCharacter = {
      container,
      placement,
      modelRoot: analysis.root,
      originalVisibility: new Map(),
    };
    analysis.root.traverse((object) => {
      if (object.isMesh || object.isPoints || object.isLine) {
        this.staticCharacter.originalVisibility.set(object, object.visible);
      }
    });
    this.setCharacterProfile(this.characterProfile);
    return {
      ready: false,
      mappedCount: 0,
      totalCount: CORE27_JOINTS.length,
      static: true,
    };
  }

  removeModel({ disposeModel = true } = {}) {
    if (this.characterRig) {
      this.characterRig.dispose({ disposeModel });
      this.characterRig = null;
    }
    if (this.staticCharacter) {
      const { container, modelRoot } = this.staticCharacter;
      if (disposeModel) disposeObject3D(modelRoot);
      else modelRoot.removeFromParent();
      container.removeFromParent();
      container.clear();
      this.staticCharacter.originalVisibility.clear();
      this.staticCharacter = null;
    }
    this.characterAnalysis = null;
    this.characterProfile = null;
  }

  setCharacterProfile(profile) {
    if (this.characterRig) {
      const status = this.characterRig.setProfile(profile);
      this.characterProfile = this.characterRig.getProfile();
      return status;
    }
    if (!this.staticCharacter) return null;
    this.characterProfile = sanitizeCharacterProfile(profile, {
      modelId: profile?.modelId,
      modelName: profile?.modelName || this.characterAnalysis?.sourceName,
      availableBones: [],
    });
    const { transform } = this.characterProfile;
    this.staticCharacter.placement.position.fromArray(transform.offset);
    this.staticCharacter.placement.rotation.set(
      transform.pitchDegrees * Math.PI / 180,
      transform.yawDegrees * Math.PI / 180,
      transform.rollDegrees * Math.PI / 180,
      "YXZ",
    );
    this.staticCharacter.placement.scale.setScalar(transform.scale);
    for (const [object, authoredVisible] of this.staticCharacter.originalVisibility) {
      object.visible = this.characterProfile.meshVisible && authoredVisible;
    }
    this.staticCharacter.container.updateMatrixWorld(true);
    return {
      ready: false,
      mappedCount: 0,
      totalCount: CORE27_JOINTS.length,
      static: true,
    };
  }

  applyCharacterPose(frame) {
    return this.characterRig?.applyPose(frame) || null;
  }

  resetCharacterRootAnchor() {
    if (this.characterRig) this.characterRig.resetRootAnchor();
  }

  setCharacterSelectedJoint(name = null) {
    return this.characterRig?.setSelectedJoint(name) || null;
  }

  suggestCharacterScale(targetHeight = 1.72) {
    if (this.characterRig) return this.characterRig.suggestScale(targetHeight);
    if (!this.staticCharacter || !this.characterProfile) return null;
    this.staticCharacter.container.updateMatrixWorld(true);
    const height = new THREE.Box3()
      .setFromObject(this.staticCharacter.modelRoot)
      .getSize(new THREE.Vector3()).y;
    if (!Number.isFinite(height) || height <= Number.EPSILON) return null;
    return this.characterProfile.transform.scale * targetHeight / height;
  }

  focusCharacter() {
    let bounds = null;
    if (this.characterRig) bounds = this.characterRig.getBounds();
    else if (this.staticCharacter) {
      this.staticCharacter.container.updateMatrixWorld(true);
      bounds = new THREE.Box3().setFromObject(this.staticCharacter.modelRoot);
    }
    if (!bounds || bounds.isEmpty()) {
      this.resetView();
      return false;
    }
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const maximum = Math.max(size.x, size.y, size.z, 0.25);
    const halfFov = THREE.MathUtils.degToRad(this.camera.fov * 0.5);
    const distance = Math.min(30, Math.max(0.45, maximum * 0.72 / Math.tan(halfFov)));
    const direction = this.camera.position.clone().sub(this.controls.target);
    if (direction.lengthSq() < Number.EPSILON) direction.set(1, 0.25, 1);
    direction.normalize();
    this.controls.target.copy(center);
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.controls.minDistance = Math.max(0.08, maximum * 0.12);
    this.controls.maxDistance = Math.max(12, maximum * 12);
    this.controls.update();
    return true;
  }

  getCharacterStatus() {
    if (this.characterRig) return this.characterRig.getStatus();
    if (this.staticCharacter) {
      return {
        ready: false,
        mappedCount: 0,
        totalCount: CORE27_JOINTS.length,
        static: true,
      };
    }
    return null;
  }

  resetView() {
    this.camera.position.set(2.7, 1.8, 3.5);
    this.controls.target.set(0, 0.95, 0);
    this.controls.update();
  }

  resize() {
    const width = Math.max(1, this.canvas.clientWidth);
    const height = Math.max(1, this.canvas.clientHeight);
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const targetWidth = Math.floor(width * pixelRatio);
    const targetHeight = Math.floor(height * pixelRatio);
    if (this.canvas.width !== targetWidth || this.canvas.height !== targetHeight) {
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    }
  }

  render() {
    this.resize();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
