import "./styles.css";

import {
  characterProfileSummary,
  defaultCharacterProfile,
  parseCharacterProfile,
  sanitizeCharacterProfile,
  serializeCharacterProfile,
} from "./characterProfile.js";
import {
  importModelFile,
  importModelFiles,
  modelFormatForFile,
  selectImportedSkeleton,
} from "./modelImporter.js";
import {
  CORE27_JOINTS,
  SOURCE_REVISION,
  createNeutralFrame,
  defaultRigMapping,
  sanitizeRigMapping,
} from "./poseProtocol.js";
import { PoseStream } from "./poseStream.js";
import { RigScene } from "./rigScene.js";

function requiredElement(id) {
  const element = document.querySelector(`#${id}`);
  if (!element) throw new Error(`Rig Lab is missing the required #${id} control.`);
  return element;
}

const elements = {
  canvas: requiredElement("rig-canvas"),
  connectionBadge: requiredElement("connection-badge"),
  connectionLabel: requiredElement("connection-label"),
  motionState: requiredElement("motion-state"),
  prompt: requiredElement("motion-prompt"),
  behavior: requiredElement("behavior"),
  duration: requiredElement("duration"),
  intensity: requiredElement("intensity"),
  intensityValue: requiredElement("intensity-value"),
  runOnce: requiredElement("run-once"),
  runLoop: requiredElement("run-loop"),
  stop: requiredElement("stop-motion"),
  notice: requiredElement("motion-notice"),
  resetView: requiredElement("reset-view"),

  modelFiles: requiredElement("model-file-input"),
  modelUpload: requiredElement("model-upload"),
  savedModel: requiredElement("saved-model-select"),
  modelLoad: requiredElement("model-load"),
  modelRemove: requiredElement("model-remove"),
  modelStatus: requiredElement("model-status"),
  modelDiagnostic: requiredElement("model-diagnostic"),
  modelSummary: requiredElement("model-summary"),
  meshCount: requiredElement("model-mesh-count"),
  skeletonCount: requiredElement("model-skeleton-count"),
  boneCount: requiredElement("model-bone-count"),
  activeSkeleton: requiredElement("active-skeleton-select"),
  characterMeshVisible: requiredElement("character-mesh-visible"),
  characterSkeletonVisible: requiredElement("character-skeleton-visible"),

  mappingCount: requiredElement("mapping-count"),
  mappingCoverage: requiredElement("mapping-coverage"),
  mappingRows: requiredElement("mapping-rows"),
  autoMap: requiredElement("auto-map-character"),
  clearMap: requiredElement("reset-character-map"),

  autoFit: requiredElement("auto-fit-character"),
  resetCharacterTransform: requiredElement("reset-character-transform"),
  characterScale: requiredElement("character-scale"),
  characterYaw: requiredElement("character-yaw"),
  characterPitch: requiredElement("character-pitch"),
  characterRoll: requiredElement("character-roll"),
  characterOffsets: [
    requiredElement("character-offset-x"),
    requiredElement("character-offset-y"),
    requiredElement("character-offset-z"),
  ],
  characterJoint: requiredElement("character-joint-select"),
  targetBone: requiredElement("target-bone-select"),
  rotationOffsets: [
    requiredElement("rotation-offset-x"),
    requiredElement("rotation-offset-y"),
    requiredElement("rotation-offset-z"),
  ],
  resetRotation: requiredElement("reset-rotation-offset"),
  rootMotion: requiredElement("root-motion"),

  profileState: requiredElement("profile-state"),
  profileName: requiredElement("profile-name"),
  saveProfile: requiredElement("save-profile"),
  reloadProfile: requiredElement("reload-profile"),
  exportProfile: requiredElement("export-profile"),
  importProfile: requiredElement("profile-import-input"),
  profileNotice: requiredElement("profile-notice"),

  rigScale: requiredElement("rig-scale"),
  rigYaw: requiredElement("rig-yaw"),
  mirrorX: requiredElement("mirror-x"),
  rigOffsets: [
    requiredElement("rig-offset-x"),
    requiredElement("rig-offset-y"),
    requiredElement("rig-offset-z"),
  ],
  jointSelect: requiredElement("joint-select"),
  jointOffsets: [
    requiredElement("joint-offset-x"),
    requiredElement("joint-offset-y"),
    requiredElement("joint-offset-z"),
  ],
  resetJoint: requiredElement("reset-joint"),
  resetRig: requiredElement("reset-rig"),
};

let overlayMapping = defaultRigMapping();
let providerHealth = {
  checked: false,
  ready: false,
  dynamicTextReady: false,
  provider: "",
  detail: "Checking protocol v2.",
};
let currentFrame = createNeutralFrame();
let registeredModels = [];
let activeModel = null;
let activeAnalysis = null;
let characterProfile = null;
let profileDirty = false;
let modelState = "empty";
let importGeneration = 0;

const visibleComponents = Object.fromEntries(
  [...document.querySelectorAll("[data-component]")]
    .map((input) => [input.dataset.component, input.checked]),
);
const scene = new RigScene(elements.canvas);
scene.updatePose(currentFrame.positions, overlayMapping);

function setModelStatus(label, state = modelState) {
  elements.modelStatus.textContent = label;
  elements.modelStatus.dataset.state = state;
}

