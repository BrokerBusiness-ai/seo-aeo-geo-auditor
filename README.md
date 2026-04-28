# seo-aeo-geo-auditor

Narzędzie do audytu i auto-fix SEO / AEO / GEO dla stron statycznych i live URL.
Czysty Python stdlib, brak zewnętrznych zależności.

Powstało jako wewnętrzne narzędzie do audytu sieci domen ARCHAIOS Demand Engine
(zdrowie.fit, jaksobieradzic.pl, psychodzisiaj.pl, psychosen.pl,
sprawdzwypalenie.pl, wppage.pl i inne).

---

## Co audytuje

**SEO (klasyczne)** — robots.txt, sitemap.xml, JSON-LD schema, canonical, meta,
nagłówki bezpieczeństwa (HSTS, CSP, X-Frame), kompresja, cache, fonty self-hosted.

**AEO (Answer Engine Optimization)** — pliki `llms.txt` / `llms-full.txt` /
`ai.txt` (Spawning), schematy `FAQPage`, `HowTo`, `SpeakableSpecification`,
`ClaimReview`, `Person.sameAs`, fact density, citation density, H2-pytania.

**GEO (Generative Engine Optimization)** — dostęp dla 26 botów AI 2026
(GPTBot, ChatGPT-User, OAI-SearchBot, ClaudeBot, Claude-Web, claude-searchbot,
PerplexityBot, Perplexity-User, Google-Extended, GoogleOther,
Applebot-Extended, Amazonbot, Bytespider, CCBot, Meta-ExternalAgent,
Meta-ExternalFetcher, cohere-ai, Diffbot, MistralAI-User, DuckAssistBot,
YouBot, Timpibot, omgili, omgilibot, ImagesiftBot).

**Performance / CWV** (przez Google PSI) — LCP, INP, CLS, TBT, TTI,
Opportunities z impactem ms/KB.

**Accessibility** — WCAG 2.2 AA: alt text, hierarchia nagłówków,
landmarks, kontrast (parser CSS variables + heurystyka kontrastującej pary),
form labels, skip links, lang.

**Content quality** — FOG-PL (formuła Pisarka 1969 dla polskiego),
średnia długość zdania, fact density, citation density, TL;DR detection,
H2-pytania ratio, freshness signal.

**Keyword strategy** — TF-IDF per artykuł, cannibalization detection,
topical clusters (Jaccard + min-shared-keywords), content gap suggestions,
merit score 0-100 per artykuł.

---

## Moduły

| Plik | Co robi | Wymaga |
|---|---|---|
| `auditor.py` | Główny audyt 8 modułów | Python 3.10+ |
| `auditor_advanced.py` | Performance + A11y + Content quality | Python 3.10+ |
| `validator.py` | Walidacja schema.org dla 30+ typów | Python 3.10+ |
| `keyword_strategy.py` | TF-IDF, cannibalization, clusters, merit | Python 3.10+ |
| `fixer.py` | Auto-fix 7 modułów (do `_fixed/` kopii) | Python 3.10+ |
| `pagespeed.py` | Google PageSpeed Insights API | klucz API (free) |
| `monitor.py` | History + diff + alert email | smtplib (stdlib) |
| `report_html.py` | Wizualny HTML/PDF raport (Chart.js) | Python 3.10+ |
| `ai_bots.py` | Lista 26 botów AI 2026 | — |
| `templates.py` | Szablony plików (.htaccess OWASP A+, manifest, sw.js, ai.txt) | — |

---

## Quick start

### Audyt strony lokalnej (folder z plikami HTML)

```powershell
python auditor.py --folder C:\path\to\site --json wynik.json
```

### Audyt strony live (URL publiczny)

```powershell
python auditor.py --url https://example.com --pages 15 --json wynik.json
```

### Pełny audyt z 4 modułami

```powershell
python auditor.py             --folder ./build --json main.json
python auditor_advanced.py    --folder ./build --json adv.json
python validator.py           --folder ./build --json val.json --md val.md
python keyword_strategy.py    --folder ./build --json kw.json --md kw.md --suggest 20
```

### PageSpeed Insights (real metrics z Google)

```powershell
# Klucz API (free): https://console.cloud.google.com → APIs → PageSpeed Insights API
$env:PSI_API_KEY = "AIzaSy..."

python pagespeed.py --url https://example.com --md psi.md --json psi.json
```

### Auto-fix (do `{folder}_fixed/`)

```powershell
python fixer.py --folder ./build --apply all --base-url https://example.com --site-name "MyPage"
```

Moduły fixów: `ai_files`, `robots`, `sitemap`, `security`, `pwa`, `fonts`, `schema`, `all`.

