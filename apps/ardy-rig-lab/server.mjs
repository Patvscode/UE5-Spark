import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  CHARACTER_PROFILE_VERSION,
  sanitizeCharacterProfile,
} from "./src/characterProfile.js";

const APP_ROOT = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DIST = path.join(APP_ROOT, "dist");
const DEFAULT_DATA_ROOT = path.join(APP_ROOT, "data-private");
const MAX_REQUEST_BYTES = 8 * 1024;
const MAX_PROFILE_BYTES = 512 * 1024;
const MAX_MODEL_BYTES = 512 * 1024 * 1024;
const MAX_UPSTREAM_BYTES = 512 * 1024;
const MODEL_ID_PATTERN = /^[a-f0-9]{24}$/;
// Persist only single-file model formats. Multi-file GLTF remains available for
// a transient browser import where all sidecars can be selected together.
const MODEL_EXTENSIONS = new Set([".fbx", ".glb", ".vrm"]);
const BEHAVIORS = new Set([
  "idle", "listen", "explain", "wave", "jog_in_place", "run_in_place",
  "jumping_jacks", "stretch", "dance_relaxed",
]);
const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".fbx": "application/octet-stream",
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".vrm": "model/gltf-binary",
  ".webp": "image/webp",
};

function json(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
  });
  response.end(body);
}

function securityHeaders(response) {
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");
  response.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' blob:; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
  );
}

