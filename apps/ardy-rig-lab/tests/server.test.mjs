import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createRigLabServer,
  validatePoseRequest,
  validateUpstreamUrl,
} from "../server.mjs";
import { poseBatch } from "./helpers.mjs";

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
}

function close(server) {
  return new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

test("server validates the exact browser pose request", () => {
  assert.deepEqual(validatePoseRequest({
    behavior: "wave",
    prompt: "  wave naturally  ",
    intensity: 0.5,
    duration: 4,
    afterSequence: 0,
  }), {
    behavior: "wave",
    prompt: "wave naturally",
    intensity: 0.5,
    duration: 4,
    afterSequence: 0,
  });
  assert.throws(() => validatePoseRequest({
    behavior: "wave",
    intensity: 0.5,
    duration: 4,
    afterSequence: 0,
    path: "/tmp/model",
  }), /unsupported/);
  assert.throws(() => validateUpstreamUrl("https://example.com"), /loopback/);
  assert.equal(validateUpstreamUrl("http://127.0.0.1:8777"), "http://127.0.0.1:8777");
});

test("standalone server proxies only health and strict v2 poses", async (context) => {
  const received = [];
  const upstream = http.createServer(async (request, response) => {
    if (request.url === "/healthz") {
      const body = Buffer.from(JSON.stringify({ protocolVersion: 2, ok: true }));
      response.writeHead(200, { "Content-Type": "application/json", "Content-Length": body.length });
      response.end(body);
      return;
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    received.push(JSON.parse(Buffer.concat(chunks).toString("utf8")));
    const body = Buffer.from(JSON.stringify(poseBatch(1)));
    response.writeHead(200, { "Content-Type": "application/json", "Content-Length": body.length });
    response.end(body);
  });
  await listen(upstream);

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "ardy-rig-lab-test-"));
  context.after(() => fs.rmSync(tempRoot, { recursive: true, force: true }));
  fs.writeFileSync(path.join(tempRoot, "index.html"), "<!doctype html><title>Rig Lab</title>");
  const lab = createRigLabServer({
    distRoot: tempRoot,
    upstreamUrl: `http://127.0.0.1:${upstream.address().port}`,
  });
  await listen(lab);
  context.after(async () => {
    await close(lab);
    await close(upstream);
  });
  const origin = `http://127.0.0.1:${lab.address().port}`;

  const health = await fetch(`${origin}/api/ardy-health`);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).protocolVersion, 2);

  const request = {
    behavior: "explain",
    prompt: "stand and stretch",
    intensity: 0.6,
    duration: 2,
    afterSequence: 0,
  };
  const poses = await fetch(`${origin}/v2/poses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  assert.equal(poses.status, 200);
  assert.equal((await poses.json()).version, 2);
  assert.deepEqual(received, [request]);

  const rejected = await fetch(`${origin}/v2/poses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...request, arbitraryPath: "/private/checkpoint" }),
  });
  assert.equal(rejected.status, 400);
  assert.equal(received.length, 1);

  const index = await fetch(origin);
  assert.equal(index.status, 200);
  assert.match(await index.text(), /Rig Lab/);
  assert.match(index.headers.get("content-security-policy"), /connect-src 'self'/);
});
