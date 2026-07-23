import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const APP_ROOT = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DIST = path.join(APP_ROOT, "dist");
const MAX_REQUEST_BYTES = 8 * 1024;
const MAX_UPSTREAM_BYTES = 512 * 1024;
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
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
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
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
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

async function readJsonRequest(request) {
  const contentType = String(request.headers["content-type"] || "").split(";", 1)[0].trim();
  if (contentType !== "application/json") throw new Error("Content-Type must be application/json");
  const declared = Number(request.headers["content-length"]);
  if (!Number.isSafeInteger(declared) || declared < 1 || declared > MAX_REQUEST_BYTES) {
    throw new Error("request body size is outside the supported range");
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_REQUEST_BYTES) throw new Error("request body is too large");
    chunks.push(chunk);
  }
  if (size !== declared) throw new Error("request body length did not match Content-Length");
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
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
} = {}) {
  const reviewedDist = path.resolve(distRoot);
  const reviewedUpstream = validateUpstreamUrl(upstreamUrl);
  return http.createServer(async (request, response) => {
    securityHeaders(response);
    const requestUrl = new URL(request.url || "/", "http://127.0.0.1");

    if (request.method === "GET" && requestUrl.pathname === "/healthz") {
      json(response, 200, {
        ok: true,
        app: "ardy-rig-lab",
        poseEndpoint: "/v2/poses",
        upstream: "loopback",
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
  const server = createRigLabServer({ upstreamUrl });
  server.listen(port, host, () => {
    console.log(`ARDY Rig Lab listening at http://${host}:${port}`);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
