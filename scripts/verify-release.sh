#!/usr/bin/env bash
# =============================================================================
# SATRAK — Release Candidate verification
# =============================================================================
# Runs every automatable gate from the Release Candidate checklist (docs in
# RELEASE.md) and prints a pass/fail summary. Exits non-zero if any gate fails.
#
# Usage:  bash scripts/verify-release.sh
# Requires: the apps/api dev env installed (`make install-py`) or the tools on
# PATH (as in CI). Docker-based checks are reported as SKIPPED when Docker is
# absent — see docs/DOCKER_VALIDATION.md.
# -----------------------------------------------------------------------------
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
PASS=0 FAIL=0 SKIP=0

# Prefer the API virtualenv if present, else assume tools are on PATH (CI).
if [[ -x "$API_DIR/.venv/Scripts/python.exe" ]]; then
  PY="$API_DIR/.venv/Scripts/python.exe"
elif [[ -x "$API_DIR/.venv/bin/python" ]]; then
  PY="$API_DIR/.venv/bin/python"
else
  PY="python"
fi

check() { # check "name" <command...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m %s\n" "$name"; PASS=$((PASS + 1))
  else
    printf "  \033[31m✗\033[0m %s\n" "$name"; FAIL=$((FAIL + 1))
  fi
}
skip() { printf "  \033[33m•\033[0m %s (SKIPPED: %s)\n" "$1" "$2"; SKIP=$((SKIP + 1)); }

echo "SATRAK Release Candidate verification"
echo "======================================"

# Run backend/security checks from the API dir (no subshell, so counters persist).
cd "$API_DIR"

echo "[backend quality]"
check "ruff check"          "$PY" -m ruff check app tests
check "ruff format --check" "$PY" -m ruff format --check app tests
check "mypy (strict)"       "$PY" -m mypy app
check "import-linter"       "$PY" -m importlinter.cli lint
check "pytest + coverage"   "$PY" -m pytest -q

echo "[security]"
if "$PY" -c "import bandit" >/dev/null 2>&1; then
  check "bandit (SAST)" "$PY" -m bandit -q -c pyproject.toml -r app
else skip "bandit (SAST)" "not installed"; fi
if "$PY" -c "import pip_audit" >/dev/null 2>&1; then
  check "pip-audit (CVEs)" "$PY" -m pip_audit --skip-editable
else skip "pip-audit (CVEs)" "not installed"; fi

cd "$ROOT"
echo "[git]"
if [[ -z "$(git -C "$ROOT" status --porcelain)" ]]; then
  printf "  \033[32m✓\033[0m working tree clean\n"; PASS=$((PASS + 1))
else
  printf "  \033[31m✗\033[0m working tree has uncommitted changes\n"; FAIL=$((FAIL + 1))
fi

echo "[docker]"
if command -v docker >/dev/null 2>&1; then
  skip "compose stack up" "run manually: see docs/DOCKER_VALIDATION.md"
else
  skip "compose stack up" "docker not installed — see docs/DOCKER_VALIDATION.md"
fi

echo "======================================"
printf "PASS=%d  FAIL=%d  SKIP=%d\n" "$PASS" "$FAIL" "$SKIP"
[[ "$FAIL" -eq 0 ]] || { echo "Release verification FAILED"; exit 1; }
echo "Release verification PASSED (see SKIP items for manual/Docker checks)"