function setDiagnostic(title, detail, warning = false) {
  elements.modelDiagnostic.classList.toggle("is-unrigged", warning);
  const titleNode = elements.modelDiagnostic.querySelector("strong");
  const detailNode = elements.modelDiagnostic.querySelector("small");
  if (titleNode) titleNode.textContent = title;
  if (detailNode) detailNode.textContent = detail;
}

function activeBones() {
  return activeAnalysis?.inventory?.activeSkeleton?.bones || [];
}

function availableBoneIds() {
  return activeBones().map((record) => record.id);
}

function modelLabel(model) {
  if (!model && !activeAnalysis) return "No model";
  return String(model?.name || activeAnalysis?.sourceName || "Local model")
    .replace(/\.(?:glb|gltf|vrm|fbx)$/i, "");
}

function currentModelIdentity() {
  return {
    modelId: activeModel?.id || "",
    modelName: activeModel?.name || activeAnalysis?.sourceName || "Imported character",
  };
}

function reviewedProfile(profileValue = characterProfile) {
  return sanitizeCharacterProfile(profileValue || defaultCharacterProfile(currentModelIdentity()), {
    ...currentModelIdentity(),
    availableBones: availableBoneIds(),
  });
}

function setProfileDirty(dirty, notice = "") {
  profileDirty = Boolean(dirty);
  if (!characterProfile) {
    elements.profileState.textContent = "No profile";
  } else if (!activeModel?.id) {
    elements.profileState.textContent = "Local only";
  } else {
    elements.profileState.textContent = profileDirty ? "Unsaved" : "Saved";
  }
  if (notice) elements.profileNotice.textContent = notice;
}

function streamStateChanged(state) {
  elements.stop.disabled = !state.active;
  elements.runOnce.disabled = state.fetching || !providerHealth.ready;
  elements.runLoop.disabled = state.fetching || !providerHealth.ready;
  elements.motionState.textContent = {
    reference: "Reference pose",
    once: state.fetching ? "Generating" : "Once · live",
    loop: state.fetching && state.bufferedFrames === 0 ? "Generating" : "Loop · live",
    buffering: "Buffering",
    complete: "Run complete",
    stopped: "Stopped",
    error: "Pose error",
  }[state.mode] || state.mode;
  elements.motionState.classList.toggle("is-live", ["once", "loop"].includes(state.mode));
  elements.motionState.classList.toggle("is-error", state.mode === "error");

  if (state.mode === "error") {
    elements.notice.textContent = `${state.lastError} Holding the last verified pose; no fallback motion is simulated.`;
  } else if (state.mode === "complete") {
    elements.notice.textContent = `Completed ${state.playedFrames} real Core27 frames. Holding the final generated pose.`;
  } else if (state.mode === "stopped") {
    elements.notice.textContent = "Stopped. Holding the last received Core27 frame.";
  } else if (state.active) {
    elements.notice.textContent = `${state.bufferedFrames} real frames buffered · sequence ${state.sequence || "pending"} · ${state.mode === "loop" ? "looping" : `${state.playedFrames}/${state.targetFrames} played`}.`;
  }
}

const poseStream = new PoseStream({ onState: streamStateChanged });
streamStateChanged(poseStream.snapshot());

function providerIsExact(payload) {
  return payload?.protocolVersion === 2
    && payload?.fps === 20
    && payload?.coordinateSystem === "ardy-rh-x-left-y-up-z-forward-meters"
    && payload?.source?.system === "nv-tlabs/ardy"
    && payload?.source?.revision === SOURCE_REVISION
    && payload?.source?.skeleton === "Core27"
    && JSON.stringify(payload?.source?.jointOrder) === JSON.stringify(CORE27_JOINTS);
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/ardy-health", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !providerIsExact(payload)) {
      throw new Error(
        payload?.protocolVersion && payload.protocolVersion !== 2
          ? `Protocol v${payload.protocolVersion} is running; this lab requires v2.`
          : payload?.detail || "The strict ARDY v2 descriptor is unavailable.",
      );
    }
    providerHealth = {
      checked: true,
      ready: true,
      dynamicTextReady: payload.dynamicTextReady === true,
      provider: String(payload.provider || "unknown"),
      detail: payload.dynamicTextReady === true
        ? "Real dynamic text conditioning is ready."
        : "Base behavior poses are available; dynamic text conditioning is not ready.",
    };
    elements.connectionBadge.className = `connection-badge ${providerHealth.dynamicTextReady ? "is-ready" : "is-limited"}`;
    elements.connectionLabel.textContent = providerHealth.dynamicTextReady
      ? "ARDY v2 ready"
      : `v2 ${providerHealth.provider || "limited"}`;
  } catch (error) {
    providerHealth = {
      checked: true,
      ready: false,
      dynamicTextReady: false,
      provider: "",
      detail: error.message || "ARDY v2 is unavailable.",
    };
    elements.connectionBadge.className = "connection-badge is-offline";
    elements.connectionLabel.textContent = "ARDY v2 offline";
    if (!poseStream.active) {
      elements.notice.textContent = `${providerHealth.detail} The visible rig is the labeled neutral reference pose.`;
    }
  }
  const busy = poseStream.fetching;
  elements.runOnce.disabled = busy || !providerHealth.ready;
  elements.runLoop.disabled = busy || !providerHealth.ready;
}