### Continuous monitoring + diff

```powershell
python monitor.py --folder ./build --site mypage
python monitor.py --history --site mypage   # historia + ostatni diff
python monitor.py --schedule --folder ./build --site mypage   # komenda do Task Scheduler
```

### Wizualny raport HTML

```powershell
python report_html.py --inputs main.json,adv.json,val.json --site example --out raport.html
```

---

## Pełny przepływ — przykład end-to-end

```powershell
# 1. Audyt PRZED
python auditor.py --folder ./output/zdrowie-fit --json before.json

# 2. Auto-fix
python fixer.py --folder ./output/zdrowie-fit --apply all `
                --base-url https://zdrowie.fit --site-name "Zdrowie.fit"

# 3. Audyt PO (kopii _fixed/)
python auditor.py --folder ./output/zdrowie-fit_fixed --json after.json

# 4. Walidacja schema.org
python validator.py --folder ./output/zdrowie-fit_fixed --md val.md --json val.json

# 5. PageSpeed Insights real
python pagespeed.py --url https://zdrowie.fit --md psi.md --json psi.json

# 6. Wizualny raport
python report_html.py --inputs after.json,val.json --site zdrowie-fit --out raport.html
```

Albo jednym `examples\full_flow.bat`:

```powershell
.\examples\full_flow.bat "C:\path\output\zdrowie-fit" "Zdrowie.fit" "https://zdrowie.fit"
```

---

## Architektura wyniku — `auditor.py`

8 modułów audytu, każdy zwraca listę linii z `✅` / `❌` / `⚠️`.
Score = `done / (done + fail) * 100`.

```
1. PLIKI AI         — llms.txt, llms-full.txt, ai.txt
2. ROBOTS.TXT       — 26 AI crawlerów + sitemap + llms ref
3. SCHEMA JSON-LD   — wymagane: WebSite, Organization, Article,
                      BreadcrumbList, Person
                      opcjonalne: FAQPage, HowTo, Review,
                      ClaimReview, SpeakableSpecification
4. SITEMAP          — URL count, image namespace, lastmod
5. SECURITY         — HSTS, CSP, X-Frame, COOP, CORP, Permissions,
                      Referrer, gzip, cache, HTTPS redirect
6. PWA              — manifest.json + sw.js
7. FONTY            — self-hosted .woff2, brak Google Fonts
8. JAKOŚĆ TREŚCI    — H2-pytania, bibliografia, autor, OG, nosnippet
```

---

## Wymagania

- **Python 3.10+** (używamy `str | None` syntax)
- **Klucz Google API** (opcjonalny, tylko do `pagespeed.py`):
  https://console.cloud.google.com → APIs → PageSpeed Insights API
- **Lighthouse CLI** (opcjonalny, dla `auditor_advanced.py` performance):
  `npm install -g lighthouse`

Brak innych zależności. Jeden plik = jedna funkcja, czysty stdlib.

---

## Struktura repo

```
seo-aeo-geo-auditor/
├── auditor.py              ← główny audyt 8 modułów
├── auditor_advanced.py     ← Performance + A11y + Content
├── validator.py            ← walidacja schema.org
├── keyword_strategy.py     ← TF-IDF + cannibalization + clusters
├── fixer.py                ← auto-fix 7 modułów
├── pagespeed.py            ← Google PSI API
├── monitor.py              ← history + diff + alerts
├── report_html.py          ← wizualny HTML/PDF
├── ai_bots.py              ← lista 26 botów AI
├── templates.py            ← .htaccess OWASP A+, manifest, sw.js
├── examples/
│   ├── audit_url.bat
│   ├── audit_local.bat
│   └── full_flow.bat
├── .gitignore
├── README.md
├── CHANGELOG.md
└── requirements.txt
```

---

## Licencja

Wewnętrzne narzędzie ARCHAIOS. Reuse OK.

---

## Status

Zweryfikowane na produkcji:
- `auditor.py`, `auditor_advanced.py`, `validator.py`, `keyword_strategy.py`,
  `pagespeed.py`, `fixer.py --apply robots` — działają end-to-end
- Realne wyniki na zdrowie.fit: auditor 100%, validator 0 errors / 9 warnings,
  PSI Performance 98 / Accessibility 96 / BP 100 / SEO 100, LCP 1.5s, CLS 0

Niezweryfikowane (do testów):
- `monitor.py` — history + diff + email alerts
- `report_html.py` — wizualny raport
- `fixer.py` poza `--apply robots` — pozostałe moduły fixów
- Multi-domain batch (poza zdrowie.fit nie testowane)
