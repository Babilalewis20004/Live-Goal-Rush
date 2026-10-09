# Security scanning

None of Bandit, pip-audit, Semgrep, Gitleaks or Trivy was configured in the repository before Phase 7 (there was no CI at all),
so nothing was removed; all five are now part of `.github/workflows/ci.yml`. This page records what each one found on
**2026-10-08** and how to run it by hand.

| Tool | Scope | How to run | Result on 2026-10-08 |
|---|---|---|---|
| **Bandit** | `apps/api/app` (18,038 lines) | `pip install bandit && bandit -r apps/api/app -ll` | 0 high, 0 medium, 19 low (reviewed; `accepted-risks.md` S-21). Before fixes: 3 high (SHA-1 fingerprints ×2, hidden bidirectional characters in the HTML sanitiser regex), 1 medium |
| **pip-audit** | the 74 exact versions in `apps/api/constraints.txt` | `pip-audit -r apps/api/constraints.txt --no-deps --disable-pip` | **0 vulnerabilities.** Before: 35 in Pillow 11.3.0 (S-2) |
| **npm audit** (existing) | web + mobile | `npm audit --omit=dev` | web production: **0** (was 1 critical + 9 high, S-3). Mobile: 0 critical, 49 high in dev/build tooling (accepted, S-22) |
| **Semgrep** | api, web, mobile source — 261 rules (`p/python`, `p/typescript`, `p/secrets`) on 418 files | `semgrep scan --config p/python --config p/typescript --config p/secrets apps/…` | 0 errors, 5 warnings, all false positives (S-21) |
| **Gitleaks** | full git history, 13 commits | `gitleaks detect --source . --redact` | **no leaks flagged** — but see S-1: a provider API key *is* committed and Gitleaks cannot recognise it (no known token pattern). Treat "no leaks" as necessary, not sufficient |
| **Trivy** | `live-goal-api`, `live-goal-web` images (vuln + secret scanners) | `trivy image --scanners vuln,secret --severity HIGH,CRITICAL <image>` | web: **0 high/critical, 0 secrets**; api: 0 critical, 44 high (Debian base, none fixable yet, S-23), 0 secrets. Before: web 1 critical + 26 high (npm's bundled packages, base-image OpenSSL) |

## Reading a failure in CI

* **Bandit / Semgrep** — fix the code, or add `# nosec B###` / `# nosemgrep: rule-id` with a comment saying *why it is safe*; unexplained suppressions should be refused in review.
* **pip-audit** — raise the floor in `requirements.txt`, regenerate `constraints.txt`, run the backend tests. If no fix exists, record it in `accepted-risks.md` with a review date.
* **npm audit (web)** — `npm update <pkg>` or `npm install <pkg>@<fixed>`; if the package is only a build tool, make sure it is in `devDependencies`.
* **Trivy** — rebuild (picks up OS patches); `--ignore-unfixed` means CI fails only when a fix exists.
* **Gitleaks** — rotate the secret *first*, then remove it; removing it from the tree does not remove it from history.

## Tools deliberately not added
Dependabot/Renovate (schedule a weekly dependency PR run — recommended, not configured), DAST against a deployed staging, and a
dedicated software-composition-analysis service. The CI jobs above cover the same ground for a project this size.
