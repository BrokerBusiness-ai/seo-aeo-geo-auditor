# Contributing to seo-aeo-geo-auditor

Thanks for considering a contribution. This project is intentionally
small-surface and stdlib-only — please respect that constraint when
proposing changes.

## Ground rules

- **No new runtime dependencies.** The project must remain installable with
  `pip install -r requirements.txt` resulting in zero packages installed.
  Dev tools (ruff, mypy, etc.) belong in `requirements-dev.txt` only.
- **Python 3.10+ syntax allowed.** PEP 604 unions (`str | None`),
  structural pattern matching, and modern f-strings are fine.
- **Windows + Linux compatibility.** The tool runs in PowerShell, cmd,
  bash, zsh. Avoid `os.path` operations that break on Windows; prefer
  `pathlib.Path`. Do not assume `/` separator in user-visible paths.
- **No telemetry, no callouts.** The tool runs locally. The only outbound
  HTTP must be either (a) the URL the user is auditing, or (b) explicit
  API integrations the user opted into via API keys.

## Development setup

```bash
git clone https://github.com/<your-handle>/seo-aeo-geo-auditor.git
cd seo-aeo-geo-auditor
cp .env.example .env  # fill in keys you have
pip install -r requirements-dev.txt
```

## Before opening a PR

Run the full local check:

```bash
# 1. Bytecode-compile every module — must pass
python -m py_compile auditor.py auditor_advanced.py validator.py \
    fixer.py monitor.py pagespeed.py aeo_probe.py report_html.py \
    templates.py ai_bots.py keyword_strategy.py gui.py

# 2. Lint (optional but appreciated)
ruff check .

# 3. Type-check (optional)
mypy --ignore-missing-imports .

# 4. Smoke test on a public site you own permission to audit
python auditor.py https://example.com --pages 3 --json /tmp/smoke.json
```

If your change touches a module that has a CLI, make sure `--help` still
parses (`python <module>.py --help`).

## Pull request guidelines

- One logical change per PR. Refactors and feature additions stay
  separate.
- Update `CHANGELOG.md` under an `[Unreleased]` section.
- If the PR adds a new check or audit dimension, add a one-line summary
  to the relevant section in `README.md`.
- Keep commit messages in conventional style:
  `fix: <scope>: <message>` / `feat: <scope>: ...` / `docs: ...`
- Squash trivial WIP commits before requesting review.

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Please
include:

- Python version (`python --version`)
- OS and shell
- Exact command line
- Full stderr (redact API keys)
- Whether the target URL is publicly reachable

## Proposing features

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md).
Bonus points for citing the SEO/AEO/GEO research backing the proposal
(Princeton GEO 2024, Google AI Overviews documentation, schema.org spec,
etc.).

## Security

Don't open public issues for security problems. See [SECURITY.md](SECURITY.md).

## Code style

The codebase intentionally favors:

- Long, descriptive function names over abbreviations
- Polish/English bilingual docstrings where useful (most users are PL)
- Inline regex with named groups when complex
- `dataclasses.dataclass` for shaped records
- `pathlib.Path` over `os.path`
- Unicode source — UTF-8 everywhere; never assume cp1250 on Windows

If you introduce a complex helper, add a smoke test in `examples/`.
