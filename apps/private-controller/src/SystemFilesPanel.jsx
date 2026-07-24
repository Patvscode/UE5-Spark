import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise, CaretLeft, CheckCircle, CircleNotch, FilePlus, FileText,
  FloppyDisk, FolderOpen, HardDrives, Plus, Power, Stop, Trash, WarningCircle,
} from "@phosphor-icons/react";
import {
  controlCompanion,
  getServices,
  getWorkspace,
  getWorkspaceFile,
  mutateWorkspace,
  validateWorkspaceDraft,
} from "./systemFilesApi.js";

const EMPTY_SERVICES = {
  loaded: false,
  enabled: false,
  targetState: "unknown",
  components: [],
  allowedActions: [],
  message: "",
};

const EMPTY_WORKSPACE = {
  loaded: false,
  directories: [],
  files: [],
  options: {
    characters: [],
    motionPresets: [],
    aiControlModes: [],
    wardrobeProfiles: [],
  },
  guidance: [],
  message: "",
};

const IMPACT_LABELS = {
  live: "Applies live",
  restart: "Companion restart",
  rebuild: "Unreal rebuild",
};

const IMPACT_NOTES = {
  live: "Validated changes apply live.",
  restart: "Restart the companion to apply validated changes.",
  rebuild: "A new Unreal package build is required.",
};