function readOverlayMapping() {
  const selectedJoint = elements.jointSelect.value;
  overlayMapping = sanitizeRigMapping({
    ...overlayMapping,
    scale: elements.rigScale.value,
    yawDegrees: elements.rigYaw.value,
    mirrorX: elements.mirrorX.checked,
    offset: elements.rigOffsets.map((input) => input.value),
    jointOffsetsCm: {
      ...overlayMapping.jointOffsetsCm,
      [selectedJoint]: elements.jointOffsets.map((input) => input.value),
    },
  });
  writeOverlayInputs(false);
  scene.updatePose(currentFrame.positions, overlayMapping);
}

function writeOverlayInputs(includeJoint = true) {
  elements.rigScale.value = String(overlayMapping.scale);
  elements.rigYaw.value = String(overlayMapping.yawDegrees);
  elements.mirrorX.checked = overlayMapping.mirrorX;
  elements.rigOffsets.forEach((input, index) => {
    input.value = String(overlayMapping.offset[index]);
  });
  if (includeJoint) {
    const offsets = overlayMapping.jointOffsetsCm[elements.jointSelect.value] || [0, 0, 0];
    elements.jointOffsets.forEach((input, index) => {
      input.value = String(offsets[index]);
    });
  }
}

function clearSelect(select, placeholder, placeholderValue = "") {
  select.replaceChildren();
  const option = document.createElement("option");
  option.value = placeholderValue;
  option.textContent = placeholder;
  select.append(option);
}

function appendBoneOptions(select, selectedId = null) {
  clearSelect(select, "Not mapped");
  for (const record of activeBones()) {
    const option = document.createElement("option");
    option.value = record.id;
    option.textContent = `${record.name} · ${record.path}`;
    option.selected = record.id === selectedId;
    select.append(option);
  }
}

function setCharacterControlsEnabled(enabled) {
  for (const element of [
    elements.autoMap,
    elements.clearMap,
    elements.characterJoint,
    elements.targetBone,
    ...elements.rotationOffsets,
    elements.resetRotation,
    elements.rootMotion,
    elements.profileName,
    elements.exportProfile,
  ]) {
    element.disabled = !enabled;
  }
  elements.saveProfile.disabled = !enabled || !activeModel?.id;
  elements.reloadProfile.disabled = !enabled || !activeModel?.id || !activeModel.hasProfile;
  const hasModel = Boolean(activeAnalysis);
  elements.autoFit.disabled = !hasModel;
  elements.resetCharacterTransform.disabled = !hasModel;
  for (const element of [
    elements.characterScale,
    elements.characterYaw,
    elements.characterPitch,
    elements.characterRoll,
    ...elements.characterOffsets,
  ]) {
    element.disabled = !hasModel;
  }
}

function syncCharacterTransformInputs() {
  const profile = characterProfile || defaultCharacterProfile();
  elements.characterScale.value = String(profile.transform.scale);
  elements.characterYaw.value = String(profile.transform.yawDegrees);
  elements.characterPitch.value = String(profile.transform.pitchDegrees);
  elements.characterRoll.value = String(profile.transform.rollDegrees);
  elements.characterOffsets.forEach((input, index) => {
    input.value = String(profile.transform.offset[index]);
  });
  elements.rootMotion.checked = profile.rootMotion === true;
  elements.characterMeshVisible.checked = profile.meshVisible !== false;
  elements.characterSkeletonVisible.checked = profile.skeletonVisible === true;
  elements.profileName.value = profile.name || "";
}

function syncSelectedJointControls() {
  const joint = elements.characterJoint.value || "Hips";
  const profile = characterProfile;
  const enabled = Boolean(profile && activeAnalysis?.rigged);
  appendBoneOptions(elements.targetBone, profile?.boneMap?.[joint] || null);
  elements.targetBone.disabled = !enabled;
  const offsets = profile?.rotationOffsetsDegrees?.[joint] || [0, 0, 0];
  elements.rotationOffsets.forEach((input, index) => {
    input.value = String(offsets[index]);
    input.disabled = !enabled;
  });
  elements.resetRotation.disabled = !enabled;
  scene.setCharacterSelectedJoint(enabled ? joint : null);
}

