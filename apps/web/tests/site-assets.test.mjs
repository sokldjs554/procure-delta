import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test } from "node:test";
import { browserAssets, hasProductTitle, verifySiteAssets } from "../scripts/site-assets.mjs";

const html = '<title>ProcureDelta | Demo</title><link href="/_next/static/app.css?build=1&amp;v=2" rel="stylesheet"><script src="/_next/static/app.js?build=1"></script>';

async function fixture(overrides, check) {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(request.url);
    const defaults = request.url.startsWith("/_next/static/")
      ? request.url.includes(".css") ? [200, "text/css", "body{color:black}"] : [200, "application/javascript", "console.log('demo')"]
      : [200, "text/html; charset=utf-8", html];
    const [status, type, body, headers = {}] = overrides[request.url] ?? defaults;
    response.writeHead(status, { "content-type": type, ...headers });
    response.end(body);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try { await check(`http://127.0.0.1:${server.address().port}`, requests); }
  finally {
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

test("checks every page and deduplicates exact asset URLs without losing queries", async () => {
  await fixture({}, async (origin, requests) => {
    const result = await verifySiteAssets(origin, ["/", "/about"]);
    assert.equal(result.pages.length, 2);
    assert.equal(result.assets.length, 2);
    assert.deepEqual(requests, ["/", "/about", "/_next/static/app.css?build=1&v=2", "/_next/static/app.js?build=1"]);
    assert.ok(result.assets.every(asset => asset.bytes > 0 && /^[a-f0-9]{64}$/.test(asset.sha256)));
  });
});

for (const [name, value, expected] of [
  ["missing JavaScript", [404, "text/html", "not found"], /HTTP 404/],
  ["HTML content type", [200, "text/html", html], /incorrect content type/],
  ["CSS returned for JavaScript", [200, "text/css", "body{}"], /incorrect content type/],
  ["empty JavaScript", [200, "application/javascript", ""], /empty response/],
  ["HTML with forged JavaScript content type", [200, "application/javascript", "<!DOCTYPE html><html>error</html>"], /HTML fallback/],
  ["asset redirect", [302, "text/plain", "redirect", { location: "/login" }], /fetch failed/],
]) {
  test(`rejects ${name}`, async () => {
    await fixture({ "/_next/static/app.js?build=1": value }, origin => assert.rejects(verifySiteAssets(origin, ["/"]), expected));
  });
}

test("rejects a 200 startup page and a missing product route", async () => {
  assert.equal(hasProductTitle("<title>Render</title>Application loading"), false);
  await fixture({ "/": [200, "text/html", "<title>Render</title>Application loading"] }, origin =>
    assert.rejects(verifySiteAssets(origin, ["/"]), /product HTML missing/));
  await fixture({ "/about": [404, "text/html", html] }, origin =>
    assert.rejects(verifySiteAssets(origin, ["/", "/about"]), /Page \/about: HTTP 404/));
});

test("requires both script and stylesheet references and same-origin assets", () => {
  assert.throws(() => browserAssets('<script src="/_next/static/app.js"></script>', "https://example.test"), /no Next.js stylesheet/);
  assert.throws(() => browserAssets('<link href="/_next/static/app.css">', "https://example.test"), /no Next.js JavaScript/);
  assert.throws(() => browserAssets(html.replace("/_next/static/app.js", "https://other.test/_next/static/app.js"), "https://example.test"), /external Next.js asset/);
});
