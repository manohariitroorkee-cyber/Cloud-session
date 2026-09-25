// Builds ../index.html: one self-contained file with epanet-js (including its
// embedded WebAssembly engine), the page script and compiled Tailwind CSS all
// inlined, so it works offline with no CDN.
//
//   cd web-src && npm install && npm run build

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

const html = readFileSync(here("./template.html"), "utf8")
  .replace("/*__TAILWIND_CSS__*/", () => safeCss)
  .replace("/*__APP_JS__*/", () => appJs);

writeFileSync(here("../index.html"), html);
console.log(`index.html written: ${(html.length / 1024).toFixed(0)} KB`);
