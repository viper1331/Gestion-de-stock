import fs from "node:fs";
import path from "node:path";

const FEATURES_DIR = path.resolve("frontend/src/features");

const widthClassRegex = /\b(?:w|min-w|max-w)-\[(\d+)px\]/;
const heightClassRegex = /(?<!max-|min-)h-\[(\d+)px\]/;
const inlineWidthRegex = /\b(?:width|minWidth|maxWidth)\s*:\s*['"`]?\d+px['"`]?/;
const heightAllowlist = /thumbnail|avatar|icon|image|img|logo|preview|iframe/i;

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
          message: "Fixed width class detected"
        });
      }
      if (inlineWidthRegex.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message: "Fixed width style detected"
        });
      }
      if (heightClassRegex.test(line) && !heightAllowlist.test(line)) {
        violations.push({
          file: fullPath,
          line: index + 1,
          message: "Fixed height class detected"
        });
      }
    });
  }
}

walk(FEATURES_DIR);

if (violations.length > 0) {
  console.error("Layout constraint violations detected:");
  for (const violation of violations) {
    console.error(`- ${violation.file}:${violation.line} ${violation.message}`);
  }
  process.exit(1);
}

console.log("Layout constraints check passed.");
