"""Policy tests for scripts/ci/check_web_versions.py and web_package_inventory.js."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "ci" / "check_web_versions.py"
INVENTORY_JS = ROOT / "scripts" / "ci" / "web_package_inventory.js"
_spec = importlib.util.spec_from_file_location("check_web_versions", SCRIPT)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["check_web_versions"] = check
_spec.loader.exec_module(check)

GOOD = {
    "next": "15.5.27",
    "sharp": "0.35.5",
    "postcss": "8.5.29",
    "nanoid": "3.3.20",
    "source-map-js": "1.2.2",
}
LOCK = {
    "next": {"15.5.27"},
    "sharp": {"0.35.5"},
    "postcss": {"8.5.16", "8.5.29"},
    "nanoid": {"3.3.15", "3.3.20"},
    "source-map-js": {"1.2.1", "1.2.2"},
}


def _inventory(versions: dict[str, str | None] | None = None, **extra: Any) -> dict[str, Any]:
    chosen = GOOD if versions is None else versions
    return {
        "root": "/app",
        "packages": [
            {"name": n, "version": v, "path": f"/app/node_modules/.pnpm/{n}@{v}/node_modules/{n}"}
            for n, v in chosen.items()
        ],
        "errors": [],
        **extra,
    }


def test_expected_versions_pass() -> None:
    lines, violations = check.evaluate(_inventory(), LOCK)
    assert violations == []
    assert len(lines) == 5 and all(line.startswith("OK ") for line in lines)


def test_floors_are_the_approved_versions() -> None:
    assert {n: f for n, (f, _) in check.FLOORS.items()} == {
        "next": "15.5.27",
        "sharp": "0.35.5",
        "postcss": "8.5.29",
        "nanoid": "3.3.18",
        "source-map-js": "1.2.2",
    }


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("postcss", "8.4.31"),
        ("postcss", "8.5.16"),
        ("postcss", "8.5.28"),
        ("next", "15.5.26"),
        ("sharp", "0.34.5"),
        ("nanoid", "3.3.15"),
        ("source-map-js", "1.2.1"),
    ],
)
def test_below_floor_copy_is_a_violation_even_if_the_lock_resolves_it(name: str, bad: str) -> None:
    lock = {**LOCK, name: LOCK[name] | {bad}}
    inventory = _inventory({**GOOD, name: bad})
    _, violations = check.evaluate(inventory, lock)
    assert any(f"{name}@{bad} is below the approved floor" in v for v in violations)


def test_a_stray_second_postcss_copy_is_caught_alongside_a_good_one() -> None:
    inventory = _inventory()
    inventory["packages"].append(
        {
            "name": "postcss",
            "version": "8.4.31",
            "path": "/app/node_modules/next/node_modules/postcss",
        }
    )
    lock = {**LOCK, "postcss": LOCK["postcss"] | {"8.4.31"}}
    _, violations = check.evaluate(inventory, lock)
    assert any("postcss@8.4.31" in v for v in violations)


def test_copy_the_lock_does_not_resolve_is_a_violation() -> None:
    _, violations = check.evaluate(_inventory({**GOOD, "sharp": "0.35.6"}), LOCK)
    assert any("sharp@0.35.6 is not a version pnpm-lock.yaml resolves" in v for v in violations)


def test_newer_version_resolved_by_the_lock_passes() -> None:
    lock = {**LOCK, "next": {"15.5.28"}}
    _, violations = check.evaluate(_inventory({**GOOD, "next": "15.5.28"}), lock)
    assert violations == []


@pytest.mark.parametrize("name", ["next", "sharp", "postcss"])
def test_required_package_missing_is_incomplete(name: str) -> None:
    with pytest.raises(check.Incomplete):
        check.evaluate(_inventory({k: v for k, v in GOOD.items() if k != name}), LOCK)


def test_optional_package_missing_is_reported_not_silent() -> None:
    lines, violations = check.evaluate(
        _inventory({k: v for k, v in GOOD.items() if k != "nanoid"}), LOCK
    )
    assert violations == [] and "nanoid: not present in the image" in lines


def test_inventory_errors_are_incomplete() -> None:
    with pytest.raises(check.Incomplete):
        check.evaluate(_inventory(errors=["cannot read /app/x: EACCES"]), LOCK)


@pytest.mark.parametrize("version", ["15.5.27-canary.1", "latest", "", "15.5"])
def test_unparseable_versions_are_incomplete(version: str) -> None:
    with pytest.raises(check.Incomplete):
        check.evaluate(_inventory({**GOOD, "next": version}), LOCK)


def test_versionless_copy_bundled_inside_next_is_listed_as_vendored() -> None:
    inventory = _inventory()
    inventory["packages"].append(
        {
            "name": "nanoid",
            "version": None,
            "path": "/app/node_modules/.pnpm/next@15.5.27/node_modules/next/dist/compiled/nanoid",
        }
    )
    lines, violations = check.evaluate(inventory, LOCK)
    assert violations == []
    assert any(line.startswith("VENDORED nanoid") for line in lines)


def test_versionless_copy_anywhere_else_is_incomplete() -> None:
    inventory = _inventory()
    inventory["packages"].append(
        {"name": "nanoid", "version": None, "path": "/app/node_modules/nanoid"}
    )
    with pytest.raises(check.Incomplete):
        check.evaluate(inventory, LOCK)


def test_lock_parser_reads_the_repository_lock() -> None:
    resolved = check.lock_versions((ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8"))
    assert resolved["next"] == {"15.5.27"}
    assert "8.4.31" not in resolved["postcss"]
    assert "0.35.5" in resolved["sharp"]


def test_lock_parser_rejects_a_file_without_packages() -> None:
    with pytest.raises(check.Incomplete):
        check.lock_versions("lockfileVersion: '9.0'\n")


def _write(tmp_path: Path, inventory: Any, lock: str = "") -> tuple[Path, Path]:
    inv = tmp_path / "inventory.json"
    inv.write_text(inventory if isinstance(inventory, str) else json.dumps(inventory))
    lock_file = tmp_path / "pnpm-lock.yaml"
    lock_file.write_text(
        lock
        or "packages:\n"
        + "".join(f"  {n}@{v}:\n    resolution: {{}}\n" for n, vs in LOCK.items() for v in vs)
        + "\nsnapshots:\n"
    )
    return inv, lock_file


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inv, lock = _write(tmp_path, _inventory())
    assert check.main(["--inventory", str(inv), "--lock", str(lock)]) == 0
    assert "PASS" in capsys.readouterr().out

    inv, lock = _write(tmp_path, _inventory({**GOOD, "postcss": "8.4.31"}))
    assert check.main(["--inventory", str(inv), "--lock", str(lock)]) == 1

    for broken in ("", "not json", "[]"):
        inv, lock = _write(tmp_path, broken)
        assert check.main(["--inventory", str(inv), "--lock", str(lock)]) == 2
    assert check.main(["--inventory", str(tmp_path / "nope"), "--lock", str(lock)]) == 2
    assert "VERIFICATION INCOMPLETE" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_inventory_script_reads_real_package_json_and_ignores_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "node_modules" / ".pnpm" / "postcss@8.5.29" / "node_modules" / "postcss"
    real.mkdir(parents=True)
    (real / "package.json").write_text('{"name":"postcss","version":"8.5.29"}')
    link = tmp_path / "node_modules" / "postcss"
    link.symlink_to(real, target_is_directory=True)
    vendored = tmp_path / "node_modules" / "next" / "dist" / "compiled" / "nanoid"
    vendored.mkdir(parents=True)
    (vendored / "package.json").write_text('{"name":"nanoid","main":"index.cjs"}')

    result = subprocess.run(
        [shutil.which("node") or "node", "-"],
        input=INVENTORY_JS.read_text(),
        env={"INVENTORY_ROOT": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["errors"] == []
    found = {(p["name"], p["version"]) for p in data["packages"]}
    assert found == {("postcss", "8.5.29"), ("nanoid", None)}  # the symlink is not a second copy


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_inventory_script_fails_closed_when_the_root_is_unreadable(tmp_path: Path) -> None:
    result = subprocess.run(
        [shutil.which("node") or "node", "-"],
        input=INVENTORY_JS.read_text(),
        env={"INVENTORY_ROOT": str(tmp_path / "missing"), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"]
