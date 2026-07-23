export const SYSTEM_FILES_ENDPOINTS = Object.freeze({
  services: "/api/services",
  workspace: "/api/workspace",
});

export const SERVICE_ACTIONS = Object.freeze(["start", "stop", "restart", "status"]);
export const WORKSPACE_ACTIONS = Object.freeze(["save", "create", "delete"]);
export const WORKSPACE_CONTENT_LIMIT = 256 * 1024;

const APPLY_MODES = new Set(["live", "restart", "rebuild"]);
const SERVICE_STATES = new Set(["running", "starting", "stopping", "stopped", "failed", "unavailable", "unknown"]);

function asBoundedString(value, fallback = "", maximum = 240) {
  if (typeof value !== "string") return fallback;
  return value.trim().slice(0, maximum);
}

function asOpaqueId(value) {
  return asBoundedString(value, "", 160);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

async function responsePayload(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      asBoundedString(payload?.detail || payload?.error || payload?.message, "Request was not accepted.", 300),
    );
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export function normalizeServices(payload) {
  const allowedActions = asArray(payload?.allowedActions)
    .filter((action) => SERVICE_ACTIONS.includes(action));
  const components = asArray(payload?.components || payload?.services)
    .slice(0, 16)
    .map((component) => {
      const status = SERVICE_STATES.has(component?.status) ? component.status : "unknown";
      return {
        id: asOpaqueId(component?.id || component?.name),
        label: asBoundedString(component?.label || component?.name, "Service", 48),
        status,
        detail: asBoundedString(component?.detail, "", 140),
        required: component?.required !== false,
      };
    })
    .filter((component) => component.id);

  const targetState = SERVICE_STATES.has(payload?.targetState)
    ? payload.targetState
    : "unknown";

  return {
    schemaVersion: Number(payload?.schemaVersion) || 1,
    loaded: true,
    enabled: payload?.enabled !== false,
    targetState,
    components,
    allowedActions,
    message: asBoundedString(payload?.message, "", 240),
  };
}

export function normalizeWorkspace(payload) {
  const directories = asArray(payload?.directories || payload?.roots)
    .slice(0, 16)
    .map((directory) => {
      const addable = typeof directory?.addAllowed === "boolean"
        ? directory.addAllowed
        : directory?.addable === true;
      return {
        id: asOpaqueId(directory?.id || directory?.rootId),
        label: asBoundedString(directory?.label || directory?.name, "Directory", 48),
        path: asBoundedString(directory?.path, "", 220),
        description: asBoundedString(directory?.description, "", 140),
        addable,
        acceptedKind: asBoundedString(directory?.acceptedKind, "", 40),
      };
    })
    .filter((directory) => directory.id && directory.path);

  const files = asArray(payload?.files)
    .slice(0, 200)
    .map((file) => normalizeWorkspaceFile(file))
    .filter((file) => file.id && file.path);

  const options = payload?.options && typeof payload.options === "object"
    ? payload.options
    : {};
  const normalizeOptionList = (value) => asArray(value)
    .slice(0, 100)
    .map((item) => asBoundedString(item, "", 64))
    .filter(Boolean);
  const wardrobeProfiles = asArray(options.wardrobeProfiles)
    .slice(0, 64)
    .map((profile) => ({
      profileId: asOpaqueId(profile?.profileId),
      status: asBoundedString(profile?.status, "unknown", 40),
      presets: normalizeOptionList(profile?.presets),
      slots: profile?.slots && typeof profile.slots === "object"
        ? Object.fromEntries(
          Object.entries(profile.slots)
            .slice(0, 12)
            .map(([key, values]) => [
              asBoundedString(key, "", 32),
              normalizeOptionList(values),
            ])
            .filter(([key]) => key),
        )
        : {},
    }))
    .filter((profile) => profile.profileId);
  const guidance = asArray(payload?.guidance)
    .slice(0, 8)
    .map((item) => asBoundedString(item, "", 300))
    .filter(Boolean);

  return {
    schemaVersion: Number(payload?.schemaVersion) || 1,
    loaded: true,
    workspaceId: asOpaqueId(payload?.workspaceId),
    workspacePath: asBoundedString(payload?.workspacePath, "", 240),
    backupPath: asBoundedString(payload?.backupPath, "", 240),
    directories,
    files,
    options: {
      characters: normalizeOptionList(options.characters),
      motionPresets: normalizeOptionList(options.motionPresets),
      aiControlModes: normalizeOptionList(options.aiControlModes),
      wardrobeProfiles,
    },
    guidance,
    message: asBoundedString(payload?.message, "", 240),
  };
}

export function normalizeWorkspaceFile(file) {
  const applyCandidate = file?.applyMode || file?.impact || file?.apply?.effect;
  const applyMode = APPLY_MODES.has(applyCandidate)
    ? applyCandidate
    : "restart";
  const deleteAllowed = typeof file?.deleteAllowed === "boolean"
    ? file.deleteAllowed
    : file?.removable === true;
  const builtIn = file?.builtIn === true;
  return {
    id: asOpaqueId(file?.id || file?.fileId),
    directoryId: asOpaqueId(file?.directoryId || file?.rootId),
    name: asBoundedString(file?.name, "Untitled", 96),
    path: asBoundedString(file?.path, "", 240),
    kind: asBoundedString(file?.kind, "text", 32),
    editable: file?.editable !== false,
    removable: deleteAllowed && !builtIn,
    builtIn,
    applyMode,
    applyTarget: asBoundedString(file?.applyTarget || file?.apply?.target, "", 80),
    applyNote: asBoundedString(file?.applyNote || file?.apply?.note, "", 180),
    modifiedAt: asBoundedString(file?.modifiedAt || file?.updatedAt, "", 64),
    content: typeof file?.content === "string"
      ? file.content.slice(0, WORKSPACE_CONTENT_LIMIT)
      : "",
    revision: asBoundedString(file?.revision, "", 160),
    validation: normalizeValidation(file?.validation, file?.valid, file?.validationMessage),
  };
}

export function normalizeValidation(validation, valid, message) {
  const source = validation && typeof validation === "object" ? validation : {};
  const explicitValid = typeof source.valid === "boolean"
    ? source.valid
    : typeof valid === "boolean" ? valid : null;
  return {
    valid: explicitValid,
    message: asBoundedString(source.message || message, "", 240),
    errors: asArray(source.errors)
      .slice(0, 8)
      .map((entry) => asBoundedString(
        typeof entry === "string" ? entry : entry?.message,
        "",
        180,
      ))
      .filter(Boolean),
  };
}

export function validateWorkspaceDraft(file, content) {
  if (typeof content !== "string") {
    return { valid: false, message: "File content must be text." };
  }
  const bytes = new TextEncoder().encode(content).byteLength;
  if (bytes > WORKSPACE_CONTENT_LIMIT) {
    return { valid: false, message: `File exceeds the ${WORKSPACE_CONTENT_LIMIT / 1024} KB editor limit.` };
  }
  if (!content.trim()) {
    return { valid: false, message: "File cannot be empty." };
  }

  const path = String(file?.path || file?.name || "").toLowerCase();
  if (path.endsWith(".json")) {
    try {
      JSON.parse(content);
      return { valid: true, message: "Valid JSON · Spark validates the file schema before saving." };
    } catch (error) {
      const detail = String(error?.message || "Invalid JSON").slice(0, 160);
      return { valid: false, message: detail };
    }
  }

  return { valid: true, message: "Text is within limits · Spark validates the file before saving." };
}

export async function getServices(fetchImpl = fetch) {
  const response = await fetchImpl(SYSTEM_FILES_ENDPOINTS.services, { cache: "no-store" });
  return normalizeServices(await responsePayload(response));
}

export async function controlCompanion(action, fetchImpl = fetch) {
  if (!SERVICE_ACTIONS.includes(action)) throw new Error("Unsupported companion action.");
  const response = await fetchImpl(SYSTEM_FILES_ENDPOINTS.services, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return normalizeServices(await responsePayload(response));
}

export async function getWorkspace(fetchImpl = fetch) {
  const response = await fetchImpl(SYSTEM_FILES_ENDPOINTS.workspace, { cache: "no-store" });
  return normalizeWorkspace(await responsePayload(response));
}

export async function getWorkspaceFile(fileId, fetchImpl = fetch) {
  const id = asOpaqueId(fileId);
  if (!id) throw new Error("Choose a workspace file first.");
  const query = new URLSearchParams({ file: id });
  const response = await fetchImpl(`${SYSTEM_FILES_ENDPOINTS.workspace}?${query}`, {
    cache: "no-store",
  });
  return normalizeWorkspaceFile(await responsePayload(response));
}

export async function mutateWorkspace(action, values, fetchImpl = fetch) {
  if (!WORKSPACE_ACTIONS.includes(action)) throw new Error("Unsupported workspace action.");
  const response = await fetchImpl(SYSTEM_FILES_ENDPOINTS.workspace, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...values }),
  });
  const payload = await responsePayload(response);
  return {
    message: asBoundedString(payload?.message, "", 240),
    file: payload?.file ? normalizeWorkspaceFile(payload.file) : null,
    workspace: payload?.workspace ? normalizeWorkspace(payload.workspace) : null,
    validation: normalizeValidation(payload?.validation),
    backup: payload?.backup && typeof payload.backup === "object"
      ? {
          created: payload.backup.created === true,
          path: asBoundedString(payload.backup.path, "", 240),
        }
      : null,
  };
}
