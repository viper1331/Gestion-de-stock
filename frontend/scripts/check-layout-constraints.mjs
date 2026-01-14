import fs from "node:fs";
import path from "node:path";

const SOURCE_DIRS = [
  path.resolve("frontend/src/features"),
  path.resolve("frontend/src/components")
];

const widthClassRegex = /\b(?:w|min-w|max-w)-\[(\d+)px\]/;
const heightClassRegex = /(?<!max-|min-)h-\[(\d+)px\]/;
const inlineWidthRegex = /\b(?:width|minWidth|maxWidth)\s*:\s*['"`]?\d+px['"`]?/;
const heightAllowlist = /thumbnail|avatar|icon|image|img|logo|preview|iframe/i;
const navShellRegex = /frontend\/src\/components\/.*(AppLayout|Sidebar|Navigation).*\.tsx?$/;
const navPositionClassRegex = /\b(?:left|right|min-w|w)-\[(\d+)px\]/;
const inlinePositionRegex = /\b(?:left|right)\s*:\s*['"`]?\d+px['"`]?/;

const violations = [];

function walk(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(fullPath);
      continue;
    }
    if (!entry.name.endsWith(".ts") && !entry.name.endsWith(".tsx")) {
      continue;
    }
    const content = fs.readFileSync(fullPath, "utf8");
    const lines = content.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (widthClassRegex.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message:
            "Fixed width class detected. Prefer min-w-0, w-full, responsive grids, or table-layout: fixed with truncation."
        });
      }
      if (inlineWidthRegex.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message:
            "Fixed width style detected. Prefer min-w-0, w-full, responsive grids, or table-layout: fixed with truncation."
        });
      }
      if (heightClassRegex.test(line) && !heightAllowlist.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message:
            "Fixed height class detected on a dynamic container. Prefer auto height, min-h-0, and overflow-auto where needed."
        });
      }
      if (navShellRegex.test(fullPath) && navPositionClassRegex.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message:
            "Fixed px position/width class detected in navigation shell. Use responsive sizing (rem/vw) and avoid px offsets."
        });
      }
      if (navShellRegex.test(fullPath) && inlinePositionRegex.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message:
            "Fixed px position style detected in navigation shell. Use responsive sizing (rem/vw) and avoid px offsets."
        });
      }
    });
  }
}

SOURCE_DIRS.forEach((dir) => {
  if (fs.existsSync(dir)) {
    walk(dir);
  }
});

if (violations.length > 0) {
  console.error("Layout constraint violations detected:");
  for (const violation of violations) {
    console.error(`- ${violation.file}:${violation.line} ${violation.message}`);
  }
  console.error(
    "Use responsive primitives instead (min-w-0, w-full, responsive grids, or table-layout: fixed with truncation/wrap)."
  );
  process.exit(1);
}

console.log("Layout constraints check passed.");