function safeNumber(value, minimum, maximum, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${label} is outside the supported range`);
  }
  return value;
}

export function validatePoseRequest(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("pose request must be a JSON object");
  }
  const allowed = new Set(["behavior", "prompt", "intensity", "duration", "afterSequence"]);
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    throw new Error("pose request contains unsupported fields");
  }
  if (!BEHAVIORS.has(value.behavior)) throw new Error("behavior is not supported by this lab");
  if (!Number.isSafeInteger(value.afterSequence) || value.afterSequence < 0) {
    throw new Error("afterSequence must be a non-negative integer");
  }
  const result = {
    behavior: value.behavior,
    intensity: safeNumber(value.intensity, 0, 1, "intensity"),
    duration: safeNumber(value.duration, 0.2, 10, "duration"),
    afterSequence: value.afterSequence,
  };
  if (value.prompt !== undefined) {
    if (typeof value.prompt !== "string") throw new Error("prompt must be text");
    const prompt = value.prompt.trim();
    if (prompt.length < 1 || prompt.length > 512) {
      throw new Error("prompt must contain 1 to 512 characters");
    }
    result.prompt = prompt;
  }
  return result;
}

export function validateUpstreamUrl(value) {
  const url = new URL(value);
  if (
    url.protocol !== "http:"
    || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    || (url.pathname !== "/" && url.pathname !== "")
    || url.search
    || url.hash
  ) {
    throw new Error("ARDY Rig Lab upstream must be a loopback HTTP origin");
  }
  return url.origin;
}

async function readJsonRequest(request, maximumBytes = MAX_REQUEST_BYTES) {
  const contentType = String(request.headers["content-type"] || "").split(";", 1)[0].trim();
  if (contentType !== "application/json") throw new Error("Content-Type must be application/json");
  const declared = Number(request.headers["content-length"]);
  if (!Number.isSafeInteger(declared) || declared < 1 || declared > maximumBytes) {
    throw new Error("request body size is outside the supported range");
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maximumBytes) throw new Error("request body is too large");
    chunks.push(chunk);
  }
  if (size !== declared) throw new Error("request body length did not match Content-Length");
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function prepareDataRoot(value) {
  const root = path.resolve(value || DEFAULT_DATA_ROOT);
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  if (fs.lstatSync(root).isSymbolicLink()) {
    throw new Error("RIG_LAB_DATA_ROOT must not be a symbolic link");
  }
  const reviewed = fs.realpathSync(root);
  for (const directory of ["models", "metadata", "profiles"]) {
    fs.mkdirSync(path.join(reviewed, directory), { recursive: true, mode: 0o700 });
  }
  return reviewed;
}

function modelPaths(dataRoot, id, extension = "") {
  if (!MODEL_ID_PATTERN.test(id)) throw new Error("model id is invalid");
  return {
    metadata: path.join(dataRoot, "metadata", `${id}.json`),
    profile: path.join(dataRoot, "profiles", `${id}.json`),
    model: extension ? path.join(dataRoot, "models", `${id}${extension}`) : "",
  };
}

function readModelMetadata(dataRoot, id) {
  const metadataPath = modelPaths(dataRoot, id).metadata;
  if (!fs.existsSync(metadataPath)) return null;
  const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
  if (
    metadata?.id !== id
    || typeof metadata?.name !== "string"
    || !MODEL_EXTENSIONS.has(metadata?.extension)
    || !Number.isSafeInteger(metadata?.size)
  ) {
    throw new Error("stored model metadata is invalid");
  }
  return metadata;
}

function listModels(dataRoot) {
  const metadataDirectory = path.join(dataRoot, "metadata");
  const models = [];
  for (const entry of fs.readdirSync(metadataDirectory, { withFileTypes: true })) {
    if (!entry.isFile() || !MODEL_ID_PATTERN.test(path.basename(entry.name, ".json"))) continue;
    try {
      const id = path.basename(entry.name, ".json");
      const metadata = readModelMetadata(dataRoot, id);
      if (metadata && fs.existsSync(modelPaths(dataRoot, id, metadata.extension).model)) {
        models.push({
          ...metadata,
          hasProfile: fs.existsSync(modelPaths(dataRoot, id).profile),
          fileUrl: `/api/models/${id}/file`,
        });
      }
    } catch {
      // A malformed private entry is omitted rather than exposed to the browser.
    }
  }
  return models.sort((left, right) => String(right.uploadedAt).localeCompare(String(left.uploadedAt)));
}

function safeUploadName(value) {
  let decoded;
  try {
    decoded = decodeURIComponent(String(value || ""));
  } catch {
    throw new Error("model filename is invalid");
  }
  const basename = path.basename(decoded).trim();
  if (!basename || basename.length > 180 || basename !== decoded.trim()) {
    throw new Error("model filename is invalid");
  }
  const extension = path.extname(basename).toLowerCase();
  if (!MODEL_EXTENSIONS.has(extension)) {
    throw new Error("use a skinned GLB, VRM, or FBX model; multi-file GLTF can be opened locally");
  }
  return { name: basename, extension };
}

async function receiveModel(request, dataRoot) {
  const contentType = String(request.headers["content-type"] || "").split(";", 1)[0].trim();
  if (!["application/octet-stream", "model/gltf-binary", "model/gltf+json"].includes(contentType)) {
    throw new Error("model upload Content-Type is not supported");
  }
  const declared = Number(request.headers["content-length"]);
  if (!Number.isSafeInteger(declared) || declared < 16 || declared > MAX_MODEL_BYTES) {
    throw new Error("model file size is outside the supported range");
  }
  const { name, extension } = safeUploadName(request.headers["x-rig-model-name"]);
  const temporary = path.join(
    dataRoot,
    "models",
    `.upload-${process.pid}-${crypto.randomUUID()}${extension}`,
  );
  const output = fs.createWriteStream(temporary, { flags: "wx", mode: 0o600 });
  const hash = crypto.createHash("sha256");
  let received = 0;
  try {
    for await (const chunk of request) {
      received += chunk.length;
      if (received > MAX_MODEL_BYTES || received > declared) {
        throw new Error("model upload exceeded the declared size");
      }
      hash.update(chunk);
      if (!output.write(chunk)) {
        await new Promise((resolve) => output.once("drain", resolve));
      }
    }
    if (received !== declared) throw new Error("model upload length did not match Content-Length");
    await new Promise((resolve, reject) => output.end((error) => error ? reject(error) : resolve()));
  } catch (error) {
    output.destroy();
    fs.rmSync(temporary, { force: true });
    throw error;
  }

  const id = hash.digest("hex").slice(0, 24);
  const target = modelPaths(dataRoot, id, extension).model;
  if (fs.existsSync(target)) fs.rmSync(temporary, { force: true });
  else fs.renameSync(temporary, target);
  const metadata = {
    id,
    name,
    extension,
    size: received,
    uploadedAt: new Date().toISOString(),
  };
  fs.writeFileSync(
    modelPaths(dataRoot, id).metadata,
    `${JSON.stringify(metadata, null, 2)}\n`,
    { mode: 0o600 },
  );
  return {
    ...metadata,
    hasProfile: fs.existsSync(modelPaths(dataRoot, id).profile),
    fileUrl: `/api/models/${id}/file`,
  };
}

function serveModelFile(response, dataRoot, id, headOnly = false) {
  const metadata = readModelMetadata(dataRoot, id);
  if (!metadata) {
    json(response, 404, { error: "model_not_found" });
    return;
  }
  const modelPath = modelPaths(dataRoot, id, metadata.extension).model;
  if (!fs.existsSync(modelPath) || !fs.statSync(modelPath).isFile()) {
    json(response, 404, { error: "model_file_not_found" });
    return;
  }
  response.writeHead(200, {
    "Content-Type": MIME_TYPES[metadata.extension] || "application/octet-stream",
    "Content-Length": fs.statSync(modelPath).size,
    "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(metadata.name)}`,
    "Cache-Control": "private, no-store",
  });
  if (headOnly) response.end();
  else fs.createReadStream(modelPath).pipe(response);
}

