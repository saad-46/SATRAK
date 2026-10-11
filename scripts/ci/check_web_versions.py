#!/usr/bin/env python3
"""Prove which versions of the security-relevant npm packages the final Web image ships.

Input is the inventory printed by ``web_package_inventory.js`` from inside the running image
(every real installed copy, with its exact version) plus ``pnpm-lock.yaml``. The check fails when:

* the inventory is missing, unparseable, reports errors, or lacks a package the image must ship
  (verification incomplete, exit 2);
* an installed copy is below the approved patched floor below (exit 1);
* an installed copy is not one of the versions ``pnpm-lock.yaml`` resolves for that package, so
  the image does not match what was reviewed (exit 1).

A lock entry alone is never accepted as proof: the lock is only the thing the image is compared
against. Floors are not derived from the lock or the image; changing one is a reviewed code change.

Exit codes: 0 pass, 1 violation, 2 verification incomplete.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EXIT_PASS, EXIT_VIOLATION, EXIT_INCOMPLETE = 0, 1, 2

# Next.js vendors pre-bundled copies of some libraries under next/dist/compiled/<name>/ with a
# stub package.json that has no version. They are part of the `next` package (so covered by its
# floor), their version cannot be read from the image, and they are reported as such, not skipped.
VENDORED_MARKER = "/next/dist/compiled/"

# name -> (floor, must the image ship it, why this floor)
# Floors are the approved patched versions. Advisory data (npm registry bulk advisories, checked
# 2026-10-11) for each: next fixed in 15.5.27 (cache poisoning; 15.5.24 for the critical RCEs),
# sharp 0.35.5 (librsvg), postcss first patched 8.5.23 (approved override is 8.5.29), nanoid
# 3.3.18, source-map-js 1.2.2.
FLOORS: dict[str, tuple[str, bool]] = {
    "next": ("15.5.27", True),
    "sharp": ("0.35.5", True),
    "postcss": ("8.5.29", True),
    "nanoid": ("3.3.18", False),
    "source-map-js": ("1.2.2", False),
}

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_LOCK_KEY = re.compile(r"^  '?(@?[^@\s'][^@\s']*)@(\d+\.\d+\.\d+)(?:\([^']*)?'?:\s*$")


class Incomplete(Exception):
    """The inspection itself failed; this is never a pass."""


def parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION.match(text)
    if not match:  # pre-releases and anything unparseable cannot be compared with a floor
        raise Incomplete(f"unparseable version {text!r}")
    return int(match[1]), int(match[2]), int(match[3])


def lock_versions(lock_text: str) -> dict[str, set[str]]:
    """Versions pnpm-lock.yaml resolves, per package name (the `packages:` section)."""
    out: dict[str, set[str]] = {}
    in_packages = False
    for line in lock_text.splitlines():
        if line.startswith("packages:"):
            in_packages = True
            continue
        if in_packages and line and not line.startswith(" "):
            break  # next top-level section (snapshots:)
        if in_packages:
            match = _LOCK_KEY.match(line)
            if match:
                out.setdefault(match[1], set()).add(match[2])
    if not out:
        raise Incomplete("no packages found in the lock file")
    return out


def evaluate(
    inventory: Mapping[str, Any], resolved: Mapping[str, set[str]]
) -> tuple[list[str], list[str]]:
    """Return (report lines, violations). Raises Incomplete if the inspection cannot be trusted."""
    if inventory.get("errors"):
        raise Incomplete("inventory reported errors: " + "; ".join(map(str, inventory["errors"])))
    packages = inventory.get("packages")
    if not isinstance(packages, list):
        raise Incomplete("inventory has no package list")

    lines: list[str] = []
    violations: list[str] = []
    shipped: dict[str, list[tuple[str, str]]] = {name: [] for name in FLOORS}
    for item in packages:
        name, version, where = item.get("name"), item.get("version"), item.get("path")
        if name not in FLOORS or not isinstance(where, str):
            raise Incomplete(f"malformed inventory entry: {item!r}")
        if version is None and VENDORED_MARKER in where:
            lines.append(f"VENDORED {name} (no version in package.json; bundled inside next) {where}")
            continue
        if not isinstance(version, str):
            raise Incomplete(f"{name}: installed copy without a version: {where}")
        shipped[name].append((version, where))

    for name, (floor, required) in FLOORS.items():
        copies = sorted(shipped[name])
        if not copies:
            if required:
                raise Incomplete(f"{name}: no installed copy found in the image")
            lines.append(f"{name}: not present in the image")
            continue
        known = resolved.get(name, set())
        for version, where in copies:
            below = parse_version(version) < parse_version(floor)
            in_lock = version in known
            status = "OK" if not below and in_lock else "FAIL"
            lines.append(f"{status} {name}@{version} (floor {floor}) {where}")
            if below:
                violations.append(f"{name}@{version} is below the approved floor {floor}")
            if not in_lock:
                violations.append(
                    f"{name}@{version} is not a version pnpm-lock.yaml resolves "
                    f"({', '.join(sorted(known)) or 'none'})"
                )
    return lines, violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        try:
            inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
            lock_text = args.lock.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise Incomplete(f"cannot read inputs: {exc}") from exc
        if not isinstance(inventory, dict):
            raise Incomplete("inventory is not a JSON object")
        lines, violations = evaluate(inventory, lock_versions(lock_text))
    except Incomplete as exc:
        print(f"VERIFICATION INCOMPLETE: {exc}")
        return EXIT_INCOMPLETE
    print("\n".join(lines))
    if violations:
        print("\n".join(f"VIOLATION: {v}" for v in violations))
        return EXIT_VIOLATION
    print("PASS: every shipped copy meets the approved floor and is resolved by the lock file")
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