function renderMappingRows() {
  elements.mappingRows.replaceChildren();
  if (!characterProfile || !activeAnalysis?.rigged) {
    const empty = document.createElement("div");
    empty.className = "mapping-empty";
    const title = document.createElement("strong");
    title.textContent = "27 mapping rows will appear here";
    const detail = document.createElement("span");
    detail.textContent = "Load a skinned model to inspect its skeleton.";
    empty.append(title, detail);
    elements.mappingRows.append(empty);
    return;
  }

  for (const joint of CORE27_JOINTS) {
    const row = document.createElement("div");
    row.className = "mapping-row";
    row.setAttribute("role", "listitem");
    row.dataset.joint = joint;
    const label = document.createElement("label");
    label.textContent = joint;
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${joint} target bone`);
    appendBoneOptions(select, characterProfile.boneMap[joint]);
    select.addEventListener("change", () => {
      applyBoneMapping(joint, select.value || null);
      elements.characterJoint.value = joint;
      syncSelectedJointControls();
    });
    label.append(select);
    const status = document.createElement("span");
    status.className = characterProfile.boneMap[joint] ? "mapping-ok" : "mapping-missing";
    status.textContent = characterProfile.boneMap[joint] ? "Mapped" : "Missing";
    row.append(label, status);
    elements.mappingRows.append(row);
  }
}

function updateMappingSummary() {
  const summary = characterProfileSummary(characterProfile || defaultCharacterProfile());
  elements.mappingCount.textContent = `${summary.mappedCount} / ${summary.totalCount}`;
  elements.mappingCoverage.value = summary.mappedCount;
  elements.mappingCoverage.textContent = `${summary.mappedCount} of ${summary.totalCount} joints mapped`;
  if (characterProfile && activeAnalysis?.rigged) {
    const detail = summary.ready
      ? "All required body chains are mapped and ready for live ARDY motion."
      : `${summary.missingRequired.length} required body joints still need a target bone.`;
    elements.profileNotice.textContent = profileDirty
      ? `${detail} Save when the mapping feels correct.`
      : detail;
  }
}

function updateCharacterUI({ rebuildRows = true } = {}) {
  const inventory = activeAnalysis?.inventory;
  const rigged = Boolean(activeAnalysis?.rigged && inventory?.activeSkeleton);
  elements.modelSummary.textContent = modelLabel(activeModel);
  elements.meshCount.textContent = String(inventory?.meshes?.length || 0);
  elements.skeletonCount.textContent = String(inventory?.skeletonGroups?.length || 0);
  elements.boneCount.textContent = String(inventory?.activeSkeleton?.bones?.length || 0);

  clearSelect(elements.activeSkeleton, rigged ? "Choose a skeleton" : "Load a rigged model first");
  if (rigged) {
    for (const group of inventory.skeletonGroups) {
      const option = document.createElement("option");
      option.value = group.id;
      option.textContent = `${group.skinnedMeshes.map((mesh) => mesh.name).join(", ")} · ${group.bones.length} bones`;
      option.selected = group.id === inventory.activeSkeleton.id;
      elements.activeSkeleton.append(option);
    }
  }
  elements.activeSkeleton.disabled = !rigged;
  elements.characterMeshVisible.disabled = !activeAnalysis;
  elements.characterSkeletonVisible.disabled = !rigged;

  clearSelect(elements.characterJoint, rigged ? "Select a Core27 joint" : "Load a rigged model first");
  if (rigged) {
    for (const joint of CORE27_JOINTS) {
      const option = document.createElement("option");
      option.value = joint;
      option.textContent = joint;
      elements.characterJoint.append(option);
    }
    elements.characterJoint.value = "Hips";
  }
  elements.characterJoint.disabled = !rigged;
  setCharacterControlsEnabled(rigged);

  if (!activeAnalysis) {
    modelState = "empty";
    setDiagnostic(
      "No rigged character loaded",
      "Add a skinned GLB, GLTF, VRM, or FBX. Static meshes can be viewed, but ARDY cannot move them until they have a skeleton and skin weights.",
      true,
    );
  } else if (!rigged) {
    modelState = "static";
    setDiagnostic("Static model loaded", activeAnalysis.diagnostic.message, true);
  } else {
    const summary = characterProfileSummary(characterProfile);
    modelState = summary.ready ? "ready" : "rigged";
    setDiagnostic(
      summary.ready ? "Character rig ready" : "Skeleton found — finish mapping",
      activeAnalysis.diagnostic.message,
      !summary.ready,
    );
  }
  setModelStatus({
    empty: "Waiting",
    static: "Static only",
    rigged: "Needs mapping",
    ready: "Ready",
    loading: "Loading…",
    error: "Import failed",
  }[modelState] || modelState, modelState);

  if (characterProfile) syncCharacterTransformInputs();
  else setProfileDirty(false);
  if (rebuildRows) renderMappingRows();
  syncSelectedJointControls();
  updateMappingSummary();
}

function applyCharacterProfile({ dirty = true, rebuildRows = false, resetRootAnchor = false } = {}) {
  if (!characterProfile) return;
  characterProfile = reviewedProfile(characterProfile);
  scene.setCharacterProfile(characterProfile);
  if (resetRootAnchor) scene.resetCharacterRootAnchor();
  scene.applyCharacterPose(currentFrame);
  setProfileDirty(dirty);
  syncCharacterTransformInputs();
  if (rebuildRows) renderMappingRows();
  syncSelectedJointControls();
  updateMappingSummary();
}

function applyBoneMapping(joint, boneId) {
  if (!characterProfile || !CORE27_JOINTS.includes(joint)) return;
  const nextMap = { ...characterProfile.boneMap };
  if (boneId) {
    for (const sourceJoint of CORE27_JOINTS) {
      if (sourceJoint !== joint && nextMap[sourceJoint] === boneId) nextMap[sourceJoint] = null;
    }
  }
  nextMap[joint] = boneId || null;
  characterProfile = { ...characterProfile, boneMap: nextMap };
  applyCharacterProfile({ dirty: true, rebuildRows: true });
}

function autoMapCharacter({ clearFirst = false } = {}) {
  if (!characterProfile || !activeAnalysis?.autoMap) return;
  const nextMap = clearFirst
    ? Object.fromEntries(CORE27_JOINTS.map((joint) => [joint, null]))
    : { ...characterProfile.boneMap };
  const used = new Set(Object.values(nextMap).filter(Boolean));
  for (const joint of CORE27_JOINTS) {
    const candidate = activeAnalysis.autoMap.jointToBoneId[joint];
    if (!nextMap[joint] && candidate && !used.has(candidate)) {
      nextMap[joint] = candidate;
      used.add(candidate);
    }
  }
  characterProfile = {
    ...characterProfile,
    skeletonId: activeAnalysis.inventory.activeSkeleton.id,
    boneMap: nextMap,
  };
  applyCharacterProfile({ dirty: true, rebuildRows: true });
}

function baseProfileForAnalysis(analysis, model) {
  const profile = defaultCharacterProfile({
    modelId: model?.id || "",
    modelName: model?.name || analysis.sourceName,
    name: String(model?.name || analysis.sourceName || "Imported character")
      .replace(/\.(?:glb|gltf|vrm|fbx)$/i, ""),
  });
  if (analysis.rigged) {
    profile.skeletonId = analysis.inventory.activeSkeleton.id;
    profile.boneMap = { ...analysis.autoMap.jointToBoneId };
    profile.skeletonVisible = false;
  }
  return sanitizeCharacterProfile(profile, {
    modelId: model?.id || "",
    modelName: model?.name || analysis.sourceName,
    availableBones: analysis.inventory.activeSkeleton?.bones?.map((record) => record.id) || [],
  });
}

async function loadStoredProfile(model, analysis) {
  if (!model?.id || !model.hasProfile) return null;
  const response = await fetch(`/api/models/${model.id}/profile`, { cache: "no-store" });
  if (response.status === 404) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "The saved rig profile could not be loaded.");
  const activeSkeletonId = analysis.inventory.activeSkeleton?.id || "";
  if (payload.skeletonId && payload.skeletonId !== activeSkeletonId) {
    throw new Error("The saved profile targets a different skeleton in this model. Auto-map this skeleton and save a new profile.");
  }
  return sanitizeCharacterProfile(payload, {
    modelId: model.id,
    modelName: model.name,
    availableBones: analysis.inventory.activeSkeleton?.bones?.map((record) => record.id) || [],
  });
}

async function installImportedModel(analysis, model = null, storedProfile = null) {
  importGeneration += 1;
  scene.attachModel(analysis, storedProfile || baseProfileForAnalysis(analysis, model));
  activeAnalysis = analysis;
  activeModel = model;
  characterProfile = storedProfile || baseProfileForAnalysis(analysis, model);
  characterProfile = reviewedProfile(characterProfile);
  profileDirty = !storedProfile;
  scene.setCharacterProfile(characterProfile);
  scene.applyCharacterPose(currentFrame);
  scene.focusCharacter();
  updateCharacterUI();
  setProfileDirty(!storedProfile, storedProfile
    ? "Loaded the saved private rig profile."
    : analysis.rigged
      ? "Auto-map has been applied as a starting point. Review it, adjust rotations, then save."
      : "This model has no usable skin and skeleton. It is visible for inspection only.");
}

function uploadContentType(file) {
  const format = modelFormatForFile(file);
  if (["glb", "vrm"].includes(format)) return "model/gltf-binary";
  return "application/octet-stream";
}

async function uploadPortableModel(file) {
  const response = await fetch("/api/models", {
    method: "POST",
    headers: {
      "Content-Type": uploadContentType(file),
      "X-Rig-Model-Name": encodeURIComponent(file.name),
    },
    body: file,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "The model could not be stored on this Spark.");
  return payload;
}

function chooseEntryFile(files) {
  const candidates = files.filter((file) => modelFormatForFile(file));
  if (candidates.length !== 1) {
    throw new Error(candidates.length === 0
      ? "Choose one GLB, GLTF, VRM, or FBX entry file."
      : "Choose one model entry at a time. GLTF texture and .bin sidecars may be selected with it.");
  }
  return candidates[0];
}

async function addSelectedModel() {
  const files = [...elements.modelFiles.files];
  if (files.length === 0) {
    setModelStatus("Choose files", "error");
    return;
  }
  const generation = ++importGeneration;
  modelState = "loading";
  setModelStatus("Inspecting…", "loading");
  elements.modelUpload.disabled = true;
  try {
    const entry = chooseEntryFile(files);
    const analysis = await importModelFiles(files, {
      entryFileName: entry.webkitRelativePath || entry.name,
    });
    if (generation !== importGeneration) return;
    if (!analysis.root) throw new Error(analysis.diagnostic?.message || "The model could not be read.");

    let model = null;
    if (modelFormatForFile(entry) === "gltf") {
      setModelStatus("Local GLTF", analysis.rigged ? "rigged" : "static");
    } else {
      model = await uploadPortableModel(entry);
      await refreshModelLibrary(model.id);
    }
    await installImportedModel(analysis, model);
    elements.modelFiles.value = "";
  } catch (error) {
    modelState = "error";
    setModelStatus("Import failed", "error");
    setDiagnostic("Model import failed", error.message || "The selected model could not be loaded.", true);
  } finally {
    elements.modelUpload.disabled = false;
  }
}

async function loadRegisteredModel(model) {
  if (!model) return;
  const generation = ++importGeneration;
  modelState = "loading";
  setModelStatus("Loading…", "loading");
  elements.modelLoad.disabled = true;
  try {
    const response = await fetch(model.fileUrl, { cache: "no-store" });
    if (!response.ok) throw new Error("The stored model file could not be read.");
    const blob = await response.blob();
    const file = new File([blob], model.name, { type: blob.type || uploadContentType(model) });
    const analysis = await importModelFile(file);
    if (generation !== importGeneration) return;
    if (!analysis.root) throw new Error(analysis.diagnostic?.message || "The model could not be loaded.");
    let storedProfile = null;
    try {
      storedProfile = await loadStoredProfile(model, analysis);
    } catch (profileError) {
      elements.profileNotice.textContent = profileError.message;
    }
    await installImportedModel(analysis, model, storedProfile);
  } catch (error) {
    modelState = "error";
    setModelStatus("Load failed", "error");
    setDiagnostic("Saved model could not be loaded", error.message, true);
  } finally {
    elements.modelLoad.disabled = !elements.savedModel.value;
  }
}

async function refreshModelLibrary(preferredId = "") {
  try {
    const response = await fetch("/api/models", { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !Array.isArray(payload.models)) {
      throw new Error(payload.detail || "The private model library is unavailable.");
    }
    registeredModels = payload.models;
    const selectedId = preferredId || elements.savedModel.value || activeModel?.id || "";
    clearSelect(elements.savedModel, registeredModels.length ? "Choose a saved model" : "No saved models yet");
    for (const model of registeredModels) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.name} · ${(model.size / 1024 / 1024).toFixed(1)} MB${model.hasProfile ? " · rig saved" : ""}`;
      option.selected = model.id === selectedId;
      elements.savedModel.append(option);
    }
    const selected = registeredModels.some((model) => model.id === selectedId) ? selectedId : "";
    elements.savedModel.value = selected;
    elements.modelLoad.disabled = !selected;
    elements.modelRemove.disabled = !selected;
  } catch (error) {
    setModelStatus("Library offline", "error");
  }
}