function serviceStateLabel(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

function wardrobeProfileCopy(name, sourceText) {
  const source = JSON.parse(sourceText);
  let profileId = name.replace(/\.json$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
  if (!/^[a-z]/.test(profileId)) profileId = `profile-${profileId}`.slice(0, 32);
  source.id = profileId || "new-profile";
  source.status = "pending_asset_audit";
  source.allowFullyUnclothed = false;
  return `${JSON.stringify(source, null, 2)}\n`;
}

export function SystemFilesPanel({ onBack, onStageNotice }) {
  const [services, setServices] = useState(EMPTY_SERVICES);
  const [servicesBusy, setServicesBusy] = useState(false);
  const [servicesError, setServicesError] = useState("");
  const [workspace, setWorkspace] = useState(EMPTY_WORKSPACE);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [draft, setDraft] = useState("");
  const [savedDraft, setSavedDraft] = useState("");
  const [fileBusy, setFileBusy] = useState(false);
  const [workspaceNotice, setWorkspaceNotice] = useState("");
  const [showAddFile, setShowAddFile] = useState(false);
  const [newFile, setNewFile] = useState({ directoryId: "", name: "" });

  const dirty = Boolean(selectedFile) && draft !== savedDraft;
  const draftValidation = useMemo(
    () => selectedFile ? validateWorkspaceDraft(selectedFile, draft) : null,
    [draft, selectedFile],
  );

  const refreshServices = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setServicesBusy(true);
    if (!silent) setServicesError("");
    try {
      setServices(await getServices());
    } catch (error) {
      if (!silent) {
        setServices(EMPTY_SERVICES);
        setServicesError(error.message || "Service control is unavailable.");
      }
    } finally {
      if (!silent) setServicesBusy(false);
    }
  }, []);

  const refreshWorkspace = useCallback(async () => {
    setWorkspaceBusy(true);
    setWorkspaceError("");
    try {
      const next = await getWorkspace();
      setWorkspace(next);
      setNewFile((current) => ({
        ...current,
        directoryId: next.directories.some((item) => item.id === current.directoryId)
          ? current.directoryId
          : next.directories.find((item) => item.addable)?.id || "",
      }));
    } catch (error) {
      setWorkspace(EMPTY_WORKSPACE);
      setWorkspaceError(error.message || "The file workspace is unavailable.");
    } finally {
      setWorkspaceBusy(false);
    }
  }, []);

  useEffect(() => {
    refreshServices();
    refreshWorkspace();
    const serviceTimer = window.setInterval(
      () => refreshServices({ silent: true }),
      2500,
    );
    return () => window.clearInterval(serviceTimer);
  }, [refreshServices, refreshWorkspace]);

  async function runServiceAction(action) {
    setServicesBusy(true);
    setServicesError("");
    try {
      const next = await controlCompanion(action);
      setServices(next);
      const message = next.message || (
        action === "start" ? "Companion start requested."
          : action === "stop" ? "Companion stop requested."
            : "Companion state refreshed."
      );
      onStageNotice?.(message);
      getServices().then(setServices).catch(() => {
        /* The 2.5 second panel poll will retry without masking an accepted action. */
      });
    } catch (error) {
      setServicesError(error.message || `Could not ${action} the companion.`);
    } finally {
      setServicesBusy(false);
    }
  }

  async function chooseFile(summary) {
    if (dirty && !window.confirm("Discard the unsaved editor changes?")) return;
    setFileBusy(true);
    setWorkspaceError("");
    setWorkspaceNotice("");
    try {
      const file = await getWorkspaceFile(summary.id);
      setSelectedFile(file);
      setDraft(file.content);
      setSavedDraft(file.content);
      if (file.validation?.valid === false) {
        setWorkspaceNotice(file.validation.message || "This file needs attention before it can be applied.");
      }
    } catch (error) {
      setWorkspaceError(error.message || "The file could not be opened.");
    } finally {
      setFileBusy(false);
    }
  }

  async function saveFile() {
    if (!selectedFile || !draftValidation?.valid || !dirty) return;
    setFileBusy(true);
    setWorkspaceError("");
    setWorkspaceNotice("");
    try {
      const result = await mutateWorkspace("save", {
        fileId: selectedFile.id,
        revision: selectedFile.revision,
        content: draft,
      });
      if (result.validation.valid === false) {
        setWorkspaceNotice(result.validation.message || "Spark rejected this file during validation.");
        return;
      }
      const updated = result.file || { ...selectedFile, content: draft };
      setSelectedFile(updated);
      setDraft(updated.content || draft);
      setSavedDraft(updated.content || draft);
      const backupMessage = result.backup?.created
        ? ` Backup created${result.backup.path ? ` at ${result.backup.path}` : ""}.`
        : " Spark did not report a backup; verify before relying on this save.";
      setWorkspaceNotice(`${result.message || "Saved."}${backupMessage}`);
      if (result.workspace) setWorkspace(result.workspace);
      else await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(error.message || "The file was not saved.");
    } finally {
      setFileBusy(false);
    }
  }

  async function createFile(event) {
    event.preventDefault();
    const name = newFile.name.trim();
    if (
      !newFile.directoryId
      || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$/.test(name)
      || name.includes("..")
    ) {
      setWorkspaceError("Use a simple file name without folders or “..”.");
      return;
    }
    setFileBusy(true);
    setWorkspaceError("");
    setWorkspaceNotice("");
    try {
      const templateSummary = workspace.files.find(
        (item) => item.directoryId === newFile.directoryId && item.name.endsWith(".json"),
      );
      if (!templateSummary) {
        throw new Error("A reviewed wardrobe profile is required as a starting point.");
      }
      const templateFile = await getWorkspaceFile(templateSummary.id);
      const result = await mutateWorkspace("create", {
        directoryId: newFile.directoryId,
        name,
        content: wardrobeProfileCopy(name, templateFile.content),
      });
      setWorkspaceNotice(result.message || `${name} created.`);
      setShowAddFile(false);
      setNewFile((current) => ({ ...current, name: "" }));
      if (result.workspace) setWorkspace(result.workspace);
      else await refreshWorkspace();
      if (result.file) {
        setSelectedFile(result.file);
        setDraft(result.file.content);
        setSavedDraft(result.file.content);
      }
    } catch (error) {
      setWorkspaceError(error.message || "The file was not created.");
    } finally {
      setFileBusy(false);
    }
  }

  async function removeFile() {
    if (!selectedFile?.removable) return;
    if (!window.confirm(`Remove ${selectedFile.name}? The Spark must retain a recoverable backup.`)) return;
    setFileBusy(true);
    setWorkspaceError("");
    setWorkspaceNotice("");
    try {
      const result = await mutateWorkspace("delete", {
        fileId: selectedFile.id,
        revision: selectedFile.revision,
      });
      const backupMessage = result.backup?.created
        ? ` Recoverable backup created${result.backup.path ? ` at ${result.backup.path}` : ""}.`
        : "";
      setWorkspaceNotice(`${result.message || `${selectedFile.name} removed.`}${backupMessage}`);
      setSelectedFile(null);
      setDraft("");
      setSavedDraft("");
      if (result.workspace) setWorkspace(result.workspace);
      else await refreshWorkspace();
    } catch (error) {
      setWorkspaceError(error.message || "The file was not removed.");
    } finally {
      setFileBusy(false);
    }
  }

  const canStart = services.enabled && services.allowedActions.includes("start");
  const canStop = services.enabled && services.allowedActions.includes("stop");

  return (
    <div className="system-files-content">
      <button className="system-back" onClick={onBack} type="button">
        <CaretLeft size={16} weight="bold" /> Back to stage setup
      </button>

      <section className="utility-card services-card" aria-labelledby="system-services-heading">
        <div className="utility-heading">
          <span>
            <HardDrives size={19} weight="regular" />
            <span><strong id="system-services-heading">System services</strong><small>DGX Spark companion stack</small></span>
          </span>
          <button onClick={() => refreshServices()} type="button" disabled={servicesBusy} aria-label="Refresh service status">
            <ArrowClockwise className={servicesBusy ? "spin" : ""} size={17} />
          </button>
        </div>

        <div className="service-summary">
          <span className={`service-state state-${services.targetState}`}>
            <span aria-hidden="true" /> {services.loaded ? serviceStateLabel(services.targetState) : "Not connected"}
          </span>
          <div className="service-controls">
            <button className="service-start" onClick={() => runServiceAction("start")} type="button" disabled={!canStart || servicesBusy}>
              {servicesBusy ? <CircleNotch className="spin" size={17} /> : <Power size={17} weight="bold" />}
              Start companion
            </button>
            <button className="service-stop" onClick={() => runServiceAction("stop")} type="button" disabled={!canStop || servicesBusy}>
              <Stop size={16} weight="fill" /> Stop companion
            </button>
          </div>
        </div>

        {services.components.length > 0 && (
          <ul className="service-list" aria-label="Service status">
            {services.components.map((service) => (
              <li key={service.id}>
                <span className={`component-dot state-${service.status}`} aria-hidden="true" />
                <span><strong>{service.label}</strong><small>{service.detail || serviceStateLabel(service.status)}</small></span>
                <em>{serviceStateLabel(service.status)}</em>
              </li>
            ))}
          </ul>
        )}
        {servicesError && <p className="utility-error" role="alert"><WarningCircle size={15} />{servicesError}</p>}
      </section>

      <section className="utility-card workspace-card" aria-labelledby="file-workspace-heading">
        <div className="utility-heading">
          <span>
            <FolderOpen size={19} weight="regular" />
            <span><strong id="file-workspace-heading">Configuration & wardrobe</strong><small>Reviewed local files only</small></span>
          </span>
          <button onClick={refreshWorkspace} type="button" disabled={workspaceBusy || fileBusy} aria-label="Refresh file workspace">
            <ArrowClockwise className={workspaceBusy ? "spin" : ""} size={17} />
          </button>
        </div>

        {workspace.directories.length > 0 && (
          <div className="workspace-directories" aria-label="Documented directories">
            {workspace.directories.map((directory) => (
              <div key={directory.id}>
                <span>{directory.label}</span>
                <code title={directory.path}>{directory.path}</code>
                {directory.description && <small>{directory.description}</small>}
              </div>
            ))}
          </div>
        )}

        {workspace.loaded && (
          <details className="workspace-options">
            <summary>Available project options</summary>
            <div className="workspace-option-grid">
              <div><strong>Characters</strong><p>{workspace.options.characters.join(" · ") || "None reported"}</p></div>
              <div><strong>AI modes</strong><p>{workspace.options.aiControlModes.join(" · ") || "None reported"}</p></div>
              <div><strong>Motion presets</strong><p>{workspace.options.motionPresets.join(" · ") || "None reported"}</p></div>
              <div>
                <strong>Wardrobe profiles</strong>
                {workspace.options.wardrobeProfiles.length ? workspace.options.wardrobeProfiles.map((profile) => (
                  <p key={profile.profileId}>
                    {profile.profileId} · {profile.status} · {profile.presets.join(", ") || "no presets"}
                  </p>
                )) : <p>None reported</p>}
              </div>
            </div>
          </details>
        )}

        <div className="workspace-toolbar">
          <span>{workspace.loaded ? `${workspace.files.length} reviewed files` : "Workspace not connected"}</span>
          <button onClick={() => setShowAddFile((value) => !value)} type="button" disabled={!workspace.directories.some((item) => item.addable) || fileBusy}>
            <Plus size={15} weight="bold" /> Add file
          </button>
        </div>

        {showAddFile && (
          <form className="add-file-form" onSubmit={createFile}>
            <label>
              Directory
              <select value={newFile.directoryId} onChange={(event) => setNewFile((current) => ({ ...current, directoryId: event.target.value }))}>
                {workspace.directories.filter((item) => item.addable).map((directory) => (
                  <option key={directory.id} value={directory.id}>{directory.label}</option>
                ))}
              </select>
            </label>
            <label>
              File name
              <input value={newFile.name} onChange={(event) => setNewFile((current) => ({ ...current, name: event.target.value }))} placeholder="new-profile.json" maxLength={96} autoComplete="off" />
            </label>
            <small>A valid copy of the current wardrobe profile is created. Open it below to change its IDs, listing, slots, and presets.</small>
            <button type="submit" disabled={fileBusy || !newFile.name.trim()}><FilePlus size={16} /> Create</button>
          </form>
        )}

        <div className="workspace-layout">
          <div className="workspace-file-list" role="list" aria-label="Workspace files">
            {workspace.files.map((file) => (
              <button className={selectedFile?.id === file.id ? "is-selected" : ""} key={file.id} onClick={() => chooseFile(file)} type="button" role="listitem" disabled={fileBusy}>
                <FileText size={17} weight="regular" />
                <span>
                  <strong>{file.name}</strong>
                  <small>{file.path}</small>
                  <small className="file-impact-note">{file.applyNote || IMPACT_NOTES[file.applyMode]}</small>
                </span>
                <em className={`impact impact-${file.applyMode}`}>{IMPACT_LABELS[file.applyMode]}</em>
              </button>
            ))}
            {workspace.loaded && workspace.files.length === 0 && (
              <p className="workspace-empty">No reviewed editable files were returned by the Spark.</p>
            )}
          </div>

          {selectedFile && (
            <div className="workspace-editor">
              <div className="editor-heading">
                <span><strong>{selectedFile.name}</strong><code>{selectedFile.path}</code></span>
                <em className={`impact impact-${selectedFile.applyMode}`}>{IMPACT_LABELS[selectedFile.applyMode]}</em>
              </div>
              <p className="editor-impact-note">{selectedFile.applyNote || IMPACT_NOTES[selectedFile.applyMode]}</p>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                readOnly={!selectedFile.editable}
                spellCheck="false"
                aria-label={`Edit ${selectedFile.name}`}
              />
              <div className={`editor-validation ${draftValidation?.valid ? "is-valid" : "is-invalid"}`} aria-live="polite">
                {draftValidation?.valid ? <CheckCircle size={15} weight="fill" /> : <WarningCircle size={15} weight="fill" />}
                <span>{draftValidation?.message}</span>
              </div>
              <div className="editor-actions">
                <button className="editor-save" onClick={saveFile} type="button" disabled={!selectedFile.editable || !dirty || !draftValidation?.valid || fileBusy}>
                  {fileBusy ? <CircleNotch className="spin" size={16} /> : <FloppyDisk size={16} weight="bold" />} Save with backup
                </button>
                <button className="editor-remove" onClick={removeFile} type="button" disabled={!selectedFile.removable || fileBusy} title={selectedFile.removable ? "Remove this user-created file" : "Built-in files cannot be removed"}>
                  <Trash size={16} /> Remove
                </button>
              </div>
              {!selectedFile.removable && (
                <small className="built-in-note">
                  {selectedFile.builtIn ? "Built-in file · removal is protected." : "Removal is disabled for this reviewed file."}
                </small>
              )}
            </div>
          )}
        </div>

        {fileBusy && <div className="workspace-loading" role="status"><CircleNotch className="spin" size={17} /> Working on the Spark…</div>}
        {workspaceNotice && <p className="utility-notice" role="status">{workspaceNotice}</p>}
        {workspaceError && <p className="utility-error" role="alert"><WarningCircle size={15} />{workspaceError}</p>}
        {workspace.guidance.length > 0 && (
          <ul className="workspace-guidance" aria-label="How configuration changes work">
            {workspace.guidance.map((item) => <li key={item}>{item}</li>)}
          </ul>
        )}
      </section>
    </div>
  );
}
