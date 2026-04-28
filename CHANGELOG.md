# CHANGELOG

## 2026-04-28 — v1.0 (sesja inicjalna)

### Dodane
- `auditor.py` — główny audyt 8 modułów (URL + folder)
- `auditor_advanced.py` — Performance + A11y WCAG 2.2 + Content quality (FOG-PL Pisarek)
- `validator.py` — walidacja schema.org dla 30+ typów (Article, WebSite,
  Organization, Person, BreadcrumbList, FAQPage, HowTo, SpeakableSpecification,
  ImageObject, Recipe, Product, Review, ClaimReview, Dataset, Event, QAPage,
  CollectionPage, ItemList, AboutPage, ContactPage, ListItem, HowToStep,
  SearchAction, Answer, Question, ScholarlyArticle, NewsArticle, BlogPosting,
  WebPage, VideoObject)
- `keyword_strategy.py` — TF-IDF per artykuł, cannibalization,
  Jaccard clusters z min-shared fallback, content gap suggestions, merit score
- `fixer.py` — auto-fix 7 modułów (ai_files, robots, sitemap, security,
  pwa, fonts, schema) z safe copy do `_fixed/`
- `pagespeed.py` — Google PSI API integration (Performance, A11y, BP, SEO + LCP/INP/CLS)
- `monitor.py` — history snapshots + diff reporter + SMTP alerts + Task Scheduler
- `report_html.py` — wizualny raport HTML z Chart.js (gauge + trend line)
- `ai_bots.py` — kanoniczna lista 26 botów AI (kwiecień 2026)
- `templates.py` — szablony plików (htaccess OWASP A+, manifest, sw.js, ai.txt)

### Naprawione bugi (znalezione przez testy w trakcie sesji)
- `fixer.py` — `write_file` rzucał ValueError dla plików w korzeniu folderu
- `auditor_advanced.py` — `body_html` undefined (literówka w fix dla citation regex)
- `auditor_advanced.py` — kontrast a11y false-positive dla par tego samego koloru
  i dwóch ciemnych odcieni (zmienione na semantyczne parowanie jasny+ciemny)
- `auditor_advanced.py` — formuła Flesch Reading Ease (English) zastąpiona
  formułą FOG-PL Pisarka (1969) dla polskiego — daje realistyczne wyniki
- `auditor_advanced.py` — citation regex pomijał plain-text DOI w bibliografii
  (teraz łapie zarówno klikalne `<a href>` jak i `\b10.xxxx/yyyy` w body)
- `keyword_strategy.py` — citation regex (analogicznie)
- `keyword_strategy.py` — threshold klastrów Jaccard 0.2 → 0.1 + min-shared 3
- `auditor.py` — wykrywanie nested `@type` (np. SpeakableSpecification w Article)
- `validator.py` — image URL relatywny (`/img/...`) flag jako "niepoprawny URL" → naprawione
- `validator.py` — dodane reguły dla CollectionPage, ItemList, AboutPage,
  ContactPage, ListItem, HowToStep, SearchAction, Answer

### Patche dla generatora ARCHAIOS Demand Engine (zdrowie-fit-generator)
- `domains/zdrowie-fit.yaml` — dodane `founder`, `foundingDate`, `address`
- `domains/_schema.yaml` — dokumentacja nowych pól
- `domain_config.py` — loader przekazuje nowe pola do `site` dict
- `src/templates/base.html` — Organization JSON-LD rozszerzony o `description`,
  `email`, `contactPoint`, `address`, `founder`, `foundingDate`
- `src/templates/category.html` — CollectionPage z `@id`, `isPartOf`, `inLanguage`,
  `mainEntity` ItemList, `datePublished`, `dateModified`
- `src/templates/articles.html` — to samo
- `src/templates/robots.txt` — z 9 botów AI rozszerzony do 26
- `build.py` — funkcja `linkify_dois()` zamienia plain-text DOI w bibliografii
  na klikalne `<a href="https://doi.org/...">` (idempotent)
- `src/static/css/style.css` — fix kontrastu WCAG AA:
  - `.section__link`: `color: var(--color-primary)` → `var(--color-primary-dark)`
  - `.difficulty-badge--sredniozaawansowany`: `color: #b58b36` → `#8a6a26`
- `scripts/update_author_sameas.py` — skrypt do aktualizacji author URLs w sqlite

### Wyniki real na zdrowie.fit (po wszystkich patches)
- `auditor.py` main score: 70% → 100%
- `validator.py`: 10 errors / 104 warnings → 0 errors / 9 warnings
- Citation density per artykuł: 0 → 8-14
- PageSpeed Insights:
  - Performance: 98/100
  - Accessibility: 96/100 (kontrast fix wykonany, do potwierdzenia po rebuild)
  - Best Practices: 100/100
  - SEO: 100/100
- LCP: 1.5s, CLS: 0, TBT: 0ms (mobile)

### Niezweryfikowane (do testów)
- `monitor.py` — history snapshots + diff
- `report_html.py` — wizualny raport
- Dashboard artifact `seo-aeo-geo-command-center` (tryb query/paste-back)
- `fixer.py` poza `--apply robots`
- Multi-domain batch (pozostałe domeny ARCHAIOS poza zdrowie.fit)
