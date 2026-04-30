#!/usr/bin/env python3
"""
SEO / AEO / GEO Auditor — samodzielne narzędzie do audytu stron WWW.

Pochodzenie:
    Wyodrębnione z ARCHAIOS Demand Engine / zdrowie-fit-generator
    (scripts/audit_aeo.py). Wersja standalone — bez zaleznosci od projektu
    nadrzednego, dziala na czystym stdlib.

Co sprawdza:
    1. PLIKI AI       — llms.txt, llms-full.txt
    2. ROBOTS.TXT     — dostep AI crawlerow (GPTBot, Claude-Web, PerplexityBot...)
    3. SCHEMA JSON-LD — WebSite, Organization, Article, BreadcrumbList, Person,
                        FAQPage, HowTo, Speakable...
    4. SITEMAP        — kompletnosc, image namespace, lastmod
    5. BEZPIECZENSTWO — naglowki HTTP / .htaccess (HSTS, CSP, X-Frame-Options...)
    6. PWA            — sw.js, manifest.json
    7. FONTY          — self-hosted vs Google Fonts
    8. JAKOSC TRESCI  — naglowki-pytania, bibliografia, autor, OG image, nosnippet

Tryby pracy:
    --url       audyt strony na zywo (HTTP)
    --folder    audyt lokalnego katalogu z wygenerowana strona statyczna

Przyklady:
    python auditor.py --url https://zdrowie.fit
    python auditor.py --url https://example.com --pages 20 --json report.json
    python auditor.py --folder C:/PYTHON/ARCHAIOS-Demand-Engine/.../output/zdrowie-fit
"""
from __future__ import annotations
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

# ─── KONFIGURACJA ─────────────────────────────────────────────────────────────

try:
    # Pełna lista 26 botów AI (kwiecień 2026) z ai_bots.py
    from ai_bots import REQUIRED_AI_BOTS  # type: ignore
except ImportError:
    # Fallback — podstawowa lista jeśli ai_bots.py niedostępny
    REQUIRED_AI_BOTS = [
        "GPTBot", "ChatGPT-User", "OAI-SearchBot",
        "ClaudeBot", "Claude-Web", "claude-searchbot",
        "PerplexityBot", "Perplexity-User",
        "Google-Extended", "GoogleOther",
        "Applebot-Extended", "Amazonbot", "Bytespider",
        "CCBot", "Meta-ExternalAgent", "Meta-ExternalFetcher",
        "cohere-ai", "Diffbot", "MistralAI-User",
        "DuckAssistBot", "YouBot", "Timpibot",
        "omgili", "omgilibot", "ImagesiftBot",
    ]

REQUIRED_SCHEMA_TYPES = [
    "WebSite", "Organization", "Article", "BreadcrumbList", "Person",
]

OPTIONAL_SCHEMA_TYPES = [
    "FAQPage", "HowTo", "Review", "ClaimReview", "SpeakableSpecification",
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; SEO-AEO-GEO-Auditor/1.0; "
    "+standalone)"
)


# ─── ABSTRAKCJA ZRODLA (lokalny folder LUB url) ───────────────────────────────

@dataclass
class FetchResult:
    exists: bool
    content: str = ""
    size: int = 0
    error: str = ""


class Source:
    """Bazowa klasa zrodla. Implementacje: LocalSource, URLSource."""

    def get(self, rel_path: str) -> FetchResult:
        raise NotImplementedError

    def html_pages(self, max_pages: int = 30) -> list[tuple[str, str]]:
        raise NotImplementedError

    @property
    def label(self) -> str:
        raise NotImplementedError


