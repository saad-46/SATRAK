#!/usr/bin/env python3
"""Decide whether a container image may pass CI, from a Trivy JSON report.

Trivy only scans; this script holds the policy so that it is reviewable and tested:

* A *fixable* finding is a HIGH or CRITICAL vulnerability whose report entry names a fixed version.
  Findings with no published fix are listed but never fail the build.
* A scanner problem is not a finding. A failed Trivy step, a missing/unparseable/incomplete report,
  or a report for a different image exits 2 with ``SCAN INCOMPLETE``. It is never a pass.
* Documented exceptions (``security/image-scan-exceptions.json``) may excuse a specific
  (vulnerability id, package, image). Every exception needs an owner, a different approver, a
  justification and an expiry at most 90 days after its creation date. An expired exception fails
  the build even if the vulnerability is gone, so stale entries are removed, not accumulated.

Exit codes: 0 pass, 1 fixable vulnerabilities, 2 scan incomplete, 3 exception policy violation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_PASS, EXIT_FINDINGS, EXIT_INCOMPLETE, EXIT_EXCEPTIONS = 0, 1, 2, 3
GATED_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
MAX_EXCEPTION_DAYS = 90
IMAGE_KEYS = ("api", "web")
_REQUIRED = ("id", "package", "image", "justification", "owner", "approver", "created", "expires")


class ScanIncompleteError(Exception):
    """The scanner did not produce a trustworthy report."""


class ExceptionPolicyError(Exception):
    """The exceptions file is invalid or contains an expired entry."""


@dataclass(frozen=True)
class Finding:
    vulnerability_id: str
    package: str
    installed: str
    fixed: str
    severity: str
    target: str


def _load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ScanIncompleteError(f"{what} {path} was not produced") from None
    except (OSError, ValueError) as exc:
        raise ScanIncompleteError(f"{what} {path} is unreadable: {exc}") from None


def read_findings(report_path: Path, image_ref: str) -> tuple[list[Finding], list[Finding]]:
    """Return (fixable, unfixed) HIGH/CRITICAL findings, or raise ScanIncompleteError."""
    report = _load_json(report_path, "report")
    if not isinstance(report, dict):
        raise ScanIncompleteError("report is not a JSON object")
    if report.get("SchemaVersion") != 2:
        raise ScanIncompleteError(f"unsupported report schema {report.get('SchemaVersion')!r}")
    if report.get("ArtifactType") != "container_image":
        raise ScanIncompleteError(f"report is for a {report.get('ArtifactType')!r}, not an image")
    if report.get("ArtifactName") != image_ref:
        raise ScanIncompleteError(
            f"report is for {report.get('ArtifactName')!r}, expected {image_ref!r}"
        )
    metadata = report.get("Metadata")
    if not isinstance(metadata, dict) or not metadata.get("ImageID"):
        raise ScanIncompleteError("report has no image metadata (the image was not inspected)")
    results = report.get("Results", [])
    if not isinstance(results, list):
        raise ScanIncompleteError("report Results is not a list")
    fixable: list[Finding] = []
    unfixed: list[Finding] = []
    for result in results:
        if not isinstance(result, dict):
            raise ScanIncompleteError("report contains a malformed result")
        vulns = result.get("Vulnerabilities") or []
        if not isinstance(vulns, list):
            raise ScanIncompleteError("report contains malformed vulnerabilities")
        for vuln in vulns:
            if not isinstance(vuln, dict) or not vuln.get("VulnerabilityID"):
                raise ScanIncompleteError("report contains a vulnerability without an id")
            severity = str(vuln.get("Severity", "")).upper()
            if severity not in GATED_SEVERITIES:
                continue
            finding = Finding(
                vulnerability_id=str(vuln["VulnerabilityID"]),
                package=str(vuln.get("PkgName", "")),
                installed=str(vuln.get("InstalledVersion", "")),
                fixed=str(vuln.get("FixedVersion", "") or ""),
                severity=severity,
                target=str(result.get("Target", "")),
            )
            (fixable if finding.fixed.strip() else unfixed).append(finding)
    return fixable, unfixed


def _date(value: Any, field: str, entry: str) -> dt.date:
    try:
        if not isinstance(value, str):
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ExceptionPolicyError(f"{entry}: {field} must be an ISO date (YYYY-MM-DD)") from None


def load_exceptions(path: Path, today: dt.date) -> list[dict[str, Any]]:
    """Validate the exceptions file. Raises ExceptionPolicyError on any violation."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExceptionPolicyError(f"{path} is unreadable: {exc}") from None
    if not isinstance(data, dict) or set(data) - {"version", "exceptions"}:
        raise ExceptionPolicyError("exceptions file must contain only 'version' and 'exceptions'")
    if data.get("version") != 1 or not isinstance(data.get("exceptions"), list):
        raise ExceptionPolicyError("exceptions file needs version 1 and an 'exceptions' list")
    seen: set[tuple[str, str, str]] = set()
    valid: list[dict[str, Any]] = []
    for index, raw in enumerate(data["exceptions"]):
        name = f"exception #{index + 1}"
        if not isinstance(raw, dict):
            raise ExceptionPolicyError(f"{name} is not an object")
        name = f"exception {raw.get('id', index + 1)!s}"
        unknown = set(raw) - set(_REQUIRED)
        if unknown:
            raise ExceptionPolicyError(f"{name}: unknown field(s) {sorted(unknown)}")
        for field in _REQUIRED:
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ExceptionPolicyError(f"{name}: {field} is required")
        if raw["image"] not in IMAGE_KEYS:
            raise ExceptionPolicyError(f"{name}: image must be one of {IMAGE_KEYS}")
        if raw["owner"].strip().lower() == raw["approver"].strip().lower():
            raise ExceptionPolicyError(f"{name}: approver must differ from owner")
        created = _date(raw["created"], "created", name)
        expires = _date(raw["expires"], "expires", name)
        if created > today:
            raise ExceptionPolicyError(f"{name}: created is in the future")
        if expires <= created:
            raise ExceptionPolicyError(f"{name}: expires must be after created")
        if (expires - created).days > MAX_EXCEPTION_DAYS:
            raise ExceptionPolicyError(f"{name}: expiry is more than {MAX_EXCEPTION_DAYS} days out")
        if expires < today:
            raise ExceptionPolicyError(f"{name}: EXPIRED on {expires}; remove it or renew it")
        key = (raw["id"], raw["package"], raw["image"])
        if key in seen:
            raise ExceptionPolicyError(f"{name}: duplicate for {raw['package']} on {raw['image']}")
        seen.add(key)
        valid.append(raw)
    return valid


