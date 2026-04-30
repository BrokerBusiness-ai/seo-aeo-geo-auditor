# seo-aeo-geo-auditor

> Open-source toolkit that audits a website for **SEO + AEO + GEO** readiness — and tests real LLM citation rate against your pages. Pure Python 3.10 stdlib, zero runtime dependencies.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen.svg)]()
[![Status](https://img.shields.io/badge/status-active-success.svg)]()

---

## What is this?

A unified auditor for the three optimization layers that matter in 2026:

| Layer | What it covers | Example checks |
|---|---|---|
| **SEO** | Classic search engines | Schema.org JSON-LD, sitemap, robots, security headers |
| **AEO** | Answer Engine Optimization (Google AI Overviews, Bing Copilot) | FAQ structure, citation density, fact density, freshness |
| **GEO** | Generative Engine Optimization (ChatGPT, Claude, Perplexity) | 26 AI-bot crawler access, llms.txt, llms-full.txt, Speakable |

Plus an **AEO Active Probe** that fires real queries at 5 LLM providers (OpenAI, Anthropic, DeepSeek, xAI, Gemini) and measures whether your domain is actually being cited.

---

## Quick start

```bash
# Clone
git clone https://github.com/<your-handle>/seo-aeo-geo-auditor.git
cd seo-aeo-geo-auditor

# Audit any URL — full pipeline, HTML report
python gui.py --open
# → opens http://127.0.0.1:8765 — paste URL, click button, get report
```

CLI alternative:

```bash
python auditor.py https://example.com --md report.md --json report.json
python auditor_advanced.py https://example.com --json adv.json
python validator.py https://example.com --md val.md
python keyword_strategy.py https://example.com --md kw.md
python aeo_probe.py --domain example.com --topic "your topic" --md probe.md
```

---

## Features

### 12 audit modules

| # | Module | What it checks |
|---|---|---|
| 1 | `auditor.py` | 8 SEO/AEO/GEO core groups — files, robots, schema, sitemap, security, PWA, fonts, content quality |
| 2 | `auditor_advanced.py` | Performance (HTML weight, image formats), A11y (lang, landmarks, headings), Content (FOG-PL readability, fact density, citation density, freshness) |
| 3 | `validator.py` | Schema.org JSON-LD validator for 30+ types with cross-reference checks |
| 4 | `pagespeed.py` | Google PageSpeed Insights API integration (real Lighthouse scores) |
| 5 | `keyword_strategy.py` | TF-IDF keyword extraction + topical clustering (Jaccard) |
| 6 | `fixer.py` | Auto-fix engine: missing schema, security headers, self-host fonts, llms.txt generation |
| 7 | `aeo_probe.py` | **The differentiator.** Real LLM citation tracking across 5 providers |
| 8 | `monitor.py` | History snapshots + diff between runs |
| 9 | `gui.py` | Local web GUI — one URL, one button, full report |
| 10 | `report_html.py` | Self-contained HTML report (Chart.js inline, print-to-PDF ready) |
| 11 | `templates.py` | OWASP A+ `.htaccess`, `manifest.json`, `sw.js`, `ai.txt` generators |
| 12 | `ai_bots.py` | Reference list of 26 AI crawlers (April 2026) |

### Why "the AEO probe is the differentiator"

Most OSS SEO tools check infrastructure. The probe checks **outcome**: it asks 10 real questions about your topic to 5 different LLM providers and measures:

- Whether your domain is cited (binary)
- Position in the response (early = better)
- Whether the URL is rendered as a clickable link
- Sentiment of the mention (positive / neutral / negative)
- Aggregate citation rate per provider

Output: `probe.md` table with citation rate per LLM, plus a JSON dump for downstream automation.

---

## Installation

### Requirements

- Python 3.10+ (uses `str | None` PEP 604 syntax)
- Optional: Lighthouse CLI (`npm install -g lighthouse`) for offline performance scoring
- Optional: API keys (see `.env.example`)

### Setup

```bash
git clone https://github.com/<your-handle>/seo-aeo-geo-auditor.git
cd seo-aeo-geo-auditor

# Copy env template and fill in keys you have
cp .env.example .env
# edit .env — at minimum PSI_API_KEY for PageSpeed; add LLM keys if using probe

# (optional) dev tools
pip install -r requirements-dev.txt
```

### Loading API keys (Windows PowerShell)

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^([A-Z_]+)=(.+)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), "Process")
    }
}
```

### Loading API keys (Linux/macOS)

```bash
set -a; source .env; set +a
```

---

## Usage examples

### Single-URL audit (GUI, recommended)

```bash
python gui.py --port 8765 --open
```

Opens a single-field web form. Paste URL, click button, watch progress, get HTML + JSON reports in `reports/`.

### Full CLI pipeline

```bash
URL="https://example.com"