class LocalSource(Source):
    def __init__(self, root: Path):
        self.root = root.resolve()

    @property
    def label(self) -> str:
        return f"folder: {self.root}"

    def get(self, rel_path: str) -> FetchResult:
        p = self.root / rel_path
        if not p.exists() or not p.is_file():
            return FetchResult(exists=False, error="file not found")
        try:
            return FetchResult(
                exists=True,
                content=p.read_text(encoding="utf-8", errors="ignore"),
                size=p.stat().st_size,
            )
        except Exception as e:  # noqa: BLE001
            return FetchResult(exists=False, error=str(e))

    def html_pages(self, max_pages: int = 30) -> list[tuple[str, str]]:
        files = list(self.root.rglob("*.html"))
        out: list[tuple[str, str]] = []
        for f in files[:max_pages]:
            try:
                out.append(
                    (str(f.relative_to(self.root)),
                     f.read_text(encoding="utf-8", errors="ignore"))
                )
            except Exception:
                pass
        return out


class URLSource(Source):
    def __init__(self, base_url: str, max_pages: int = 10, timeout: int = 15):
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        self.base = base_url.rstrip("/")
        self.max_pages = max_pages
        self.timeout = timeout
        self._cache: dict[str, FetchResult] = {}
        self._head_cache: dict[str, dict[str, str]] = {}

    @property
    def label(self) -> str:
        return f"url:    {self.base}"

    def _fetch(self, url: str) -> FetchResult:
        if url in self._cache:
            return self._cache[url]
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                ct = r.headers.get("Content-Type", "")
                m = re.search(r"charset=([\w-]+)", ct)
                charset = m.group(1) if m else "utf-8"
                fr = FetchResult(
                    exists=True,
                    content=raw.decode(charset, errors="ignore"),
                    size=len(raw),
                )
        except urllib.error.HTTPError as e:
            fr = FetchResult(exists=False, error=f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            fr = FetchResult(exists=False, error=str(e))
        self._cache[url] = fr
        return fr

    def head(self, path: str = "/") -> dict[str, str]:
        url = urljoin(self.base + "/", path.lstrip("/"))
        if url in self._head_cache:
            return self._head_cache[url]
        # IMPORTANT: send Accept-Encoding so the server actually advertises
        # Content-Encoding: gzip|br|deflate. Without this header the server
        # serves uncompressed and we'd report "no compression" as a false
        # negative (urllib otherwise sends NO Accept-Encoding by default,
        # unlike curl/browsers).
        common_headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "*/*",
        }
        req = urllib.request.Request(url, headers=common_headers, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                hdrs = {k.lower(): v for k, v in r.headers.items()}
        except Exception:
            # Some hosts reject HEAD — fall back to a tiny GET (Range: 0-1023)
            # so we still get response headers including Content-Encoding.
            try:
                req_get = urllib.request.Request(
                    url,
                    headers={**common_headers, "Range": "bytes=0-1023"},
                    method="GET",
                )
                with urllib.request.urlopen(req_get, timeout=self.timeout) as r:
                    hdrs = {k.lower(): v for k, v in r.headers.items()}
                    hdrs["_status"] = "fallback-get"
            except Exception:
                hdrs = {}
        self._head_cache[url] = hdrs
        return hdrs

    def get(self, rel_path: str) -> FetchResult:
        return self._fetch(urljoin(self.base + "/", rel_path.lstrip("/")))

    def html_pages(self, max_pages: int = 30) -> list[tuple[str, str]]:
        limit = min(self.max_pages, max_pages)
        urls: list[str] = [self.base + "/"]
        sm = self._fetch(self.base + "/sitemap.xml")
        if sm.exists:
            for u in re.findall(r"<loc>(.*?)</loc>", sm.content):
                u = u.strip()
                if u and u.startswith(self.base) and u not in urls:
                    urls.append(u)
                if len(urls) >= limit:
                    break
        urls = urls[:limit]
        out: list[tuple[str, str]] = []
        for u in urls:
            r = self._fetch(u)
            if r.exists and "<html" in r.content.lower():
                name = u.replace(self.base, "") or "/"
                out.append((name, r.content))
        return out


# ─── HELPERY ──────────────────────────────────────────────────────────────────

def _badge(fr: FetchResult, name: str) -> str:
    if fr.exists:
        return f"   ✅ {name} ({fr.size:,} bajtow)"
    err = f" — {fr.error}" if fr.error else ""
    return f"   ❌ {name} — BRAK{err}"


# ─── MODULY AUDYTU ────────────────────────────────────────────────────────────

def audit_llms(src: Source) -> list[str]:
    out = ["\n📄 1. PLIKI AI (llms.txt) — fundament AEO/GEO", "─" * 50]
    fr = src.get("llms.txt")
    out.append(_badge(fr, "llms.txt"))
    if fr.exists:
        lines = fr.content.strip().splitlines()
        out.append(f"      → {len(lines)} linii")
        if any(t in fr.content.lower() for t in ("# articles", "# artykuly", "articles")):
            out.append("      → Sekcja artykulow: ✅")
        else:
            out.append("      → Sekcja artykulow: ❌ brak")
    fr2 = src.get("llms-full.txt")
    out.append(_badge(fr2, "llms-full.txt"))
    if fr2.exists:
        out.append(f"      → ~{len(fr2.content.split()):,} slow (pelna tresc)")
    return out


def audit_robots(src: Source) -> list[str]:
    out = ["\n🤖 2. ROBOTS.TXT — DOSTEP AI CRAWLEROW (GEO)", "─" * 50]
    fr = src.get("robots.txt")
    out.append(_badge(fr, "robots.txt"))
    if not fr.exists:
        return out
    content = fr.content
    for bot in REQUIRED_AI_BOTS:
        if bot.lower() in content.lower():
            # Bug fix: poprzedni regex z DOTALL mógł zaczepiać Disallow z innego bloku.
            # Teraz match ograniczony do BLOKU bota (do następnej pustej linii lub
            # następnego User-agent — nie przeskakuje cudzych reguł).
            pat = re.compile(
                rf"User-agent:\s*{re.escape(bot)}\b"
                r"(?P<block>(?:[^\n]*\n(?!\s*User-agent:|\s*$))*[^\n]*)",
                re.IGNORECASE,
            )
            m = pat.search(content)
            block = m.group("block").lower() if m else ""
            # Wyrzuć z analizy popularne wyjątki "Disallow: /data" itp. żeby nie
            # mylić z full-disallow root.
            block_clean = re.sub(r"disallow:\s*/(data|admin|api|private)\b[^\n]*", "", block)
            has_full_disallow = re.search(r"disallow:\s*/\s*$", block_clean, re.MULTILINE)
            if m and not has_full_disallow:
                out.append(f"   ✅ {bot} — dozwolony")
            else:
                out.append(f"   ⚠️  {bot} — wymieniony, sprawdz reguly")
        else:
            out.append(f"   ❌ {bot} — nie wymieniony")
    out.append("   ✅ Sitemap zadeklarowany" if "sitemap:" in content.lower()
              else "   ❌ Sitemap niezadeklarowany")
    out.append("   ✅ Odniesienie do llms.txt"
              if ("llms.txt" in content or "llms-full.txt" in content)
              else "   ⚠️  Brak odniesienia do llms.txt")
    return out


def audit_schema(src: Source) -> list[str]:
    out = ["\n🏷️  3. SCHEMA MARKUP (JSON-LD) — AEO/SEO", "─" * 50]
    pages = src.html_pages(max_pages=30)
    out.append(f"   Plikow HTML do analizy: {len(pages)}")

    schema_pat = re.compile(
        r'<script\s+type=["\']application/ld\+json["\']>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    all_types: set[str] = set()
    errors = 0

    def collect(node, depth=0):
        # Rekurencyjnie po WSZYSTKICH węzłach — łapie nested @type
        # (np. speakable.@type=SpeakableSpecification w środku Article)
        if depth > 25:
            return
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                all_types.add(t)
            elif isinstance(t, list):
                all_types.update(t)
            for v in node.values():
                collect(v, depth + 1)
        elif isinstance(node, list):
            for it in node:
                collect(it, depth + 1)

    for name, content in pages:
        for blob in schema_pat.findall(content):
            try:
                collect(json.loads(blob.strip()))
            except json.JSONDecodeError:
                errors += 1
                out.append(f"   ❌ Blad JSON-LD w {name}")

    if errors == 0:
        out.append("   ✅ Wszystkie JSON-LD poprawne skladniowo")
    out.append(f"   Znalezione typy: {', '.join(sorted(all_types)) or '(brak)'}")
    for st in REQUIRED_SCHEMA_TYPES:
        out.append(f"   ✅ {st}" if st in all_types
                  else f"   ❌ {st} — BRAK (wymagany)")
    for st in OPTIONAL_SCHEMA_TYPES:
        out.append(f"   ✅ {st} (opcjonalny)" if st in all_types
                  else f"   ℹ️  {st} — brak (opcjonalny)")
    return out


def audit_sitemap(src: Source) -> list[str]:
    out = ["\n🗺️  4. SITEMAP", "─" * 50]
    fr = src.get("sitemap.xml")
    out.append(_badge(fr, "sitemap.xml"))
    if not fr.exists:
        return out
    c = fr.content
    url_count = c.count("<url>") or c.count("<loc>")
    out.append(f"      → {url_count} URL-i")
    out.append("   ✅ Image namespace (obrazki w sitemap)"
              if ("image:" in c or "image:loc" in c)
              else "   ❌ Brak image namespace")
    out.append("   ✅ lastmod timestamps" if "<lastmod>" in c
              else "   ⚠️  Brak lastmod")
    if "<changefreq>" in c:
        out.append("   ✅ changefreq")
    if "<priority>" in c:
        out.append("   ✅ priority")
    return out


def audit_security(src: Source) -> list[str]:
    out = ["\n🔒 5. BEZPIECZENSTWO / NAGLOWKI HTTP", "─" * 50]

    if isinstance(src, LocalSource):
        fr = src.get(".htaccess")
        out.append(_badge(fr, ".htaccess"))
        if not fr.exists:
            return out
        content = fr.content
        haystack = content.lower()
        compress_ok = "mod_deflate" in content or "AddOutputFilterByType" in content
        cache_ok = "ExpiresByType" in content or "max-age" in content
    else:
        # URL: pobierz HEAD strony glownej
        hdrs = src.head("/")
        if not hdrs:
            out.append("   ❌ Nie udalo sie pobrac naglowkow HTTP")
            return out
        haystack = "\n".join(f"{k}: {v}" for k, v in hdrs.items()).lower()
        out.append("   ✅ Naglowki HTTP odebrane")
        compress_ok = "content-encoding" in haystack
        cache_ok = "cache-control" in haystack or "max-age" in haystack

    checks = [
        ("X-Content-Type-Options", "X-Content-Type-Options (nosniff)"),
        ("X-Frame-Options", "X-Frame-Options"),
        ("Strict-Transport-Security", "HSTS"),
        ("Content-Security-Policy", "CSP"),
        ("Referrer-Policy", "Referrer-Policy"),
        ("Permissions-Policy", "Permissions-Policy"),
    ]
    for header, label in checks:
        out.append(f"   ✅ {label}" if header.lower() in haystack
                  else f"   ❌ {label} — BRAK")

    out.append("   ✅ Kompresja (gzip/br/deflate)" if compress_ok
              else "   ❌ Brak kompresji")
    out.append("   ✅ Cache headers" if cache_ok
              else "   ❌ Brak cache headers")
    return out


def audit_pwa(src: Source) -> list[str]:
    out = ["\n📱 6. PWA / OFFLINE", "─" * 50]
    out.append(_badge(src.get("sw.js"), "sw.js (Service Worker)"))
    out.append(_badge(src.get("manifest.json"), "manifest.json"))
    return out


def audit_fonts(src: Source) -> list[str]:
    out = ["\n🔤 7. FONTY (self-hosted, brak Google Fonts)", "─" * 50]
    if isinstance(src, LocalSource):
        fonts_dir = src.root / "fonts"
        if fonts_dir.exists():
            woff2 = list(fonts_dir.glob("*.woff2"))
            out.append(f"   ✅ {len(woff2)} plikow .woff2 w /fonts/")
            total = sum(f.stat().st_size for f in woff2)
            out.append(f"      → Laczny rozmiar: {total // 1024} KB")
        else:
            out.append("   ❌ Brak katalogu /fonts/")
    else:
        out.append("   ℹ️  Tryb URL: sprawdzam tylko brak Google Fonts w HTML")

    found = False
    for name, content in src.html_pages(max_pages=10):
        if "fonts.googleapis.com" in content:
            out.append(f"   ❌ Google Fonts w {name}")
            found = True
            break
    if not found:
        out.append("   ✅ Zero requestow do Google Fonts")
    return out


def audit_content_quality(src: Source) -> list[str]:
    out = ["\n📝 8. JAKOSC TRESCI (AEO/GEO)", "─" * 50]
    pages = src.html_pages(max_pages=30)
    n = len(pages) or 1
    q = b = a = og = ns = 0
    for name, content in pages:
        q += len(re.findall(r'<h[23][^>]*>.*?\?</h[23]>', content, re.DOTALL))
        if 'role="doc-bibliography"' in content or "bibliography" in content.lower():
            b += 1
        if 'itemprop="author"' in content or '"@type":"Person"' in content.replace(" ", ""):
            a += 1
        if "og:image" in content:
            og += 1
        if "data-nosnippet" in content:
            ns += 1
    out.append(f"   Naglowki-pytania (FAQ-ready): {q}")
    out.append(f"   Strony z bibliografia:        {b}/{n}")
    out.append(f"   Strony z autorem:             {a}/{n}")
    out.append(f"   Strony z OG image:            {og}/{n}")
    out.append(f"   Strony z data-nosnippet (CTA):{ns}/{n}")
    return out


# ─── MAIN ─────────────────────────────────────────────────────────────────────

MODULES = [
    audit_llms,
    audit_robots,
    audit_schema,
    audit_sitemap,
    audit_security,
    audit_pwa,
    audit_fonts,
    audit_content_quality,
]


def make_source(args) -> Source:
    if args.url:
        return URLSource(args.url, max_pages=args.pages, timeout=args.timeout)
    if args.folder:
        return LocalSource(Path(args.folder))
    raise SystemExit("Podaj --url ALBO --folder (zobacz: python auditor.py -h)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audyt SEO / AEO / GEO — strona lokalna lub na zywo (URL).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przyklady:\n"
            "  python auditor.py --url https://zdrowie.fit\n"
            "  python auditor.py --url https://example.com --pages 20\n"
            "  python auditor.py --folder ./output/zdrowie-fit\n"
            "  python auditor.py --url https://example.com --json report.json\n"
        ),
    )
    ap.add_argument("--url", help="Pelny URL strony (np. https://zdrowie.fit)")
    ap.add_argument("--folder", help="Sciezka do katalogu z wygenerowana strona")
    ap.add_argument("--pages", type=int, default=10,
                    help="Ile podstron skanowac w trybie URL (default 10)")
    ap.add_argument("--timeout", type=int, default=15,
                    help="Timeout HTTP w sekundach (default 15)")
    ap.add_argument("--json", help="Zapisz wynik takze jako JSON")
    args = ap.parse_args()

    src = make_source(args)

    print("=" * 60)
    print("  SEO / AEO / GEO AUDITOR  (standalone)")
    print("=" * 60)
    print(f"  Source: {src.label}")

    all_results: list[str] = []
    for mod in MODULES:
        try:
            all_results.extend(mod(src))
        except Exception as e:  # noqa: BLE001
            all_results.append(f"\n⚠️  Modul {mod.__name__} przerwany: {e}")

    for line in all_results:
        print(line)

    done = sum(1 for r in all_results if "✅" in r)
    fail = sum(1 for r in all_results if "❌" in r)
    warn = sum(1 for r in all_results if "⚠️" in r)
    score = int(done / max(done + fail, 1) * 100)

    print("\n" + "=" * 60)
    print(f"  WYNIK:  {done} ✅   |   {fail} ❌   |   {warn} ⚠️")
    print(f"  SCORE:  {score}%")
    print("=" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "source": src.label,
                    "ok": done, "fail": fail, "warn": warn, "score": score,
                    "lines": all_results,
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n💾 Raport JSON zapisany: {args.json}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
