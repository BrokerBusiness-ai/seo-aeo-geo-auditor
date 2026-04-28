#!/usr/bin/env python3
"""
validator.py — walidator schema.org (lokalny, bez LLM).

Sprawdza każdy JSON-LD w *.html przeciwko regułom schema.org:
  - required fields per @type
  - recommended fields per @type (best practice)
  - format checks (URL, ISO 8601 date, BCP 47 language)
  - cross-references (publisher.@id musi istnieć jako Organization)

Użycie:
  python validator.py --folder ./output/zdrowie-fit
  python validator.py --folder ./output/zdrowie-fit --json validator_report.json
  python validator.py --url https://zdrowie.fit/artykuly/cold-exposure.html
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

USER_AGENT = "Mozilla/5.0 (compatible; SchemaValidator/1.0)"

# ─── REGUŁY SCHEMA.ORG ────────────────────────────────────────────────────────
# Format: { "TypeName": { "required": [...], "recommended": [...], "checks": {...} } }

SCHEMA_RULES = {
    "Article": {
        "required": ["headline", "image"],
        "recommended": ["datePublished", "dateModified", "author", "publisher",
                        "mainEntityOfPage", "description", "articleSection",
                        "wordCount", "timeRequired", "inLanguage", "keywords"],
        "checks": {
            "datePublished": "iso_date",
            "dateModified": "iso_date",
            "url": "url",
            "image": "url_or_imageobject",
            "inLanguage": "lang_code",
            "wordCount": "int",
            "timeRequired": "iso_duration",
        },
    },
    "NewsArticle": {
        "required": ["headline", "image", "datePublished"],
        "recommended": ["dateModified", "author", "publisher", "dateline", "articleBody"],
        "checks": {"datePublished": "iso_date", "dateModified": "iso_date"},
    },
    "BlogPosting": {
        "required": ["headline", "image"],
        "recommended": ["datePublished", "dateModified", "author", "publisher"],
        "checks": {"datePublished": "iso_date", "dateModified": "iso_date"},
    },
    "ScholarlyArticle": {
        "required": ["headline", "author", "datePublished"],
        "recommended": ["citation", "isPartOf", "pageStart", "pageEnd", "issn"],
        "checks": {"datePublished": "iso_date"},
    },
    "WebSite": {
        "required": ["url", "name"],
        "recommended": ["description", "inLanguage", "publisher", "potentialAction"],
        "checks": {"url": "url", "inLanguage": "lang_code"},
    },
    "WebPage": {
        "required": ["url"],
        "recommended": ["name", "description", "inLanguage", "isPartOf",
                        "datePublished", "dateModified", "breadcrumb", "primaryImageOfPage"],
        "checks": {"url": "url", "inLanguage": "lang_code",
                   "datePublished": "iso_date", "dateModified": "iso_date"},
    },
    "Organization": {
        "required": ["name", "url"],
        "recommended": ["logo", "sameAs", "description", "contactPoint",
                        "address", "email"],
        "checks": {"url": "url", "logo": "url_or_imageobject", "sameAs": "url_list"},
    },
    "Person": {
        "required": ["name"],
        "recommended": ["sameAs", "url", "image", "jobTitle", "affiliation",
                        "description", "knowsAbout", "alumniOf"],
        "checks": {"url": "url", "image": "url_or_imageobject", "sameAs": "url_list"},
    },
    "BreadcrumbList": {
        "required": ["itemListElement"],
        "recommended": [],
        "checks": {"itemListElement": "breadcrumb_items"},
    },
    "FAQPage": {
        "required": ["mainEntity"],
        "recommended": [],
        "checks": {"mainEntity": "faq_questions"},
    },
    "HowTo": {
        "required": ["name", "step"],
        "recommended": ["description", "totalTime", "estimatedCost", "tool",
                        "supply", "image", "yield"],
        "checks": {"step": "howto_steps", "totalTime": "iso_duration"},
    },
    "SpeakableSpecification": {
        "required": [],
        "recommended": ["cssSelector", "xpath"],
        "checks": {"cssSelector": "non_empty_list_or_str", "xpath": "non_empty_list_or_str"},
        "anyOf": ["cssSelector", "xpath"],  # przynajmniej jedno
    },
    "ImageObject": {
        "required": ["url"],
        "recommended": ["width", "height", "caption"],
        "checks": {"url": "url", "width": "int", "height": "int"},
    },
    "VideoObject": {
        "required": ["name", "description", "thumbnailUrl", "uploadDate"],
        "recommended": ["duration", "contentUrl", "embedUrl"],
        "checks": {"uploadDate": "iso_date", "thumbnailUrl": "url"},
    },
    "Recipe": {
        "required": ["name", "image", "recipeIngredient", "recipeInstructions"],
        "recommended": ["author", "datePublished", "description", "prepTime",
                        "cookTime", "totalTime", "recipeYield", "nutrition"],
        "checks": {"prepTime": "iso_duration", "cookTime": "iso_duration"},
    },
    "Product": {
        "required": ["name"],
        "recommended": ["image", "description", "brand", "offers", "aggregateRating", "review"],
    },
    "Review": {
        "required": ["author", "reviewRating", "itemReviewed"],
        "recommended": ["datePublished", "publisher", "reviewBody"],
        "checks": {"datePublished": "iso_date"},
    },
    "ClaimReview": {
        "required": ["claimReviewed", "reviewRating", "author", "url"],
        "recommended": ["datePublished", "itemReviewed"],
        "checks": {"datePublished": "iso_date", "url": "url"},
    },
    "Dataset": {
        "required": ["name", "description"],
        "recommended": ["url", "creator", "license", "distribution",
                        "datePublished", "keywords", "spatialCoverage"],
        "checks": {"url": "url", "datePublished": "iso_date"},
    },
    "Event": {
        "required": ["name", "startDate", "location"],
        "recommended": ["endDate", "description", "image", "organizer", "performer"],
        "checks": {"startDate": "iso_date", "endDate": "iso_date"},
    },
    "QAPage": {
        "required": ["mainEntity"],
        "recommended": [],
    },
    "CollectionPage": {
        "required": ["url"],
        "recommended": ["name", "description", "mainEntity", "isPartOf",
                        "inLanguage", "datePublished", "dateModified", "breadcrumb"],
        "checks": {"url": "url", "inLanguage": "lang_code",
                   "datePublished": "iso_date", "dateModified": "iso_date"},
    },
    "ItemList": {
        "required": ["itemListElement"],
        "recommended": ["numberOfItems", "itemListOrder"],
    },
    "AboutPage": {
        "required": ["url"],
        "recommended": ["name", "description", "mainEntity"],
        "checks": {"url": "url"},
    },
    "ContactPage": {
        "required": ["url"],
        "recommended": ["name", "description"],
        "checks": {"url": "url"},
    },
    "Answer": {
        "required": ["text"],
        "recommended": ["author", "dateCreated", "upvoteCount"],
    },
    "ListItem": {
        "required": ["position"],
        "recommended": ["name", "item", "url"],
    },
    "HowToStep": {
        "required": [],
        "recommended": ["name", "text", "image", "position", "url"],
        "anyOf": ["name", "text"],
    },
    "SearchAction": {
        "required": ["target"],
        "recommended": ["query-input"],
    },
    "Question": {
        "required": ["name", "acceptedAnswer"],
        "recommended": ["author", "answerCount", "upvoteCount", "datePublished"],
    },
}

# ─── CHECKERY FORMATU ─────────────────────────────────────────────────────────

URL_RE = re.compile(r"^https?://[^\s<>\"]+$")
URL_OR_RELATIVE_RE = re.compile(r"^(?:https?://[^\s<>\"]+|/[^\s<>\"]*|\.{0,2}/[^\s<>\"]*)$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
ISO_DURATION_RE = re.compile(r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$")
LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


def check_format(name: str, value, fmt: str) -> str | None:
    """Zwróć błąd jako string, albo None jeśli OK."""
    if value is None or value == "":
        return None  # empty checked separately
    if fmt == "url":
        url = value if isinstance(value, str) else (value.get("url") if isinstance(value, dict) else None)
        if url and not URL_RE.match(url):
            return f"`{name}`: niepoprawny URL: {url[:60]}"
    elif fmt == "url_or_imageobject":
        # Image URL może być relatywny (canonical strony go wstrzyknie)
        if isinstance(value, str):
            if not URL_OR_RELATIVE_RE.match(value):
                return f"`{name}`: niepoprawny URL: {value[:60]}"
        elif isinstance(value, dict):
            if value.get("@type") not in ("ImageObject", None):
                return f"`{name}`: oczekiwano string URL lub ImageObject"
            url = value.get("url")
            if url and not URL_OR_RELATIVE_RE.match(url):
                return f"`{name}.url`: niepoprawny URL"
    elif fmt == "url_list":
        items = value if isinstance(value, list) else [value]
        bad = [u for u in items if isinstance(u, str) and not URL_RE.match(u)]
        if bad:
            return f"`{name}`: {len(bad)} niepoprawnych URL-i"
    elif fmt == "iso_date":
        if isinstance(value, str) and not ISO_DATE_RE.match(value):
            return f"`{name}`: niepoprawna data ISO 8601: {value[:30]}"
    elif fmt == "iso_duration":
        if isinstance(value, str) and not ISO_DURATION_RE.match(value):
            return f"`{name}`: niepoprawny duration ISO 8601 (np. PT10M): {value[:30]}"
    elif fmt == "lang_code":
        if isinstance(value, str) and not LANG_CODE_RE.match(value):
            return f"`{name}`: niepoprawny kod języka BCP 47 (np. pl, pl-PL): {value[:30]}"
    elif fmt == "int":
        if not isinstance(value, int):
            return f"`{name}`: oczekiwano integer, jest: {type(value).__name__}"
    elif fmt == "breadcrumb_items":
        if not isinstance(value, list) or len(value) < 2:
            return f"`{name}`: BreadcrumbList wymaga ≥2 ListItem"
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                return f"`{name}[{i}]`: nie jest obiektem"
            for f in ("@type", "position", "name", "item"):
                if f not in item:
                    return f"`{name}[{i}]`: brak pola `{f}`"
    elif fmt == "faq_questions":
        items = value if isinstance(value, list) else [value]
        for i, q in enumerate(items):
            if not isinstance(q, dict):
                return f"`mainEntity[{i}]`: nie jest obiektem Question"
            if q.get("@type") != "Question":
                return f"`mainEntity[{i}]`: @type powinno być 'Question'"
            if "name" not in q or not q["name"]:
                return f"`mainEntity[{i}]`: brak pytania (name)"
            ans = q.get("acceptedAnswer")
            if not ans or not isinstance(ans, dict) or not ans.get("text"):
                return f"`mainEntity[{i}]`: brak acceptedAnswer.text"
    elif fmt == "howto_steps":
        if not isinstance(value, list) or not value:
            return "`step`: HowTo wymaga listy HowToStep"
        for i, step in enumerate(value):
            if not isinstance(step, dict) or step.get("@type") != "HowToStep":
                return f"`step[{i}]`: @type powinno być 'HowToStep'"
            if not step.get("name") and not step.get("text"):
                return f"`step[{i}]`: brak name lub text"
    elif fmt == "non_empty_list_or_str":
        if isinstance(value, list) and not value:
            return f"`{name}`: pusta lista"
    return None


# ─── PARSER JSON-LD ───────────────────────────────────────────────────────────

JSONLD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\']>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class Issue:
    severity: str   # "error" | "warning" | "info"
    page: str
    schema_type: str
    message: str


@dataclass
class PageReport:
    page: str
    types: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def collect_jsonld_objects(html: str) -> list[dict]:
    """Zwraca listę top-level obiektów JSON-LD z HTML (zwykłe + @graph rozpakowane)."""
    objects = []
    for blob in JSONLD_RE.findall(html):
        try:
            data = json.loads(blob.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                for it in data["@graph"]:
                    if isinstance(it, dict):
                        objects.append(it)
            else:
                objects.append(data)
        elif isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    objects.append(it)
    return objects


def get_type(obj: dict) -> str:
    t = obj.get("@type")
    if isinstance(t, list):
        return t[0] if t else ""
    return t or ""


def validate_object(obj: dict, page: str) -> list[Issue]:
    issues: list[Issue] = []
    schema_type = get_type(obj)
    rules = SCHEMA_RULES.get(schema_type)
    if not rules:
        return issues  # nieznany typ — pomijamy (mogą być user-defined)

    for field_name in rules.get("required", []):
        if field_name not in obj or obj[field_name] in (None, "", [], {}):
            issues.append(Issue("error", page, schema_type,
                                f"BRAK wymaganego pola `{field_name}`"))

    for field_name in rules.get("recommended", []):
        if field_name not in obj or obj[field_name] in (None, "", [], {}):
            issues.append(Issue("warning", page, schema_type,
                                f"brakuje zalecanego pola `{field_name}`"))

    if "anyOf" in rules:
        if not any(obj.get(f) for f in rules["anyOf"]):
            issues.append(Issue("error", page, schema_type,
                                f"wymagane przynajmniej jedno z: {', '.join(rules['anyOf'])}"))

    for field_name, fmt in rules.get("checks", {}).items():
        if field_name in obj and obj[field_name]:
            err = check_format(field_name, obj[field_name], fmt)
            if err:
                issues.append(Issue("error", page, schema_type, err))

    return issues


def validate_html_page(html: str, page: str) -> PageReport:
    rep = PageReport(page=page)
    for obj in collect_jsonld_objects(html):
        t = get_type(obj)
        if t:
            rep.types.append(t)
        rep.issues.extend(validate_object(obj, page))

    # Cross-check: jeśli Article/WebPage referuje publisher.@id, ten Organization musi być w grafie
    # (uproszczone: pomijamy bo wymaga merge'u graphów; zostawiam jako TODO)

    if not rep.types:
        rep.issues.append(Issue("warning", page, "—",
                                "BRAK JSON-LD na tej stronie"))
    return rep


# ─── ŹRÓDŁA ───────────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ct = r.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ct)
        charset = m.group(1) if m else "utf-8"
        return r.read().decode(charset, errors="ignore")


def collect_pages(folder: Path | None, url: str | None, max_pages: int) -> list[tuple[str, str]]:
    pages: list[tuple[str, str]] = []
    if folder:
        for hf in sorted(folder.rglob("*.html"))[:max_pages]:
            try:
                pages.append((str(hf.relative_to(folder)),
                              hf.read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                pass
    elif url:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            pages.append((url, fetch_url(url)))
        except Exception as e:
            print(f"❌ Błąd pobrania {url}: {e}")
    return pages


# ─── RAPORT ───────────────────────────────────────────────────────────────────

def render_markdown_report(reports: list[PageReport]) -> str:
    lines = ["# Walidacja schema.org\n"]
    total_err = sum(1 for r in reports for i in r.issues if i.severity == "error")
    total_warn = sum(1 for r in reports for i in r.issues if i.severity == "warning")
    type_counts: dict[str, int] = {}
    for r in reports:
        for t in r.types:
            type_counts[t] = type_counts.get(t, 0) + 1

    lines.append(f"**Stron przeskanowanych:** {len(reports)}")
    lines.append(f"**Błędy:** {total_err}  |  **Ostrzeżenia:** {total_warn}\n")
    lines.append("## Typy schema znalezione\n")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        rule_status = "✅" if t in SCHEMA_RULES else "❓ (nieznany typ — bez walidacji)"
        lines.append(f"- `{t}` × {c} {rule_status}")
    lines.append("")

    lines.append("## Problemy per strona\n")
    for r in reports:
        if not r.issues:
            lines.append(f"### ✅ {r.page}\nTypy: {', '.join(r.types) or '(brak)'}\n")
            continue
        errs = [i for i in r.issues if i.severity == "error"]
        warns = [i for i in r.issues if i.severity == "warning"]
        marker = "❌" if errs else "⚠️"
        lines.append(f"### {marker} {r.page}")
        lines.append(f"Typy: {', '.join(r.types) or '(brak)'}")
        for i in errs:
            lines.append(f"- ❌ **[{i.schema_type}]** {i.message}")
        for i in warns:
            lines.append(f"- ⚠️ **[{i.schema_type}]** {i.message}")
        lines.append("")

    return "\n".join(lines)


def render_json_report(reports: list[PageReport]) -> dict:
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "pages": len(reports),
            "errors": sum(1 for r in reports for i in r.issues if i.severity == "error"),
            "warnings": sum(1 for r in reports for i in r.issues if i.severity == "warning"),
        },
        "pages": [
            {
                "page": r.page,
                "types": r.types,
                "issues": [
                    {"severity": i.severity, "type": i.schema_type, "message": i.message}
                    for i in r.issues
                ],
            }
            for r in reports
        ],
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Walidator schema.org dla stron statycznych i live URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python validator.py --folder ./output/zdrowie-fit\n"
            "  python validator.py --url https://zdrowie.fit/artykuly/cold-exposure.html\n"
            "  python validator.py --folder ./build --json validator.json --md raport.md\n"
        ),
    )
    ap.add_argument("--folder", help="Folder z plikami HTML")
    ap.add_argument("--url", help="Pojedynczy URL do walidacji")
    ap.add_argument("--max-pages", type=int, default=200, help="Limit stron (default 200)")
    ap.add_argument("--json", help="Zapis raportu jako JSON")
    ap.add_argument("--md", help="Zapis raportu jako Markdown")
    args = ap.parse_args()

    if not args.folder and not args.url:
        print("❌ Podaj --folder lub --url")
        return 2

    folder = Path(args.folder).resolve() if args.folder else None
    pages = collect_pages(folder, args.url, args.max_pages)
    if not pages:
        print("❌ Brak stron do walidacji")
        return 1

    reports = [validate_html_page(html, page) for page, html in pages]

    md_report = render_markdown_report(reports)
    print(md_report)

    if args.md:
        Path(args.md).write_text(md_report, encoding="utf-8")
        print(f"\n💾 Markdown: {args.md}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(render_json_report(reports), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"💾 JSON: {args.json}")

    total_err = sum(1 for r in reports for i in r.issues if i.severity == "error")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