async function saveCurrentProfile() {
  if (!activeModel?.id || !characterProfile) return;
  characterProfile = reviewedProfile({
    ...characterProfile,
    name: elements.profileName.value,
  });
  elements.saveProfile.disabled = true;
  try {
    const response = await fetch(`/api/models/${activeModel.id}/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(characterProfile),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "The profile could not be saved.");
    characterProfile = reviewedProfile(payload);
    activeModel = { ...activeModel, hasProfile: true };
    scene.setCharacterProfile(characterProfile);
    setProfileDirty(false, "Saved privately on this Spark. You can reload it with this character at any time.");
    elements.reloadProfile.disabled = false;
    await refreshModelLibrary(activeModel.id);
  } catch (error) {
    setProfileDirty(true, error.message || "The profile could not be saved.");
  } finally {
    elements.saveProfile.disabled = false;
  }
}

async function reloadCurrentProfile() {
  if (!activeModel?.id || !activeAnalysis) return;
  try {
    const restored = await loadStoredProfile(activeModel, activeAnalysis);
    if (!restored) throw new Error("This model does not have a saved rig profile yet.");
    characterProfile = restored;
    applyCharacterProfile({ dirty: false, rebuildRows: true, resetRootAnchor: true });
    setProfileDirty(false, "Reloaded the last saved private profile.");
  } catch (error) {
    elements.profileNotice.textContent = error.message;
  }
}

function exportCurrentProfile() {
  if (!characterProfile) return;
  characterProfile = reviewedProfile({
    ...characterProfile,
    name: elements.profileName.value,
  });
  const blob = new Blob([serializeCharacterProfile(characterProfile)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${(characterProfile.name || "ardy-rig-profile").replace(/[^a-z0-9_-]+/gi, "-")}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function importCharacterProfile(file) {
  if (!file || !activeAnalysis?.rigged) return;
  try {
    const parsed = parseCharacterProfile(await file.text(), {
      ...currentModelIdentity(),
      availableBones: availableBoneIds(),
    });
    if (parsed.modelId && activeModel?.id && parsed.modelId !== activeModel.id) {
      throw new Error("This profile was exported for a different model.");
    }
    const skeletonId = activeAnalysis.inventory.activeSkeleton.id;
    if (parsed.skeletonId && parsed.skeletonId !== skeletonId) {
      throw new Error("This profile targets a different skeleton in the model.");
    }
    characterProfile = { ...parsed, skeletonId };
    applyCharacterProfile({ dirty: true, rebuildRows: true, resetRootAnchor: true });
    elements.profileNotice.textContent = "Imported successfully. Review the character, then Save to keep it in this Spark.";
  } catch (error) {
    elements.profileNotice.textContent = error.message || "The profile could not be imported.";
  } finally {
    elements.importProfile.value = "";
  }
}

async function removeSelectedModel() {
  const id = elements.savedModel.value;
  const model = registeredModels.find((entry) => entry.id === id);
  if (!model || !window.confirm(`Remove ${model.name} and its saved rig profile from this private Rig Lab?`)) return;
  try {
    const response = await fetch(`/api/models/${id}`, { method: "DELETE" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "The model could not be removed.");
    if (activeModel?.id === id) {
      scene.removeModel();
      activeModel = null;
      activeAnalysis = null;
      characterProfile = null;
      updateCharacterUI();
    }
    await refreshModelLibrary();
  } catch (error) {
    setModelStatus(error.message || "Remove failed", "error");
  }
}

async function runMotion(mode) {
  if (!providerHealth.ready) {
    elements.notice.textContent = providerHealth.detail;
    return;
  }
  const prompt = elements.prompt.value.trim();
  if (prompt && !providerHealth.dynamicTextReady) {
    elements.notice.textContent = "Dynamic text conditioning is not ready. Clear the prompt to request the selected real base behavior without pretending the text was followed.";
    return;
  }
  try {
    scene.resetCharacterRootAnchor();
    await poseStream.start({
      mode,
      prompt,
      behavior: elements.behavior.value,
      intensity: elements.intensity.value,
      duration: elements.duration.value,
    });
  } catch (error) {
    elements.notice.textContent = error.message || "The pose request was not started.";
  }
}

for (const name of CORE27_JOINTS) {
  const option = document.createElement("option");
  option.value = name;
  option.textContent = name;
  elements.jointSelect.append(option);
}
elements.jointSelect.value = "Hips";
writeOverlayInputs();

elements.intensity.addEventListener("input", () => {
  elements.intensityValue.textContent = `${Math.round(Number(elements.intensity.value) * 100)}%`;
});
elements.runOnce.addEventListener("click", () => runMotion("once"));
elements.runLoop.addEventListener("click", () => runMotion("loop"));
elements.stop.addEventListener("click", () => poseStream.stop());
elements.resetView.addEventListener("click", () => scene.resetView());

elements.modelUpload.addEventListener("click", addSelectedModel);
elements.savedModel.addEventListener("change", () => {
  const selected = Boolean(elements.savedModel.value);
  elements.modelLoad.disabled = !selected;
  elements.modelRemove.disabled = !selected;
});
elements.modelLoad.addEventListener("click", () => {
  loadRegisteredModel(registeredModels.find((model) => model.id === elements.savedModel.value));
});
elements.modelRemove.addEventListener("click", removeSelectedModel);
elements.activeSkeleton.addEventListener("change", () => {
  if (!activeAnalysis?.rigged || !elements.activeSkeleton.value) return;
  try {
    const analysis = selectImportedSkeleton(activeAnalysis, elements.activeSkeleton.value);
    const nextProfile = baseProfileForAnalysis(analysis, activeModel);
    nextProfile.transform = { ...characterProfile.transform, offset: [...characterProfile.transform.offset] };
    nextProfile.meshVisible = characterProfile.meshVisible;
    nextProfile.skeletonVisible = characterProfile.skeletonVisible;
    scene.attachModel(analysis, nextProfile, { disposePrevious: false });
    activeAnalysis = analysis;
    characterProfile = nextProfile;
    scene.applyCharacterPose(currentFrame);
    updateCharacterUI();
    setProfileDirty(true, "Selected a different skeleton and created a fresh Core27 auto-map.");
  } catch (error) {
    setDiagnostic("Skeleton change failed", error.message, true);
  }
});

elements.autoMap.addEventListener("click", () => autoMapCharacter());
elements.clearMap.addEventListener("click", () => {
  if (!characterProfile) return;
  characterProfile = {
    ...characterProfile,
    boneMap: Object.fromEntries(CORE27_JOINTS.map((joint) => [joint, null])),
  };
  applyCharacterProfile({ dirty: true, rebuildRows: true });
});
elements.characterJoint.addEventListener("change", syncSelectedJointControls);
elements.targetBone.addEventListener("change", () => {
  applyBoneMapping(elements.characterJoint.value, elements.targetBone.value || null);
});

function readCharacterTransform() {
  if (!characterProfile) return;
  characterProfile = {
    ...characterProfile,
    transform: {
      scale: elements.characterScale.value,
      yawDegrees: elements.characterYaw.value,
      pitchDegrees: elements.characterPitch.value,
      rollDegrees: elements.characterRoll.value,
      offset: elements.characterOffsets.map((input) => input.value),
    },
    rootMotion: elements.rootMotion.checked,
    meshVisible: elements.characterMeshVisible.checked,
    skeletonVisible: elements.characterSkeletonVisible.checked,
  };
  applyCharacterProfile({ dirty: true, resetRootAnchor: true });
}

for (const input of [
  elements.characterScale,
  elements.characterYaw,
  elements.characterPitch,
  elements.characterRoll,
  ...elements.characterOffsets,
  elements.rootMotion,
]) {
  input.addEventListener("input", readCharacterTransform);
}
elements.characterMeshVisible.addEventListener("change", () => {
  if (!characterProfile) return;
  characterProfile.meshVisible = elements.characterMeshVisible.checked;
  applyCharacterProfile({ dirty: true });
});
elements.characterSkeletonVisible.addEventListener("change", () => {
  if (!characterProfile) return;
  characterProfile.skeletonVisible = elements.characterSkeletonVisible.checked;
  applyCharacterProfile({ dirty: true });
});
for (const input of elements.rotationOffsets) {
  input.addEventListener("input", () => {
    const joint = elements.characterJoint.value;
    if (!characterProfile || !CORE27_JOINTS.includes(joint)) return;
    characterProfile = {
      ...characterProfile,
      rotationOffsetsDegrees: {
        ...characterProfile.rotationOffsetsDegrees,
        [joint]: elements.rotationOffsets.map((entry) => entry.value),
      },
    };
    applyCharacterProfile({ dirty: true });
  });
}
elements.resetRotation.addEventListener("click", () => {
  const joint = elements.characterJoint.value;
  if (!characterProfile || !CORE27_JOINTS.includes(joint)) return;
  characterProfile.rotationOffsetsDegrees[joint] = [0, 0, 0];
  applyCharacterProfile({ dirty: true });
});
elements.autoFit.addEventListener("click", () => {
  if (!characterProfile) return;
  const scale = scene.suggestCharacterScale(1.72);
  if (!Number.isFinite(scale)) return;
  characterProfile.transform.scale = scale;
  applyCharacterProfile({ dirty: true });
  scene.focusCharacter();
});
elements.resetCharacterTransform.addEventListener("click", () => {
  if (!characterProfile) return;
  characterProfile.transform = defaultCharacterProfile().transform;
  characterProfile.rootMotion = false;
  applyCharacterProfile({ dirty: true, resetRootAnchor: true });
  scene.focusCharacter();
});
elements.profileName.addEventListener("input", () => {
  if (!characterProfile) return;
  characterProfile.name = elements.profileName.value;
  setProfileDirty(true);
});
elements.saveProfile.addEventListener("click", saveCurrentProfile);
elements.reloadProfile.addEventListener("click", reloadCurrentProfile);
elements.exportProfile.addEventListener("click", exportCurrentProfile);
elements.importProfile.addEventListener("change", () => importCharacterProfile(elements.importProfile.files[0]));

for (const input of [
  elements.rigScale,
  elements.rigYaw,
  elements.mirrorX,
  ...elements.rigOffsets,
  ...elements.jointOffsets,
]) {
  input.addEventListener("input", readOverlayMapping);
}
elements.jointSelect.addEventListener("change", () => {
  scene.setSelectedJoint(elements.jointSelect.value);
  writeOverlayInputs(true);
});
elements.resetJoint.addEventListener("click", () => {
  overlayMapping.jointOffsetsCm[elements.jointSelect.value] = [0, 0, 0];
  overlayMapping = sanitizeRigMapping(overlayMapping);
  writeOverlayInputs(true);
  scene.updatePose(currentFrame.positions, overlayMapping);
});
elements.resetRig.addEventListener("click", () => {
  overlayMapping = defaultRigMapping();
  writeOverlayInputs(true);
  scene.updatePose(currentFrame.positions, overlayMapping);
});

for (const input of document.querySelectorAll("[data-component]")) {
  input.addEventListener("change", () => {
    visibleComponents[input.dataset.component] = input.checked;
    scene.setComponentVisible(input.dataset.component, input.checked);
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "f" || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  event.preventDefault();
  if (document.fullscreenElement) document.exitFullscreen();
  else document.querySelector("#app").requestFullscreen();
});

let lastTime = performance.now();
function update(deltaSeconds) {
  poseStream.update(deltaSeconds);
  currentFrame = poseStream.sampleFrame();
  scene.updatePose(currentFrame.positions, overlayMapping);
  scene.applyCharacterPose(currentFrame);
  scene.render();
}

function animate(now) {
  const delta = Math.min(0.1, Math.max(0, (now - lastTime) / 1000));
  lastTime = now;
  update(delta);
  requestAnimationFrame(animate);
}

window.advanceTime = (milliseconds) => {
  update(Math.max(0, Number(milliseconds) || 0) / 1000);
};

window.render_game_to_text = () => {
  const profileSummary = characterProfileSummary(characterProfile || defaultCharacterProfile());
  return JSON.stringify({
    mode: poseStream.mode,
    coordinateSystem: "ARDY source: +X character-left, +Y up, +Z forward, metres",
    provider: {
      checked: providerHealth.checked,
      ready: providerHealth.ready,
      dynamicTextReady: providerHealth.dynamicTextReady,
      name: providerHealth.provider,
      detail: providerHealth.detail,
    },
    motion: poseStream.snapshot(),
    character: {
      state: modelState,
      modelId: activeModel?.id || null,
      modelName: activeModel?.name || activeAnalysis?.sourceName || null,
      format: activeAnalysis?.format || null,
      meshCount: activeAnalysis?.inventory?.meshes?.length || 0,
      skeletonCount: activeAnalysis?.inventory?.skeletonGroups?.length || 0,
      activeSkeletonId: activeAnalysis?.inventory?.activeSkeleton?.id || null,
      boneCount: activeBones().length,
      mappedJoints: profileSummary.mappedCount,
      missingRequired: profileSummary.missingRequired,
      rootMotion: characterProfile?.rootMotion === true,
      profileDirty,
    },
    sourceOverlay: {
      selectedJoint: elements.jointSelect.value,
      mapping: overlayMapping,
      visibleComponents,
      displayedRoot: currentFrame.positions[0],
    },
    sceneReferences: ["floor", "chair", "bed"],
    controls: "left drag orbit, right drag pan, wheel/pinch zoom, F fullscreen",
  });
};

window.addEventListener("resize", () => scene.resize());
updateCharacterUI();
refreshModelLibrary();
refreshHealth();
const healthTimer = window.setInterval(refreshHealth, 5000);
window.addEventListener("pagehide", () => {
  window.clearInterval(healthTimer);
  scene.removeModel();
}, { once: true });
requestAnimationFrame(animate);
