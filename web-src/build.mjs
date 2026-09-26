// Builds ../index.html: one self-contained file with epanet-js (including its
// embedded WebAssembly engine), the page script and compiled Tailwind CSS all
// inlined, so it works offline with no CDN.
//
//   cd web-src && npm install && npm run build
//   node build.mjs <path>   also writes the page body alone (for claude.ai artifacts)

import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

const js = await build({
  entryPoints: [here("./app.js")],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2020",
  minify: true,
  write: false,
  legalComments: "eof",
  logLevel: "warning",
  // epanet-js reads import.meta.url only as a fallback for locating a .wasm
  // file; the engine is embedded, so an empty base is fine in an inline script.
  define: { "import.meta.url": '""' },
});
let appJs = js.outputFiles[0].text;

const css = execFileSync(
  "npx",
  ["tailwindcss", "-c", here("./tailwind.config.cjs"), "-i", here("./input.css"), "--minify"],
  { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
);

// Nothing inside the inline blocks may close the surrounding tag early.
appJs = appJs.replace(/<\/script/gi, "<\\/script");
const safeCss = css.replace(/<\/style/gi, "<\\/style");

const body = readFileSync(here("./template.html"), "utf8")
  .replace("/*__TAILWIND_CSS__*/", () => safeCss)
  .replace("/*__APP_JS__*/", () => appJs);

// The repo copy is a complete document that opens straight from disk.
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
</head>
<body>
${body}
</body>
</html>
`;
writeFileSync(here("../index.html"), html);
console.log(`index.html written: ${(html.length / 1024).toFixed(0)} KB`);

// Optional: page-body variant for hosts that supply their own <html> skeleton.
const artifactOut = process.argv[2];
if (artifactOut) {
  writeFileSync(artifactOut, body);
  console.log(`page body written to ${artifactOut}`);
}
