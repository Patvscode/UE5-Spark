import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  controlCompanion,
  getServices,
  getWorkspace,
  getWorkspaceFile,
  mutateWorkspace,
  normalizeWorkspace,
  validateWorkspaceDraft,
} from "../src/systemFilesApi.js";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const appSource = fs.readFileSync(path.join(testDirectory, "../src/App.jsx"), "utf8");
const panelSource = fs.readFileSync(path.join(testDirectory, "../src/SystemFilesPanel.jsx"), "utf8");

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

test("service client uses the bounded GET/POST contract", async () => {
  const calls = [];
  const fetchMock = async (url, options = {}) => {
    calls.push({ url, options });
    return response({
      schemaVersion: 1,
      enabled: true,
      targetState: "starting",
      services: [
        { id: "ardy", label: "ARDY", status: "running", detail: "ready", required: true },
      ],
      allowedActions: ["stop", "restart", "destroy"],
      message: "Start accepted.",
    }, options.method === "POST" ? 202 : 200);
  };

  const status = await getServices(fetchMock);
  const accepted = await controlCompanion("start", fetchMock);
  assert.equal(calls[0].url, "/api/services");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[1].url, "/api/services");
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[1].options.body), { action: "start" });
  assert.equal(status.targetState, "starting");
  assert.deepEqual(status.allowedActions, ["stop", "restart"]);
  assert.equal(accepted.components[0].status, "running");
  await assert.rejects(() => controlCompanion("destroy", fetchMock), /Unsupported/);
});

test("workspace client keeps file ids opaque and uses one isolated endpoint", async () => {
  const calls = [];
  const inventory = {
    schemaVersion: 1,
    workspaceId: "controller-config",
    workspacePath: "/private/controller-config",
    backupPath: "/private/backups",
    roots: [
      {
        id: "wardrobe-user",
        label: "Wardrobe overrides",
        path: "/private/wardrobe",
        description: "User-authored JSON",
        addAllowed: true,
        acceptedKind: "json",
      },
    ],
    files: [
      {
        id: "wardrobe-user/outfit",
        name: "outfit.json",
        path: "/private/wardrobe/outfit.json",
        rootId: "wardrobe-user",
        editable: true,
        deleteAllowed: false,
        apply: { effect: "live", target: "wardrobe", note: "Applies to the selected profile." },
      },
    ],
  };
  const fetchMock = async (url, options = {}) => {
    calls.push({ url, options });
    if (String(url).includes("?")) {
      return response({
        ...inventory.files[0],
        content: "{\n  \"preset\": \"casual\"\n}\n",
        revision: "sha256:one",
        valid: true,
        validationMessage: "Valid wardrobe override.",
      });
    }
    if (options.method === "POST") {
      return response({
        message: "Saved.",
        file: { ...inventory.files[0], content: "{}", revision: "sha256:two" },
        backup: { created: true, path: "/private/backups/outfit.json.bak" },
      });
    }
    return response(inventory);
  };

  const workspace = await getWorkspace(fetchMock);
  const file = await getWorkspaceFile("wardrobe-user/outfit", fetchMock);
  const saved = await mutateWorkspace("save", {
    fileId: file.id,
    revision: file.revision,
    content: file.content,
  }, fetchMock);
  await mutateWorkspace("create", {
    directoryId: "wardrobe-user",
    name: "second.json",
    content: "{}",
  }, fetchMock);

  assert.equal(workspace.directories[0].addable, true);
  assert.equal(workspace.files[0].applyMode, "live");
  assert.equal(workspace.files[0].removable, false);
  assert.match(calls[1].url, /^\/api\/workspace\?file=wardrobe-user%2Foutfit$/);
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    action: "save",
    fileId: "wardrobe-user/outfit",
    revision: "sha256:one",
    content: "{\n  \"preset\": \"casual\"\n}\n",
  });
  assert.deepEqual(JSON.parse(calls[3].options.body), {
    action: "create",
    directoryId: "wardrobe-user",
    name: "second.json",
    content: "{}",
  });
  assert.equal(saved.backup.created, true);
});

test("workspace normalization protects built-ins and exposes apply impact", () => {
  const workspace = normalizeWorkspace({
    roots: [{ id: "config", label: "Config", path: "/config", addAllowed: false }],
    files: [
      {
        id: "built-in",
        name: "character.json",
        path: "/config/character.json",
        rootId: "config",
        deleteAllowed: true,
        builtIn: true,
        apply: { effect: "rebuild" },
      },
    ],
  });
  assert.equal(workspace.directories[0].addable, false);
  assert.equal(workspace.files[0].removable, false);
  assert.equal(workspace.files[0].builtIn, true);
  assert.equal(workspace.files[0].applyMode, "rebuild");
});

test("editor validates JSON and bounded text before save", () => {
  const file = { path: "/config/profile.json" };
  assert.equal(validateWorkspaceDraft(file, '{"enabled":true}').valid, true);
  assert.equal(validateWorkspaceDraft(file, '{"enabled":').valid, false);
  assert.equal(validateWorkspaceDraft({ path: "/config/notes.md" }, "# Notes").valid, true);
  assert.equal(validateWorkspaceDraft(file, "").valid, false);
});

test("system controls stay in the settings sheet and poll while open", () => {
  const rail = appSource.slice(
    appSource.indexOf('className="companion-rail"'),
    appSource.indexOf("</nav>", appSource.indexOf('className="companion-rail"')),
  );
  assert.doesNotMatch(rail, /SystemFilesPanel|System & files|HardDrives/);
  assert.match(appSource, /className="system-files-launch"/);
  assert.match(appSource, /activeSheet === "system"/);
  assert.match(panelSource, /setInterval\([\s\S]*2500/);
  assert.match(panelSource, /Start companion/);
  assert.match(panelSource, /Save with backup/);
  assert.match(panelSource, /Built-in file · removal is protected/);
  assert.match(panelSource, /IMPACT_LABELS/);
  assert.match(panelSource, /IMPACT_NOTES/);
});