function profileForModel(dataRoot, id) {
  const metadata = readModelMetadata(dataRoot, id);
  if (!metadata) return null;
  const profilePath = modelPaths(dataRoot, id).profile;
  if (!fs.existsSync(profilePath)) return null;
  const payload = JSON.parse(fs.readFileSync(profilePath, "utf8"));
  if (payload?.version !== CHARACTER_PROFILE_VERSION) {
    throw new Error("stored character profile version is unsupported");
  }
  return sanitizeCharacterProfile(payload, {
    modelId: metadata.id,
    modelName: metadata.name,
  });
}

function saveProfile(dataRoot, id, value) {
  const metadata = readModelMetadata(dataRoot, id);
  if (!metadata) throw new Error("model was not found");
  if (value?.version !== CHARACTER_PROFILE_VERSION) {
    throw new Error("character profile version is unsupported");
  }
  const profile = sanitizeCharacterProfile(value, {
    modelId: metadata.id,
    modelName: metadata.name,
  });
  const target = modelPaths(dataRoot, id).profile;
  const temporary = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.writeFileSync(temporary, `${JSON.stringify(profile, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, target);
  return profile;
}

function deleteModel(dataRoot, id) {
  const metadata = readModelMetadata(dataRoot, id);
  if (!metadata) return false;
  const paths = modelPaths(dataRoot, id, metadata.extension);
  fs.rmSync(paths.model, { force: true });
  fs.rmSync(paths.profile, { force: true });
  fs.rmSync(paths.metadata, { force: true });
  return true;
}

function parseModelRoute(pathname) {
  const match = /^\/api\/models\/([a-f0-9]{24})(?:\/(file|profile))?$/.exec(pathname);
  if (!match) return null;
  return { id: match[1], resource: match[2] || "" };
}

async function proxyJson(response, upstreamUrl, route, requestBody) {
  try {
    const options = {
      method: requestBody === undefined ? "GET" : "POST",
      headers: requestBody === undefined ? {} : { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(15_000),
    };
    if (requestBody !== undefined) options.body = JSON.stringify(requestBody);
    const upstream = await fetch(`${upstreamUrl}${route}`, options);
    const bytes = Buffer.from(await upstream.arrayBuffer());
    if (bytes.length > MAX_UPSTREAM_BYTES) {
      json(response, 502, { error: "upstream_response_too_large" });
      return;
    }
    let payload;
    try {
      payload = JSON.parse(bytes.toString("utf8"));
    } catch {
      json(response, 502, { error: "upstream_response_not_json" });
      return;
    }
    json(response, upstream.status, payload);
  } catch {
    json(response, 502, {
      error: "ardy_v2_unavailable",
      detail: "The loopback ARDY protocol-v2 service did not respond.",
    });
  }
}

function serveStatic(response, requestPath, distRoot, headOnly) {
  let decoded;
  try {
    decoded = decodeURIComponent(requestPath);
  } catch {
    json(response, 400, { error: "invalid_path" });
    return;
  }
  const relative = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const resolved = path.resolve(distRoot, relative);
  const rootPrefix = `${path.resolve(distRoot)}${path.sep}`;
  if (resolved !== path.join(path.resolve(distRoot), "index.html") && !resolved.startsWith(rootPrefix)) {
    json(response, 404, { error: "not_found" });
    return;
  }
  let target = resolved;
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    target = path.join(distRoot, "index.html");
  }
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    json(response, 503, { error: "frontend_not_built", detail: "Run npm run build first." });
    return;
  }
  const body = fs.readFileSync(target);
  response.writeHead(200, {
    "Content-Type": MIME_TYPES[path.extname(target).toLowerCase()] || "application/octet-stream",
    "Content-Length": body.length,
    "Cache-Control": path.basename(target) === "index.html"
      ? "no-store"
      : "public, max-age=31536000, immutable",
  });
  response.end(headOnly ? undefined : body);
}

export function createRigLabServer({
  distRoot = DEFAULT_DIST,
  upstreamUrl = "http://127.0.0.1:8777",
  dataRoot = DEFAULT_DATA_ROOT,
} = {}) {
  const reviewedDist = path.resolve(distRoot);
  const reviewedUpstream = validateUpstreamUrl(upstreamUrl);
  const reviewedDataRoot = prepareDataRoot(dataRoot);
  return http.createServer(async (request, response) => {
    securityHeaders(response);
    const requestUrl = new URL(request.url || "/", "http://127.0.0.1");
    const modelRoute = parseModelRoute(requestUrl.pathname);

    if (request.method === "GET" && requestUrl.pathname === "/healthz") {
      json(response, 200, {
        ok: true,
        app: "ardy-rig-lab",
        poseEndpoint: "/v2/poses",
        upstream: "loopback",
        modelFormats: [...MODEL_EXTENSIONS].map((extension) => extension.slice(1)),
      });
      return;
    }
    if (request.method === "GET" && requestUrl.pathname === "/api/ardy-health") {
      await proxyJson(response, reviewedUpstream, "/healthz");
      return;
    }
    if (request.method === "POST" && requestUrl.pathname === "/v2/poses") {
      try {
        const payload = validatePoseRequest(await readJsonRequest(request));
        await proxyJson(response, reviewedUpstream, "/v2/poses", payload);
      } catch (error) {
        json(response, 400, { error: "invalid_request", detail: error.message });
      }
      return;
    }
    if (request.method === "GET" && requestUrl.pathname === "/api/models") {
      json(response, 200, { models: listModels(reviewedDataRoot) });
      return;
    }
    if (request.method === "POST" && requestUrl.pathname === "/api/models") {
      try {
        json(response, 201, await receiveModel(request, reviewedDataRoot));
      } catch (error) {
        json(response, 400, { error: "invalid_model_upload", detail: error.message });
      }
      return;
    }
    if (modelRoute && modelRoute.resource === "file" && ["GET", "HEAD"].includes(request.method || "")) {
      serveModelFile(response, reviewedDataRoot, modelRoute.id, request.method === "HEAD");
      return;
    }
    if (modelRoute && modelRoute.resource === "profile" && request.method === "GET") {
      try {
        const profile = profileForModel(reviewedDataRoot, modelRoute.id);
        if (profile) json(response, 200, profile);
        else json(response, 404, { error: "profile_not_found" });
      } catch (error) {
        json(response, 500, { error: "profile_unreadable", detail: error.message });
      }
      return;
    }
    if (modelRoute && modelRoute.resource === "profile" && request.method === "PUT") {
      try {
        json(
          response,
          200,
          saveProfile(
            reviewedDataRoot,
            modelRoute.id,
            await readJsonRequest(request, MAX_PROFILE_BYTES),
          ),
        );
      } catch (error) {
        json(response, 400, { error: "invalid_character_profile", detail: error.message });
      }
      return;
    }
    if (modelRoute && modelRoute.resource === "" && request.method === "DELETE") {
      try {
        if (deleteModel(reviewedDataRoot, modelRoute.id)) {
          json(response, 200, { deleted: true, id: modelRoute.id });
        } else {
          json(response, 404, { error: "model_not_found" });
        }
      } catch (error) {
        json(response, 500, { error: "model_delete_failed", detail: error.message });
      }
      return;
    }
    if (!["GET", "HEAD"].includes(request.method || "")) {
      json(response, 405, { error: "method_not_allowed" });
      return;
    }
    if (requestUrl.pathname.startsWith("/api/") || requestUrl.pathname.startsWith("/v2/")) {
      json(response, 404, { error: "not_found" });
      return;
    }
    serveStatic(response, requestUrl.pathname, reviewedDist, request.method === "HEAD");
  });
}

function main() {
  const host = process.env.RIG_LAB_HOST || "127.0.0.1";
  if (!["127.0.0.1", "::1"].includes(host)) {
    throw new Error("RIG_LAB_HOST must remain loopback for the local prototype");
  }
  const port = Number(process.env.RIG_LAB_PORT || 8488);
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) {
    throw new Error("RIG_LAB_PORT must be an unprivileged TCP port");
  }
  const upstreamUrl = process.env.ARDY_RIG_LAB_UPSTREAM || "http://127.0.0.1:8777";
  const dataRoot = process.env.RIG_LAB_DATA_ROOT || DEFAULT_DATA_ROOT;
  const server = createRigLabServer({ upstreamUrl, dataRoot });
  server.listen(port, host, () => {
    console.log(`ARDY Rig Lab listening at http://${host}:${port}`);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
