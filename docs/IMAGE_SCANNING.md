# Container image scanning

CI scans the API and Web images with [Trivy](https://github.com/aquasecurity/trivy) in the `image-scan`
job. Trivy only scans; `scripts/ci/image_scan_gate.py` decides pass or fail, so the policy is in one reviewed,
unit-tested place (`apps/api/tests/ci/test_image_scan_gate.py`).

## Policy

| Situation                                                                                                    | Result                                     | Exit code |
| ------------------------------------------------------------------------------------------------------------ | ------------------------------------------ | --------- |
| No un-excepted **fixable** HIGH or CRITICAL finding                                                          | pass                                       | 0         |
| A fixable HIGH or CRITICAL finding with no valid exception                                                   | `VULNERABILITIES FOUND`, job fails         | 1         |
| Trivy step failed, DB or network error, missing or untrustworthy report, report for another image, bad SARIF | `SCAN INCOMPLETE`, job fails (fail closed) | 2         |
| Exceptions file invalid, or any exception expired                                                            | `EXCEPTION POLICY VIOLATION`, job fails    | 3         |

- **Fixable** means the Trivy report names a fixed version for the package. Rebuilding on a newer base image
  or upgrading the package is then possible. Unfixed HIGH/CRITICAL findings are printed as
  `UNFIXED (not gating)` and stay in the JSON and SARIF reports; they do not fail CI.
- MEDIUM, LOW and UNKNOWN findings are not gated.
- A scanner problem is never a pass and never a waiver. The Trivy step uses `continue-on-error` only so the
  gate can print `SCAN INCOMPLETE`; the gate step always runs and fails unless Trivy succeeded.
- Order of checks: scanner/report problems (2), then exception policy (3), then findings (1).
- JSON and SARIF reports are kept as workflow artifacts for 30 days (`trivy-api`, `trivy-web`). They are not
  uploaded to GitHub code scanning.

## Exceptions

`security/image-scan-exceptions.json` is empty. An entry excuses one vulnerability in one package on one
image (`api` or `web`) and must contain:

`id` (CVE or advisory id), `package`, `image`, `justification` (why it cannot be exploited here or why no
upgrade is possible yet), `owner`, `approver` (a different person), `created`, `expires`.

Rules, enforced by the gate: all fields required and no unknown fields; `expires` after `created` and at most
**90 days** after it; `created` not in the future; no duplicates. An expired entry fails CI even if the
vulnerability has gone, so entries are removed or consciously renewed (a new `created` and a new review).
Exceptions are added only through a reviewed pull request.

## Scanner choice and supply chain

Trivy: Apache-2.0, scans OS and language packages in one pass, native GitHub Actions support, SARIF, active
maintenance. Grype was the alternative. In March 2026 Trivy's release and the tags of `trivy-action` and
`setup-trivy` were compromised ([Aqua advisory](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know)),
so nothing here is referenced by tag:

- `aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1` is `v0.35.0`, the one action version Aqua
  lists as unaffected. The commit is dated 2026-03-04, before the incident. Its `action.yaml` pins
  `setup-trivy` (`e6c2c5e3…`, v0.2.4) and `actions/cache` by SHA, and defaults to Trivy `v0.69.3`; the workflow
  also sets `version: v0.69.3` explicitly. Aqua lists v0.69.2–v0.69.3 as safe.
- Verified when added: `git ls-remote` showed the `v0.35.0` tag at that SHA and the commit object was fetched
  by SHA. The SHA of `setup-trivy@e6c2c5e3…` is not one of the malicious commits Aqua lists; its content was
  not independently audited.
- To upgrade: choose a release newer than the advisory, review the diff of `action.yaml` and the pinned
  dependencies, and replace the SHA and comment together.

## Limits

This scans the two built images. It does not scan the compose-only images (`postgis`, `redis`, `node` dev
server), a future worker image, or running infrastructure, and says nothing about application-level flaws.
Scheduled re-scans of already-merged images are not configured. Vulnerability data comes from Trivy's
database, downloaded at scan time; a failed download is `SCAN INCOMPLETE`.
