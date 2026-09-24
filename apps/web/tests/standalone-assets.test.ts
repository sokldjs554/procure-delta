import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

test("standalone packaging includes browser chunks and public files", async () => {
  const { prepareStandalone } = await import("../scripts/prepare-standalone.ts");
  const root = mkdtempSync(join(tmpdir(), "procure-standalone-"));
  try {
    mkdirSync(join(root, ".next/standalone"), { recursive: true });
    mkdirSync(join(root, ".next/static/chunks"), { recursive: true });
    mkdirSync(join(root, "public"));
    writeFileSync(join(root, ".next/standalone/server.js"), "server");
    writeFileSync(join(root, ".next/static/chunks/app.js"), "browser-code");
    writeFileSync(join(root, "public/icon.svg"), "icon");
    prepareStandalone(root);
    assert.equal(readFileSync(join(root, ".next/standalone/.next/static/chunks/app.js"), "utf8"), "browser-code");
    assert.equal(readFileSync(join(root, ".next/standalone/public/icon.svg"), "utf8"), "icon");
    assert.equal(readFileSync(join(root, ".next/standalone/server.js"), "utf8"), "server");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("packaging fails when a build has no browser assets", async () => {
  const { prepareStandalone } = await import("../scripts/prepare-standalone.ts");
  const root = mkdtempSync(join(tmpdir(), "procure-standalone-"));
  try {
    mkdirSync(join(root, ".next/standalone"), { recursive: true });
    writeFileSync(join(root, ".next/standalone/server.js"), "server");
    assert.throws(() => prepareStandalone(root), /static/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
