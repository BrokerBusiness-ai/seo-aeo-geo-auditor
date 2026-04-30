# Architecture

This document explains how the modules fit together and why each one exists.

## Three layers, twelve modules

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ENTRY LAYER                                  │
│                                                                       │
│   gui.py            ← HTTP server + one-URL-one-button SPA           │
│   <CLI of any module>  ← direct subprocess invocation                │
└──────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       AUDIT LAYER                                     │
│                                                                       │
│   auditor.py             ← 8 SEO/AEO/GEO core groups                 │
│   auditor_advanced.py    ← Performance + A11y + Content quality      │
│   validator.py           ← schema.org JSON-LD checker (30+ types)    │
│   pagespeed.py           ← Google PSI API wrapper                    │
│   keyword_strategy.py    ← TF-IDF + Jaccard clusters                 │
│   aeo_probe.py           ← real LLM citation tracker (5 providers)   │
└──────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       OUTPUT LAYER                                    │
│                                                                       │
│   report_html.py         ← single-file HTML with Chart.js inline     │
│   monitor.py             ← snapshots + diffs                         │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                       SHARED / FIX LAYER                              │
│                                                                       │
│   fixer.py               ← auto-fix engine                           │
│   templates.py           ← htaccess / manifest / sw.js generators    │
│   ai_bots.py             ← canonical 26-bot reference list           │
└──────────────────────────────────────────────────────────────────────┘
```

## Data flow for `gui.py` job

```
POST /start { url }
   │
   ├── _cleanup_jobs()     ← TTL + max-entries pruning
   │
   ├── allocate job_id     ← timestamped key in JOBS
   │
   ├── threading.Thread → run_audit_job(job_id, url)
   │       │
   │       ├── pagespeed.py       (subprocess, JSON output)
   │       ├── auditor.py         (subprocess, JSON output)
   │       ├── auditor_advanced.py(subprocess, JSON output)
   │       └── validator.py       (subprocess, JSON output)
   │
   ├── build_html_report(url, results) → report_html.py
   │
   └── JOBS[job_id]["done"] = True
                "_finished_at" = time.time()

Browser polls /status?job=<id> until done, then redirects to /view?path=<html>.
```

## Why each module exists

### `auditor.py` — the entry-level scan

Eight modules, each binary pass/fail/info:

1. **PLIKI AI** — `llms.txt`, `llms-full.txt`, `ai.txt`
2. **ROBOTS.TXT** — 26 AI crawlers, sitemap declaration, `llms.txt` reference
3. **SCHEMA MARKUP** — JSON-LD presence + types (Article, Organization, etc.)
4. **SITEMAP** — XML well-formed, image namespace, lastmod, changefreq, priority
5. **BEZPIECZEŃSTWO** — HSTS, CSP, X-Frame, X-CTO, Referrer-Policy, compression
6. **PWA** — manifest, service worker
7. **FONTY** — self-hosted vs Google Fonts CDN
8. **JAKOŚĆ TREŚCI** — H2 questions count, bibliography presence, OG image, nosnippet

Output: human-readable terminal output + optional `--json` machine output.

### `auditor_advanced.py` — the diagnostic deep-dive

Three independent submodules running in sequence:

- **Performance** — HTML weight, image format coverage (WebP/AVIF), `<picture>` usage, lazy loading, font preload, alt presence
- **A11y** — `<html lang>`, skip links, alt text quality, single-H1, header hierarchy, landmarks, label/aria-label coverage on inputs
- **Content** — FOG-PL readability (Pisarek 1969 formula), sentence-length distribution, fact density (numbers + proper names + years per 100 words), citation density (DOI + URL pattern matches per 1000 words), H2-as-question ratio, TL;DR presence

Each submodule outputs an independent score 0–100; final report shows all three.

### `validator.py` — the schema correctness checker

Goes beyond presence: validates *cross-references* between schema entities. If `Article.publisher.@id` references an `Organization`, that Organization must actually exist in the page's JSON-LD graph. Catches the "I have schema but it's broken" class of bugs that other tools miss.

30+ supported types include the Speakable extension and the AEO-relevant types (FAQPage, HowTo, ClaimReview).

### `pagespeed.py` — outsourced performance scoring

Wraps the Google PSI API. Returns Lighthouse Performance, A11y, Best Practices, SEO scores plus Core Web Vitals (LCP, INP, CLS). Free 25k calls/day with API key.

### `keyword_strategy.py` — content strategy advisor

- **TF-IDF** per article — what words define each page
- **Jaccard similarity** — which articles cluster topically
- **Cannibalization detection** — pages competing for the same query
- **Content gap** — Polish stopwords filtered (312 entries), suggests missing semantic neighbors

### `aeo_probe.py` — the differentiator

Sends 10 queries (auto-generated from `--topic` or read from `--queries-file`) to 5 LLM providers. Per response, measures:

- Whether `<domain>` or `<brand>` appears (citation = yes/no)
- Position in the response text (early = stronger signal)
- Whether the URL is rendered as `<a href>` or just plain text mention
- Sentiment (positive / neutral / negative — keyword-based)
- Aggregate per-provider citation rate

This is **the only module that measures outcome**, not infrastructure.

### `fixer.py` — the remediation engine

Reads the audit findings and writes patches:

- Generates `llms.txt`, `llms-full.txt`, `ai.txt` from page content
- Adds missing security headers via `.htaccess` template
- Downloads Google Fonts to `/fonts/` and rewrites CSS
- Adds missing schema scaffolding (Organization, BreadcrumbList)
- Generates `manifest.json` and `sw.js` for PWA

Always operates on a `_fixed/` copy — never mutates the input.

### `monitor.py` — temporal awareness

Stores compact snapshots of audit JSON. `--compare-last` produces a diff:
"score went from 92 to 87, the regression is in the A11y module on /pricing".

### `gui.py` — the friction killer

The reason the project exists in this shape. CLI is fine for developers; the GUI is for everyone else. One field, one button, full report. No flags, no config.

### `report_html.py` — the deliverable format

Self-contained HTML (Chart.js loaded from CDN, no other external assets). Print-to-PDF ready. The format you actually send to a client.

## Design principles

1. **Stdlib only at runtime.** No `pip install` dance. The tool runs.
2. **Fail visible, not silent.** Every module surfaces errors prominently. Better to scream than to swallow.
3. **Idempotency.** Run the auditor twice in a row → identical output (modulo timestamps).
4. **One responsibility per module.** `auditor.py` does not call `validator.py`; the GUI does the orchestration.
5. **No hidden network calls.** Outbound HTTP only to (a) the URL being audited, (b) explicit API integrations the user activated via key.

## Where to look in the code

| Looking for... | Open... |
|---|---|
| The GUI HTML/CSS/JS | `gui.py::INDEX_HTML` |
| The job runner | `gui.py::run_audit_job` |
| Schema rules | `validator.py::TYPE_RULES` |
| FOG-PL formula | `auditor_advanced.py::flesch_pisarek_pl` |
| Citation pattern matching | `aeo_probe.py::detect_citation` |
| AI bots reference list | `ai_bots.py` |
