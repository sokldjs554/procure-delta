import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const standalone = resolve(root, ".next", "standalone");
if (!existsSync(standalone)) {
  throw new Error("Next standalone output is missing; run next build first");
}

function replaceDirectory(source, destination) {
  if (!existsSync(source)) return;
  rmSync(destination, { recursive: true, force: true });
  mkdirSync(destination, { recursive: true });
  cpSync(source, destination, { recursive: true });
}

replaceDirectory(
  resolve(root, ".next", "static"),
  resolve(standalone, ".next", "static"),
);
replaceDirectory(resolve(root, "public"), resolve(standalone, "public"));

console.log("Standalone assets prepared: .next/static and public");
