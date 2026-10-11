// Lists every installed copy of the packages whose shipped version CI must prove.
//
// Runs INSIDE the final Web image (`docker exec -i satrak-web node - < this file`), where only the
// `node` binary exists. It reads package.json files from disk: a lock file says what was resolved,
// this says what was shipped. It prints JSON only (no environment data) and exits non-zero if it
// could not walk the tree, so an incomplete inspection cannot look like a pass.
//
// Symlinks are not followed: pnpm links each package into several places, and the real copy under
// node_modules/.pnpm/<name>@<version>/ is the one that counts. Each real copy is reported once.
"use strict";
const fs = require("fs");
const path = require("path");

// INVENTORY_ROOT exists only so the script can be tested outside an image; CI leaves it unset.
const ROOT = process.env.INVENTORY_ROOT || "/app";
const WANT = new Set(["next", "sharp", "postcss", "nanoid", "source-map-js"]);
const found = [];
const errors = [];

function walk(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    errors.push(`cannot read ${dir}: ${e.code || e.message}`);
    return;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue; // symlinks and files are skipped
    const full = path.join(dir, entry.name);
    if (WANT.has(entry.name)) {
      const manifest = path.join(full, "package.json");
      if (fs.existsSync(manifest)) {
        try {
          const meta = JSON.parse(fs.readFileSync(manifest, "utf8"));
          if (meta.name === entry.name) {
            found.push({
              name: meta.name,
              version: typeof meta.version === "string" ? meta.version : null,
              path: full,
            });
          }
        } catch (e) {
          errors.push(`cannot parse ${manifest}: ${e.message}`);
        }
      }
    }
    walk(full);
  }
}

walk(ROOT);
process.stdout.write(JSON.stringify({ root: ROOT, packages: found, errors }, null, 2) + "\n");
process.exit(errors.length ? 2 : 0);