python auditor.py "$URL" --pages 15 --md main.md --json main.json
python auditor_advanced.py "$URL" --pages 10 --json adv.json
python pagespeed.py "$URL" --strategy mobile --json psi.json
python validator.py "$URL" --md val.md --json val.json
python keyword_strategy.py "$URL" --md kw.md --json kw.json
```

### AEO probe (real LLM citation test)

```bash
python aeo_probe.py \
    --domain example.com \
    --brand "Example Inc." \
    --topic "your industry topic" \
    --max-queries 10 \
    --md probe.md \
    --json probe.json
```

Cost: ~$0.05–0.15 per 10-query run across 5 providers (mostly OpenAI mini + Anthropic Haiku tier).

### Auto-fix a local site

```bash
python fixer.py /path/to/built/site --json fix-log.json
```

Adds missing security headers, generates `llms.txt`, downloads Google Fonts to local `/fonts/`, ensures `manifest.json` + `sw.js` etc.

### Monitor over time

```bash
python monitor.py https://example.com --compare-last
```

Compares current run with the previous snapshot, surfaces regressions.

---

## Sample output

After running the GUI on a well-optimized site:

```
═══════════════════════════════════════════════════════════
  SEO / AEO / GEO AUDITOR
═══════════════════════════════════════════════════════════
  PERFORMANCE   96/100
  A11Y          86/100
  CONTENT       62/100
  MAIN SCORE    98%
  VALIDATOR     0 errors / 0 warnings
═══════════════════════════════════════════════════════════
```

The HTML report (auto-generated) groups findings by module with pass/fail/warn statuses, score gauges, and remediation hints.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                            gui.py                                │
│            (HTTP server — one URL → one button → report)         │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
   ┌───────────▼─────────────┐    ┌───────────▼─────────────┐
   │      audit pipeline     │    │      report builder     │
   │                         │    │                         │
   │  pagespeed.py           │    │  report_html.py         │
   │  auditor.py             │    │  (Chart.js, print-PDF)  │
   │  auditor_advanced.py    │    └─────────────────────────┘
   │  validator.py           │
   └─────────────────────────┘

   ┌─────────────────────────────────────────────────────────────┐
   │                  Standalone tools (CLI)                      │
   │  aeo_probe.py | keyword_strategy.py | fixer.py | monitor.py  │
   └─────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────┐
   │                          Shared                              │
   │             ai_bots.py (26 bots) | templates.py              │
   └─────────────────────────────────────────────────────────────┘
```

---

## What's tracked vs. what's not

**Tracked by this tool:**

- Technical readiness for SEO / AEO / GEO
- Schema.org correctness and coverage
- Content structural quality (FOG-PL, FAQ format, citation density)
- Real LLM citation rate (probe)
- Performance (via Google PSI)
- Accessibility basics

**Out of scope (use other tools):**

- Google rankings → Search Console / Ahrefs
- Backlink profile → Ahrefs / Majestic
- Conversion analytics → GA4 / Plausible
- Page-level UX → manual / Hotjar

The probe is the closest thing to a "rank tracker" for the LLM era — it measures *outcome* (citations), not just *infrastructure*.

---

## Documentation

- [`CHANGELOG.md`](CHANGELOG.md) — version history
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — community standards
- [`docs/`](docs/) — module-by-module reference

---

## Polski / Polish

Open-source narzędzie do audytu i naprawy stron WWW pod **SEO** (klasyczne wyszukiwarki), **AEO** (Answer Engine Optimization — Google AI Overviews, Bing Copilot) oraz **GEO** (Generative Engine Optimization — ChatGPT, Claude, Perplexity). Powstało jako wewnętrzne narzędzie ARCHAIOS Demand Engine, otwarte do publicznego użytku.

Najszybszy start:

```powershell
git clone https://github.com/<twoj-handle>/seo-aeo-geo-auditor.git
cd seo-aeo-geo-auditor
copy .env.example .env
# edytuj .env — dodaj klucze (przynajmniej PSI_API_KEY)
python gui.py --open
```

Otworzy się `http://127.0.0.1:8765`. Wpisujesz URL → klikasz przycisk → masz raport HTML w `reports/`.

Pełna lista modułów i komend wyżej (sekcja angielska).

---

## License

MIT — see [LICENSE](LICENSE).

## Author

Marek Porycki — psychologist, writer, builder.
GitHub: [@brokerbusinesseu](https://github.com/brokerbusinesseu)

## Contributing

Pull requests welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md) first. For security issues, see [SECURITY.md](SECURITY.md).
