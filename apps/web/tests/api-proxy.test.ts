import assert from "node:assert/strict";
import test from "node:test";
import config from "../next.config.ts";

const keys = ["API_PROXY_ORIGIN", "NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_STATIC_DEMO"];

async function rewrites(values: Record<string, string>) {
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    for (const key of keys) {
      if (key in values) process.env[key] = values[key];
      else delete process.env[key];
    }
    return await config.rewrites?.() ?? [];
  } finally {
    for (const key of keys) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  }
}

test("cloud API calls use the web origin with a fixed upstream", async () => {
  assert.deepEqual(await rewrites({
    API_PROXY_ORIGIN: "https://procure-delta-api.onrender.com/",
    NEXT_PUBLIC_API_URL: "",
  }), [{
    source: "/api/v1/:path*",
    destination: "https://procure-delta-api.onrender.com/api/v1/:path*",
  }]);
});

test("the container proxy can reach the private API service", async () => {
  assert.deepEqual(await rewrites({
    API_PROXY_ORIGIN: "http://api:8000", NEXT_PUBLIC_API_URL: "",
  }), [{ source: "/api/v1/:path*", destination: "http://api:8000/api/v1/:path*" }]);
});

test("an unconfigured proxy and the static demo have no upstream routes", async () => {
  assert.deepEqual(await rewrites({}), []);
  assert.deepEqual(await rewrites({
    NEXT_PUBLIC_STATIC_DEMO: "true", API_PROXY_ORIGIN: "https://api.example.test",
  }), []);
});

test("proxy setup rejects a browser URL that would bypass the same-origin route", async () => {
  await assert.rejects(rewrites({ API_PROXY_ORIGIN: "https://api.example.test" }),
    /NEXT_PUBLIC_API_URL must be empty/);
  await assert.rejects(rewrites({
    API_PROXY_ORIGIN: "https://api.example.test", NEXT_PUBLIC_API_URL: "https://api.example.test",
  }), /NEXT_PUBLIC_API_URL must be empty/);
});

test("the proxy target must be a credential-free HTTP origin", async () => {
  for (const target of [
    "ftp://api.example.test", "https://user:secret@api.example.test", "/api",
    "https://api.example.test/path", "https://api.example.test?key=secret",
    "https://api.example.test#fragment",
  ]) {
    await assert.rejects(rewrites({ API_PROXY_ORIGIN: target, NEXT_PUBLIC_API_URL: "" }),
      error => error instanceof Error && error.message ===
        "API_PROXY_ORIGIN must be a credential-free HTTP(S) origin without a path, query or fragment");
  }
});
