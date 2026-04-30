# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `seo-aeo-geo-auditor`, please
**do not open a public GitHub issue.** Instead, email the maintainer
directly:

**brokerbusinesseu@gmail.com**

Include:

- A description of the issue
- Steps to reproduce
- The version / commit hash where you found it
- Optional: your proposed fix

You should expect a first-response acknowledgement within 5 business days.

## Scope

In-scope vulnerabilities include:

- **Path traversal** in `gui.py` (file serving from `reports/`)
- **Command injection** through subprocess invocations in any module
- **Server-Side Request Forgery (SSRF)** through user-supplied URLs
- **API-key leakage** in logs, reports, or HTTP responses
- **Memory-exhaustion DoS** via unbounded data structures (e.g. `JOBS` dict)
- **HTML injection / XSS** in generated `reports/*.html` files

Out of scope:

- Vulnerabilities in target sites being audited (those are the user's concern)
- Issues caused by user-installed third-party CLI tools (e.g. lighthouse)
- Self-XSS in the local GUI when the user is the operator

## Hardening already in place

- `gui.py` binds to `127.0.0.1` by default; opt-in only for other hosts
- File downloads validate the path resolves under `reports/` — no traversal
- Whitelisted file extensions for served files (`.html`, `.json`, `.md`,
  `.txt`, `.csv`)
- `JOBS` dict has TTL (1h) + max-entries cap (200)
- API keys never logged or written to reports
- All subprocess calls use `shell=False` and pass argv as a list

## Disclosure timeline

- Day 0: Report received
- Day ≤5: Acknowledgement
- Day ≤30: Patch released or detailed mitigation guidance issued
- Day +30: Public disclosure (coordinated with reporter)

## Credit

Researchers who report a valid issue will be credited in the
[CHANGELOG.md](CHANGELOG.md) entry for the fix release, unless they
prefer to remain anonymous.
