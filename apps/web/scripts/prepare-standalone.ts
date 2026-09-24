import { cpSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export function prepareStandalone(root: string): void {
  const standalone = join(root, ".next/standalone");
  const assets = join(root, ".next/static");
  if (!existsSync(join(standalone, "server.js")) || !existsSync(assets)) {
    throw new Error("Build must contain standalone/server.js and .next/static");
  }
  cpSync(assets, join(standalone, ".next/static"), { recursive: true });
  if (existsSync(join(root, "public"))) {
    cpSync(join(root, "public"), join(standalone, "public"), { recursive: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  prepareStandalone(process.cwd());
  console.log("Standalone browser assets prepared");
}
