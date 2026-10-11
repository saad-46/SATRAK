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

## Remediation of the first scan findings

The first scan (CI run 38100711785) reported 4 fixable findings in the API image and 52 in the Web
image. They were remediated, not excepted; the policy and the gate are unchanged:

| Finding group                                              | Origin                                                           | Remediation                                                                                                        |
| ---------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| API: `msgpack`, `urllib3` (2 CVEs)                         | pip's vendored copies inside `/opt/venv`                         | pip is removed from the venv before it is copied into the runtime stage                                            |
| API: `setuptools`                                          | Python base image site-packages                                  | pip, setuptools and wheel are removed from the runtime stage; the build fails if any is still importable           |
| Web: Debian packages (17)                                  | `node:20-slim` is Node 20 (end of life) and is no longer rebuilt | Node 22 on `node:22-trixie-slim`, pinned by digest                                                                 |
| Web: npm-bundled `tar`, `glob`, `minimatch`, ... (22)      | npm shipped inside the base image                                | npm, npx, corepack and yarn are removed from the runtime stage; the build fails if any is still on `PATH`          |
| Web: `next`, `sharp`, `postcss`, `nanoid`, `source-map-js` | application lock file                                            | `next` 15.5.27, `sharp` 0.35.5, and `pnpm.overrides` `next>postcss` = 8.5.29 (Next 15 pins postcss 8.4.31 exactly) |

Follow-up changes after the first green scan: the API runtime stage no longer installs `libgdal-dev`,
`libgeos-dev` or `curl` (no GDAL/GEOS binding is locked or imported; the `HEALTHCHECK` is
`apps/api/healthcheck.py`), and the Web smoke job now lists every installed copy of `next`, `sharp`,
`postcss`, `nanoid` and `source-map-js` from inside the running image and compares them with the
approved floors in `scripts/ci/check_web_versions.py` and with `pnpm-lock.yaml`. `next` vendors
unversioned copies of some libraries under `next/dist/compiled/`; the check lists them as `VENDORED`
because their version cannot be read from the image.

Only a CI scan of the exact images proves these fixes; this section is a description, not evidence.

Reproducibility trade-off: the Web base is pinned by digest, so builds are repeatable but do not pick
up new Debian patches until the digest is bumped (Dependabot's `docker` ecosystem proposes the bump
weekly). The alternative, an unpinned `apt-get upgrade`, was rejected because the same commit would
build different images. The API base is pinned by tag only and picks up patches on each rebuild.

## Limits

This scans the two built images. It does not scan the compose-only images (`postgis`, `redis`, `node` dev
server), a future worker image, or running infrastructure, and says nothing about application-level flaws.
Scheduled re-scans of already-merged images are not configured. Vulnerability data comes from Trivy's
database, downloaded at scan time; a failed download is `SCAN INCOMPLETE`.