def evaluate(
    report_path: Path,
    image_ref: str,
    image_key: str,
    exceptions_path: Path,
    trivy_outcome: str,
    today: dt.date,
    out: Any = sys.stdout,
) -> int:
    def say(message: str) -> None:
        print(message, file=out)

    if trivy_outcome != "success":
        say(f"SCAN INCOMPLETE: the Trivy step ended with outcome {trivy_outcome!r}")
        return EXIT_INCOMPLETE
    try:
        fixable, unfixed = read_findings(report_path, image_ref)
    except ScanIncompleteError as exc:
        say(f"SCAN INCOMPLETE: {exc}")
        return EXIT_INCOMPLETE
    try:
        exceptions = load_exceptions(exceptions_path, today)
    except ExceptionPolicyError as exc:
        say(f"EXCEPTION POLICY VIOLATION: {exc}")
        return EXIT_EXCEPTIONS
    excused = {(e["id"], e["package"]): e for e in exceptions if e["image"] == image_key}
    blocking = [f for f in fixable if (f.vulnerability_id, f.package) not in excused]
    for f in fixable:
        if (f.vulnerability_id, f.package) in excused:
            e = excused[(f.vulnerability_id, f.package)]
            say(
                f"EXCEPTED {f.vulnerability_id} {f.package} "
                f"(until {e['expires']}, owner {e['owner']})"
            )
    for f in unfixed:
        say(f"UNFIXED (not gating) {f.severity} {f.vulnerability_id} {f.package} {f.installed}")
    if blocking:
        say(f"VULNERABILITIES FOUND: {len(blocking)} fixable HIGH/CRITICAL in {image_ref}")
        for f in blocking:
            say(
                f"  {f.severity} {f.vulnerability_id} {f.package} {f.installed} -> {f.fixed}"
                f" ({f.target})"
            )
        return EXIT_FINDINGS
    say(f"PASS: no un-excepted fixable HIGH/CRITICAL vulnerabilities in {image_ref}")
    return EXIT_PASS


def check_sarif(path: Path, out: Any = sys.stdout) -> int:
    try:
        data = _load_json(path, "SARIF file")
        if not isinstance(data, dict) or data.get("version") != "2.1.0":
            raise ScanIncompleteError("SARIF version is not 2.1.0")
        runs = data.get("runs")
        if not isinstance(runs, list) or not runs or not all(isinstance(r, dict) for r in runs):
            raise ScanIncompleteError("SARIF has no runs")
        if not all(isinstance(r.get("tool", {}).get("driver", {}).get("name"), str) for r in runs):
            raise ScanIncompleteError("SARIF run has no tool driver")
    except ScanIncompleteError as exc:
        print(f"SCAN INCOMPLETE: {exc}", file=out)
        return EXIT_INCOMPLETE
    print(f"SARIF OK: {path}", file=out)
    return EXIT_PASS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("gate", help="evaluate a Trivy JSON report")
    gate.add_argument("--report", type=Path, required=True)
    gate.add_argument("--image-ref", required=True, help="image reference given to Trivy")
    gate.add_argument("--image-key", choices=IMAGE_KEYS, required=True)
    gate.add_argument("--exceptions", type=Path, required=True)
    gate.add_argument("--trivy-outcome", required=True, help="outcome of the Trivy step")
    gate.add_argument("--today", help="override today's date (tests only)")
    sarif = sub.add_parser("sarif", help="validate a SARIF file")
    sarif.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "sarif":
        return check_sarif(args.path)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.UTC).date()
    return evaluate(
        args.report, args.image_ref, args.image_key, args.exceptions, args.trivy_outcome, today
    )


if __name__ == "__main__":
    sys.exit(main())
