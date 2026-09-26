import assert from "node:assert/strict";
import { createHash } from "node:crypto";

export const demoPaths = [
  "/", "/inbox", "/opportunities/opp-ai-contact-center", "/pipeline",
  "/watchlist", "/notifications", "/profile", "/about",
];

export function hasProductTitle(html) {
  return /<title>ProcureDelta(?:\s|\||<)/i.test(html);
}

// Retain query strings: checking a different URL can conceal a deployment fault.
export function browserAssets(html, origin) {
  const urls = new Set();
  for (const match of html.matchAll(/\b(?:src|href)\s*=\s*["']([^"']+\.(?:js|css)(?:\?[^"']*)?)["']/g)) {
    const url = new URL(match[1].replaceAll("&amp;", "&"), origin);
    if (!url.pathname.startsWith("/_next/static/")) continue;
    assert.equal(url.origin, origin, "Unexpected external Next.js asset");
    urls.add(url.href);
  }
  assert.ok([...urls].some(url => new URL(url).pathname.endsWith(".js")), "HTML has no Next.js JavaScript");
  assert.ok([...urls].some(url => new URL(url).pathname.endsWith(".css")), "HTML has no Next.js stylesheet");
  return [...urls];
}

export async function verifySiteAssets(origin, paths, report = { pages: [], assets: [] }) {
  const base = new URL(origin);
  assert.equal(base.origin, origin, "Use an origin without credentials, path, query or fragment");
  assert.ok(paths.length > 0, "At least one product page must be checked");
  const assets = new Set();
  for (const path of paths) {
    assert.ok(path.startsWith("/") && !path.startsWith("//"), "Use same-origin page paths");
    const response = await fetch(`${origin}${path}`, { redirect: "error", signal: AbortSignal.timeout(15000) });
    assert.equal(response.status, 200, `Page ${path}: HTTP ${response.status}`);
    const contentType = response.headers.get("content-type") ?? "";
    assert.match(contentType, /^text\/html(?:;|$)/i, `Page ${path}: unexpected content type`);
    const html = await response.text();
    assert.ok(hasProductTitle(html), `Page ${path}: product HTML missing (possibly a startup/error page)`);
    const references = browserAssets(html, origin);
    for (const url of references) assets.add(url);
    report.pages.push({ path, status: response.status, content_type: contentType, asset_count: references.length });
  }
  for (const url of assets) {
    const response = await fetch(url, { redirect: "error", signal: AbortSignal.timeout(15000) });
    const path = url.slice(origin.length);
    assert.equal(response.status, 200, `Asset ${path}: HTTP ${response.status}`);
    const contentType = response.headers.get("content-type") ?? "";
    const css = new URL(url).pathname.endsWith(".css");
    assert.match(contentType, css ? /^text\/css(?:;|$)/i : /^(?:application|text)\/(?:javascript|ecmascript)(?:;|$)/i,
      `Asset ${path}: incorrect content type`);
    const body = Buffer.from(await response.arrayBuffer());
    assert.ok(body.length > 0, `Asset ${path}: empty response`);
    assert.doesNotMatch(body.subarray(0, 200).toString().trimStart(), /^<(?:!doctype\s+html|html)\b/i,
      `Asset ${path}: HTML fallback masquerading as a browser asset`);
    report.assets.push({ path, status: response.status, content_type: contentType, bytes: body.length,
      sha256: createHash("sha256").update(body).digest("hex") });
  }
  return report;
}
