"""Policy tests for scripts/ci/image_scan_gate.py (vulnerability gate and exception rules)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "ci" / "image_scan_gate.py"
_spec = importlib.util.spec_from_file_location("image_scan_gate", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
sys.modules["image_scan_gate"] = gate
_spec.loader.exec_module(gate)

TODAY = dt.date(2026, 10, 11)
IMAGE = "satrak-api:ci"


def _vuln(
    vid: str = "CVE-2026-0001",
    pkg: str = "libexample",
    severity: str = "HIGH",
    fixed: str | None = "1.2.4",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "VulnerabilityID": vid,
        "PkgName": pkg,
        "InstalledVersion": "1.2.3",
        "Severity": severity,
    }
    if fixed is not None:
        entry["FixedVersion"] = fixed
    return entry


def _report(vulns: list[dict[str, Any]] | None, **overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "SchemaVersion": 2,
        "ArtifactName": IMAGE,
        "ArtifactType": "container_image",
        "Metadata": {"ImageID": "sha256:abc"},
    }
    if vulns is not None:
        report["Results"] = [{"Target": "debian 12", "Vulnerabilities": vulns}]
    report.update(overrides)
    return report


def _exception(**overrides: Any) -> dict[str, Any]:
    entry = {
        "id": "CVE-2026-0001",
        "package": "libexample",
        "image": "api",
        "justification": "Not reachable: the library is only loaded by a tool we do not run.",
        "owner": "owner-a",
        "approver": "approver-b",
        "created": "2026-10-01",
        "expires": "2026-12-01",
    }
    entry.update(overrides)
    return entry


def _run(
    tmp_path: Path,
    report: Any,
    exceptions: list[Any] | dict[str, Any] | None = None,
    outcome: str = "success",
    image_key: str = "api",
) -> tuple[int, str]:
    report_path = tmp_path / "report.json"
    if report is not None:
        report_path.write_text(report if isinstance(report, str) else json.dumps(report))
    exc_path = tmp_path / "exceptions.json"
    body = (
        exceptions
        if isinstance(exceptions, dict)
        else {"version": 1, "exceptions": exceptions or []}
    )
    exc_path.write_text(json.dumps(body))
    out = io.StringIO()
    code = gate.evaluate(report_path, IMAGE, image_key, exc_path, outcome, TODAY, out)
    return code, out.getvalue()


# --- Vulnerability threshold -------------------------------------------------------------------
def test_a_clean_report_passes_even_when_trivy_omits_results(tmp_path: Path) -> None:
    code, text = _run(tmp_path, _report(None))
    assert code == gate.EXIT_PASS and text.startswith("PASS")


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL", "high"])
def test_a_fixable_high_or_critical_finding_fails(tmp_path: Path, severity: str) -> None:
    code, text = _run(tmp_path, _report([_vuln(severity=severity)]))
    assert code == gate.EXIT_FINDINGS
    assert "VULNERABILITIES FOUND: 1" in text and "CVE-2026-0001" in text and "-> 1.2.4" in text


@pytest.mark.parametrize("severity", ["MEDIUM", "LOW", "UNKNOWN"])
def test_lower_severities_do_not_gate(tmp_path: Path, severity: str) -> None:
    assert _run(tmp_path, _report([_vuln(severity=severity)]))[0] == gate.EXIT_PASS


@pytest.mark.parametrize("fixed", [None, "", "   "])
def test_unfixed_findings_are_reported_but_do_not_gate(tmp_path: Path, fixed: str | None) -> None:
    code, text = _run(tmp_path, _report([_vuln(severity="CRITICAL", fixed=fixed)]))
    assert code == gate.EXIT_PASS and "UNFIXED (not gating)" in text


# --- Scanner failure is not a finding and never a pass -----------------------------------------
@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
def test_a_failed_scanner_step_is_scan_incomplete(tmp_path: Path, outcome: str) -> None:
    code, text = _run(tmp_path, _report(None), outcome=outcome)
    assert code == gate.EXIT_INCOMPLETE and text.startswith("SCAN INCOMPLETE")


def test_a_missing_report_is_scan_incomplete(tmp_path: Path) -> None:
    code, text = _run(tmp_path, None)
    assert code == gate.EXIT_INCOMPLETE and "SCAN INCOMPLETE" in text


@pytest.mark.parametrize(
    "report",
    [
        "",
        "{not json",
        "[]",
        {"SchemaVersion": 1},
        {"SchemaVersion": 2, "ArtifactType": "filesystem", "ArtifactName": IMAGE},
        {"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": "other:tag"},
        {"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": IMAGE},
        {**_report(None), "Metadata": {}},
        {**_report(None), "Results": "oops"},
        {**_report(None), "Results": ["oops"]},
        {**_report(None), "Results": [{"Vulnerabilities": "oops"}]},
        {**_report(None), "Results": [{"Vulnerabilities": [{"Severity": "HIGH"}]}]},
    ],
    ids=[
        "empty-file",
        "invalid-json",
        "not-an-object",
        "old-schema",
        "not-an-image",
        "different-image",
        "no-metadata-key",
        "empty-metadata",
        "results-not-list",
        "result-not-object",
        "vulns-not-list",
        "vuln-without-id",
    ],
)
def test_an_untrustworthy_report_is_scan_incomplete(tmp_path: Path, report: Any) -> None:
    assert _run(tmp_path, report)[0] == gate.EXIT_INCOMPLETE


def test_scan_incomplete_takes_precedence_over_a_broken_exceptions_file(tmp_path: Path) -> None:
    code, _ = _run(tmp_path, None, exceptions={"version": 2})
    assert code == gate.EXIT_INCOMPLETE


# --- Exceptions --------------------------------------------------------------------------------
def test_a_valid_exception_excuses_only_its_vulnerability_package_and_image(tmp_path: Path) -> None:
    findings = [_vuln(), _vuln(vid="CVE-2026-0002")]
    code, text = _run(tmp_path, _report([_vuln()]), [_exception()])
    assert code == gate.EXIT_PASS and "EXCEPTED CVE-2026-0001" in text
    code, text = _run(tmp_path, _report(findings), [_exception()])
    assert code == gate.EXIT_FINDINGS and "CVE-2026-0002" in text
    # a same-id finding in another package is not covered
    assert _run(tmp_path, _report([_vuln(pkg="other")]), [_exception()])[0] == gate.EXIT_FINDINGS
    # an exception granted to the api image does not excuse the web image
    assert (
        _run(tmp_path, _report([_vuln()]), [_exception()], image_key="web")[0] == gate.EXIT_FINDINGS
    )


@pytest.mark.parametrize(
    ("created", "expires"), [("2026-09-01", "2026-10-10"), ("2026-01-01", "2026-03-01")]
)
def test_an_expired_exception_fails_even_when_the_vulnerability_is_gone(
    tmp_path: Path, created: str, expires: str
) -> None:
    code, text = _run(tmp_path, _report(None), [_exception(created=created, expires=expires)])
    assert code == gate.EXIT_EXCEPTIONS and "EXPIRED" in text


def test_an_exception_expiring_today_is_still_valid(tmp_path: Path) -> None:
    entry = _exception(created="2026-09-01", expires=TODAY.isoformat())
    assert _run(tmp_path, _report([_vuln()]), [entry])[0] == gate.EXIT_PASS


def test_an_expired_exception_does_not_excuse_a_present_finding(tmp_path: Path) -> None:
    entry = _exception(created="2026-08-01", expires="2026-09-01")
    assert _run(tmp_path, _report([_vuln()]), [entry])[0] == gate.EXIT_EXCEPTIONS


@pytest.mark.parametrize(
    "override",
    [
        {"expires": "2027-01-10"},  # 101 days after creation
        {"expires": "2026-10-01"},  # not after creation
        {"created": "2026-10-12", "expires": "2026-11-01"},  # created in the future
        {"approver": "OWNER-A"},  # approver equals owner (case-insensitive)
        {"owner": " "},
        {"justification": ""},
        {"id": ""},
        {"package": ""},
        {"image": "worker"},
        {"expires": "next month"},
        {"expires": 20261201},
        {"surprise": "field"},
    ],
    ids=[
        "too-long",
        "expires-before-created",
        "created-future",
        "same-approver",
        "blank-owner",
        "no-justification",
        "no-id",
        "no-package",
        "unknown-image",
        "bad-date",
        "date-not-string",
        "unknown-field",
    ],
)
def test_malformed_or_over_long_exceptions_are_rejected(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    assert _run(tmp_path, _report(None), [_exception(**override)])[0] == gate.EXIT_EXCEPTIONS


def test_the_ninety_day_limit_is_inclusive(tmp_path: Path) -> None:
    entry = _exception(created="2026-10-01", expires="2026-12-30")  # exactly 90 days
    assert _run(tmp_path, _report(None), [entry])[0] == gate.EXIT_PASS


def test_duplicate_exceptions_and_bad_files_are_rejected(tmp_path: Path) -> None:
    assert _run(tmp_path, _report(None), [_exception(), _exception()])[0] == gate.EXIT_EXCEPTIONS
    assert _run(tmp_path, _report(None), ["nope"])[0] == gate.EXIT_EXCEPTIONS
    assert _run(tmp_path, _report(None), {"version": 1})[0] == gate.EXIT_EXCEPTIONS
    assert _run(tmp_path, _report(None), {"version": 1, "exceptions": [], "x": 1})[0] == (
        gate.EXIT_EXCEPTIONS
    )


def test_the_committed_exceptions_file_is_valid_today() -> None:
    path = ROOT / "security" / "image-scan-exceptions.json"
    exceptions = gate.load_exceptions(path, dt.datetime.now(dt.UTC).date())
    assert isinstance(exceptions, list)


# --- SARIF and command line --------------------------------------------------------------------
def test_sarif_validation(tmp_path: Path) -> None:
    good = tmp_path / "ok.sarif"
    good.write_text(
        json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Trivy"}}}]})
    )
    assert gate.check_sarif(good, io.StringIO()) == gate.EXIT_PASS
    for body in (
        "",
        "{",
        json.dumps({"version": "2.0"}),
        json.dumps({"version": "2.1.0", "runs": []}),
    ):
        bad = tmp_path / "bad.sarif"
        bad.write_text(body)
        assert gate.check_sarif(bad, io.StringIO()) == gate.EXIT_INCOMPLETE
    assert gate.check_sarif(tmp_path / "missing.sarif", io.StringIO()) == gate.EXIT_INCOMPLETE


def test_the_command_line_returns_the_gate_exit_code(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_text(json.dumps(_report([_vuln()])))
    (tmp_path / "e.json").write_text(json.dumps({"version": 1, "exceptions": []}))
    base = [
        "gate",
        "--report",
        str(tmp_path / "r.json"),
        "--image-ref",
        IMAGE,
        "--image-key",
        "api",
        "--exceptions",
        str(tmp_path / "e.json"),
        "--today",
        TODAY.isoformat(),
    ]
    assert gate.main([*base, "--trivy-outcome", "success"]) == gate.EXIT_FINDINGS
    assert gate.main([*base, "--trivy-outcome", "failure"]) == gate.EXIT_INCOMPLETE
