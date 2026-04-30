# Changelog

All notable changes to this project will be documented in this file.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-04-30

This release is a comprehensive bug-fix + repo-hardening pass before
opening the project to the public. All known CRITICAL, HIGH, and MEDIUM
issues from internal code review are resolved.

### Added

- **`gui.py`** — local web GUI: one URL field, one button, full report.
  Async job runner with TTL-bounded `JOBS` dict (1h, max 200 entries).
- **`aeo_probe.py`** — real LLM citation tracker. Fires queries at 5
  providers (OpenAI, Anthropic, DeepSeek, xAI, Gemini), measures whether
  the target domain is cited, position, link presence, sentiment.
  Auto-loads keys from `C:\PYTHON\token\Api_AI.txt` or env vars.
- **`auditor_advanced.py::_meta_get()`** — attribute-order-agnostic
  `<meta>` parser; works with `property=...content=...` and reverse, plus
  `name=` instead of `property=`, plus self-closing tags.
- Public-repo scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.env.example`,
  `requirements-dev.txt`, GitHub Actions CI workflow,
  Dependabot config, issue + PR templates, FUNDING placeholder.

### Fixed

#### Critical / High

- `gui.py` — **JOBS unbounded memory growth** patched with TTL (1h) +
  max-entries cap (200) + cleanup hook on each `/start`.
- `gui.py` — **path traversal hardened**: validates resolved path under
  `REPORTS_DIR` (not just `HERE`), adds `OSError` to except clause,
  whitelists served extensions (`.html`, `.json`, `.md`, `.txt`, `.csv`),
  rejects NUL-byte input, sanitizes `Content-Disposition` header.
- `monitor.py` — `v_score` `UnboundLocalError` when validator absent.
- `monitor.py` — slug sanitization for arbitrary URLs.
- `fixer.py` — `site_name.split()[0]` IndexError on empty site name.
- `fixer.py` — `replace("/index.html", "/")` was global; scoped to
  trailing-slash-only context.
- `validator.py` — `datetime.utcnow()` deprecated; replaced with
  `datetime.now(timezone.utc)`.
- `auditor_advanced.py` — FOG-PL scale was missing the `<5` (very-easy)
  level; complete Pisarek 1969 scale now mapped.
- `auditor_advanced.py` — contrast logic was filtering legitimate
  dark-on-dark pairs; replaced with semantic light+dark pairing.
- `auditor.py` — robots.txt regex DOTALL caused over-matching across
  user-agent blocks; bounded to single block.
- `pagespeed.py` — dead code in URL building when `--api-key` provided.
- `aeo_probe.py` — `has_url` second OR condition was unreachable.
- `aeo_probe.py` — rolling-average bug (replaced with `_pos_sum` /
  `_pos_count` accumulator).

#### Medium

- `fixer.py` — Google Fonts URL replace could clobber URLs in CSS
  comments; now strips `/* */` before parsing and replaces only inside
  `url(...)` context.
- `fixer.py` — added explicit `OSError` handler around
  `local_path.write_bytes()` for permission/disk errors.
- `auditor_advanced.py` — `META_DATE` regex required strict
  `property=...content=...` order; replaced with attribute-order-agnostic
  helper `_meta_get()`.
- `report_html.py` — module-section detector matched only `JAKOŚĆ`
  (with diacritics) but `auditor.py` emits ASCII `JAKOSC`; both forms now
  recognized.
- `aeo_probe.py::_http_post_json` — on `HTTPError`, now reads the
  response body (max 500 chars) and re-raises with status + body for
  clearer diagnostics on provider errors.
- `keyword_strategy.py` — duplicate Polish stopwords cleaned up;
  `PL_STOPWORDS` now `frozenset` of 312 unique entries.
- `aeo_probe.py` — citation deduplication: brand vs domain double-count
  fixed via overlap detection in `match_ranges`.
- `aeo_probe.py` — auto-load API keys always (not only when env unset).
- `aeo_probe.py` — Gemini fallback chain
  (`gemini-2.5-flash` → `2.0-flash` → `1.5-flash-002` → `1.5-flash`).
- `aeo_probe.py` — DeepSeek fallback chain
  (`deepseek-chat` → `deepseek-v3` → `deepseek-coder`).
- `aeo_probe.py` — xAI temperature parameter retry without temperature
  on 400 response.
- All modules — UTF-8 stdio reconfigure block added; eliminates
  `UnicodeEncodeError` on Windows cp1250 default.

### Changed

- `requirements.txt` — clarified that runtime is stdlib-only; optional
  external integrations documented separately.
- `keyword_strategy.py::PL_STOPWORDS` — changed from `set` to
  `frozenset` (immutability).
- `gui.py::INDEX_HTML` — refactored to single URL field + single button
  (was multi-field form).

### Security

- `gui.py` — defense-in-depth on file serving: traversal-resistant path
  resolution, extension whitelist, header-injection-safe filenames.
- All modules — no API keys read from request bodies; only env-vars or
  `.env` file mounted by user.

---

## [0.1.0] — 2026-04-28 — initial release

### Added

- `auditor.py` — main audit, 8 modules (URL or local folder)
- `auditor_advanced.py` — Performance + A11y (WCAG 2.2) + Content
  quality (FOG-PL Pisarek 1969)
- `validator.py` — schema.org JSON-LD validator for 30+ types
- `keyword_strategy.py` — TF-IDF per article, cannibalization detection,
  Jaccard topic clusters, merit score, content gap suggestions
- `fixer.py` — auto-fix engine for 7 areas (ai_files, robots, sitemap,
  security, pwa, fonts, schema) with safe `_fixed/` copy
- `pagespeed.py` — Google PageSpeed Insights API integration
- `monitor.py` — history snapshots + diff reporter + SMTP alerts +
  Windows Task Scheduler integration
- `report_html.py` — visual HTML report with embedded Chart.js
- `ai_bots.py` — canonical list of 26 AI crawlers (April 2026)
- `templates.py` — file templates (OWASP A+ `.htaccess`, manifest,
  service worker, `ai.txt`)

### Initial verified results on `zdrowie.fit`

- `auditor.py` main score: 70% → 100% (after applied fixes)
- `validator.py`: 10 errors / 104 warnings → 0 errors / 9 warnings
- Citation density per article: 0 → 8–14
- Google PageSpeed Insights: Performance 98, A11y 96, Best Practices 100,
  SEO 100. LCP 1.5 s, CLS 0, TBT 0 ms (mobile).

[Unreleased]: https://github.com/brokerbusinesseu/seo-aeo-geo-auditor/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/brokerbusinesseu/seo-aeo-geo-auditor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/brokerbusinesseu/seo-aeo-geo-auditor/releases/tag/v0.1.0
