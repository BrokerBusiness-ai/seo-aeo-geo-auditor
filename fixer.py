#!/usr/bin/env python3
"""
fixer.py — silnik auto-fix dla SEO/AEO/GEO.

Companion do auditor.py. Bezpieczny tryb domyślny: wszystkie zmiany
trafiają do {folder}_fixed/ — oryginał nietknięty.

Moduły fixów (idempotentne — można uruchomić wielokrotnie):
  ai_files   — generuj llms.txt, llms-full.txt, ai.txt z istniejącego HTML
  robots     — kompletny robots.txt z 26 botami AI (kwiecień 2026)
  sitemap    — sitemap.xml z lastmod, image namespace
  security   — .htaccess z OWASP A+ headers (HSTS, CSP, X-Frame, gzip, cache)
  pwa        — manifest.json + sw.js
  fonts      — pobierz Google Fonts lokalnie do /fonts/, podmień <link>
  schema     — wstrzyknij brakujące JSON-LD do <head>
  all        — wszystko powyżej

Użycie:
    python fixer.py --folder C:/path/to/output --apply all
    python fixer.py --folder ./build --apply ai_files,robots,security
    python fixer.py --folder ./build --apply all --in-place    # bez kopii
    python fixer.py --folder ./build --apply all --site-name "Zdrowie.fit" --base-url https://zdrowie.fit
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
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Lokalne moduły (ten sam folder co fixer.py)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ai_bots import AI_BOTS, render_robots_txt  # noqa: E402
from templates import (  # noqa: E402
    HTACCESS_TEMPLATE,
    MANIFEST_TEMPLATE,
    SW_TEMPLATE,
    AI_TXT_TEMPLATE,
)

USER_AGENT = "Mozilla/5.0 (compatible; SEO-AEO-GEO-Fixer/1.0)"

ALL_MODULES = ["ai_files", "robots", "sitemap", "security", "pwa", "fonts", "schema"]

# ─── HELPERY HTML ─────────────────────────────────────────────────────────────

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
JSONLD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\']>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)
HEAD_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)
GFONTS_LINK_RE = re.compile(
    r'<link[^>]+href=["\'](https?://fonts\.googleapis\.com[^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
P_TAG_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_STRIP_RE.sub(" ", html)).strip()


def _extract_title(html: str) -> str:
    m = TITLE_RE.search(html)
    return _strip_tags(m.group(1)) if m else ""


def _extract_meta_description(html: str) -> str:
    m = META_DESC_RE.search(html)
    return m.group(1) if m else ""


def _extract_h1(html: str) -> str:
    m = H1_RE.search(html)
    return _strip_tags(m.group(1)) if m else ""


def _extract_first_paragraph(html: str, min_words: int = 15) -> str:
    for m in P_TAG_RE.findall(html):
        text = _strip_tags(m)
        if len(text.split()) >= min_words:
            return text[:300]
    return ""


def _existing_jsonld_types(html: str) -> set[str]:
    """Zwróć zbiór @type już obecnych w stronie."""
    types = set()
    for blob in JSONLD_RE.findall(html):
        try:
            data = json.loads(blob.strip())
        except json.JSONDecodeError:
            continue

        def collect(node):
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    types.add(t)
                elif isinstance(t, list):
                    types.update(t)
                if "@graph" in node and isinstance(node["@graph"], list):
                    for it in node["@graph"]:
                        collect(it)
            elif isinstance(node, list):
                for it in node:
                    collect(it)

        collect(data)
    return types


# ─── BEZPIECZNY ZAPIS / PRZYGOTOWANIE FOLDERU ─────────────────────────────────

def prepare_target(src: Path, in_place: bool) -> Path:
    """Zwraca folder docelowy (kopia _fixed/ albo oryginał jeśli in_place)."""
    if in_place:
        return src
    target = src.parent / (src.name + "_fixed")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target)
    return target


def write_file(path: Path, content: str | bytes, log: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    # Pokaż 2 ostatnie segmenty ścieżki (np. "output_fixed/llms.txt")
    display = "/".join(path.parts[-2:]) if len(path.parts) >= 2 else path.name
    log.append(f"   ✏️  zapisano: {display}")


# ─── FIX 1: PLIKI AI (llms.txt, llms-full.txt, ai.txt) ───────────────────────

def fix_ai_files(target: Path, base_url: str, site_name: str, description: str) -> list[str]:
    log = ["\n📄 FIX: PLIKI AI"]
    html_files = sorted(target.rglob("*.html"))

    # llms.txt — zwięzły indeks Markdown
    lines = [f"# {site_name}", "", f"> {description}", ""]
    lines.append("## Articles")
    lines.append("")
    for hf in html_files[:200]:
        rel = hf.relative_to(target).as_posix()
        if rel in ("404.html", "500.html"):
            continue
        title = _extract_title(hf.read_text(encoding="utf-8", errors="ignore")) or rel
        url = f"{base_url.rstrip('/')}/{rel}"
        # Markdown link
        lines.append(f"- [{title}]({url})")
    lines.append("")

    write_file(target / "llms.txt", "\n".join(lines), log)

    # llms-full.txt — pełna treść (dla małych stron, do 100 plików)
    full_parts = [f"# {site_name} — pełna treść\n", f"> {description}\n"]
    for hf in html_files[:100]:
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        title = _extract_title(html) or hf.name
        body_html = re.sub(r"<head.*?</head>", "", html, flags=re.DOTALL | re.IGNORECASE)
        body_html = re.sub(r"<script.*?</script>", "", body_html, flags=re.DOTALL | re.IGNORECASE)
        body_html = re.sub(r"<style.*?</style>", "", body_html, flags=re.DOTALL | re.IGNORECASE)
        text = _strip_tags(body_html)
        full_parts.append(f"\n## {title}\n\n{text}\n")
    write_file(target / "llms-full.txt", "\n".join(full_parts), log)

    # ai.txt — Spawning policy
    write_file(target / "ai.txt", AI_TXT_TEMPLATE, log)

    log.append(f"   ℹ️  llms.txt indeksuje {len(html_files)} plików HTML")
    return log


# ─── FIX 2: ROBOTS.TXT ────────────────────────────────────────────────────────

def fix_robots(target: Path, base_url: str) -> list[str]:
    log = ["\n🤖 FIX: ROBOTS.TXT"]
    sitemap_url = f"{base_url.rstrip('/')}/sitemap.xml"
    content = render_robots_txt(sitemap_url=sitemap_url, allow_ai=True)
    # Dodaj odniesienie do llms.txt
    content += f"\n# AI training data manifest\n# Allow: {base_url.rstrip('/')}/llms.txt\n# Allow: {base_url.rstrip('/')}/llms-full.txt\n# Allow: {base_url.rstrip('/')}/ai.txt\n"
    write_file(target / "robots.txt", content, log)
    log.append(f"   ℹ️  Wymienionych botów AI: {len(AI_BOTS)}")
    return log


# ─── FIX 3: SITEMAP.XML ───────────────────────────────────────────────────────

def fix_sitemap(target: Path, base_url: str) -> list[str]:
    log = ["\n🗺️  FIX: SITEMAP"]
    base = base_url.rstrip("/")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/0.9">',
    ]

    html_files = sorted(target.rglob("*.html"))
    for hf in html_files:
        rel = hf.relative_to(target).as_posix()
        if rel in ("404.html", "500.html"):
            continue
        # Bug fix: replace global zniszczyłby URL '/index.html-archive/foo.html'
        path_part = f"/{rel}"
        if path_part.endswith("/index.html"):
            path_part = path_part[: -len("index.html")]
        url = f"{base}{path_part}"
        try:
            mtime = datetime.fromtimestamp(hf.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            mtime = today
        priority = "1.0" if rel in ("index.html",) else "0.8"
        changefreq = "daily" if rel == "index.html" else "weekly"
        lines.append("  <url>")
        lines.append(f"    <loc>{url}</loc>")
        lines.append(f"    <lastmod>{mtime}</lastmod>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        # Image namespace — wyciągnij <img> z HTML
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
            imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
            for img in imgs[:5]:
                if img.startswith("http"):
                    img_url = img
                elif img.startswith("/"):
                    img_url = f"{base}{img}"
                else:
                    img_url = f"{base}/{img}"
                lines.append("    <image:image>")
                lines.append(f"      <image:loc>{img_url}</image:loc>")
                lines.append("    </image:image>")
        except Exception:
            pass
        lines.append("  </url>")
    lines.append("</urlset>")

    write_file(target / "sitemap.xml", "\n".join(lines), log)
    log.append(f"   ℹ️  Wpisanych URL: {len(html_files)}")
    return log


# ─── FIX 4: SECURITY (.htaccess) ──────────────────────────────────────────────

def fix_security(target: Path) -> list[str]:
    log = ["\n🔒 FIX: SECURITY (.htaccess)"]
    write_file(target / ".htaccess", HTACCESS_TEMPLATE, log)
    log.append("   ℹ️  HSTS, CSP, X-Frame-Options, COOP, CORP, Permissions-Policy, gzip, cache, HTTPS redirect")
    return log


# ─── FIX 5: PWA (manifest.json + sw.js) ───────────────────────────────────────

def fix_pwa(target: Path, site_name: str, description: str) -> list[str]:
    log = ["\n📱 FIX: PWA"]
    # Bug fix: site_name="  " (whitespace) przechodziło `if site_name` ale split()=[]
    parts = (site_name or "").split()
    short = parts[0][:12] if parts else "App"
    slug = re.sub(r"[^a-z0-9]+", "-", (site_name or "").lower()).strip("-") or "site"

    manifest = json.loads(json.dumps(MANIFEST_TEMPLATE))  # deepcopy
    manifest["name"] = site_name
    manifest["short_name"] = short
    manifest["description"] = description

    write_file(target / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False), log)
    write_file(target / "sw.js", SW_TEMPLATE.replace("{{SITE_SLUG}}", slug), log)
    log.append(f"   ℹ️  PWA dla: {site_name}")
    return log


# ─── FIX 6: FONTY (Google Fonts → self-hosted) ────────────────────────────────

def fix_fonts(target: Path, timeout: int = 15) -> list[str]:
    log = ["\n🔤 FIX: FONTY (self-hosted)"]
    html_files = list(target.rglob("*.html"))
    fonts_dir = target / "fonts"
    fonts_dir.mkdir(exist_ok=True)

    found_links: set[str] = set()
    for hf in html_files:
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for url in GFONTS_LINK_RE.findall(html):
            found_links.add(url)

    if not found_links:
        log.append("   ✅ Brak Google Fonts w HTML — nic do robienia")
        return log

    log.append(f"   ℹ️  Znaleziono {len(found_links)} linków do Google Fonts")
    css_combined = ["/* @font-face — wygenerowane z Google Fonts (self-hosted) */", ""]
    fonts_downloaded = 0

    for gf_url in found_links:
        try:
            req = urllib.request.Request(gf_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                css = r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.append(f"   ⚠️  Nie udało się pobrać CSS: {gf_url} — {e}")
            continue

        # Strip CSS comments BEFORE URL extraction, so we don't process
        # fonts referenced in commented-out blocks. Operate on a stripped copy
        # for parsing/replacement to keep the original (with comments) untouched
        # outside url(...) contexts.
        css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

        # wyciągnij wszystkie URL .woff2 z CSS (bez komentarzy)
        for woff_url in re.findall(r"url\(\s*['\"]?(https?://[^)'\"]+\.woff2)['\"]?\s*\)", css_no_comments):
            fname = woff_url.rsplit("/", 1)[-1]
            local_path = fonts_dir / fname
            if not local_path.exists():
                try:
                    req2 = urllib.request.Request(woff_url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req2, timeout=timeout) as r:
                        local_path.write_bytes(r.read())
                    fonts_downloaded += 1
                except OSError as e:
                    log.append(f"   ⚠️  Zapis {fname}: {e}")
                    continue
                except Exception as e:
                    log.append(f"   ⚠️  Pobieranie {fname}: {e}")
                    continue
            # Replace ONLY inside url(...) context, leaving comments / unrelated
            # text alone. Using regex with the URL escaped guarantees we don't
            # touch occurrences outside url(...).
            css = re.sub(
                r"url\(\s*(['\"]?)" + re.escape(woff_url) + r"\1\s*\)",
                f"url('/fonts/{fname}')",
                css,
            )

        css_combined.append(css)

    fonts_css_path = target / "fonts" / "fonts.css"
    write_file(fonts_css_path, "\n".join(css_combined), log)

    # Podmień <link> w HTML na lokalny <link rel="stylesheet" href="/fonts/fonts.css">
    new_link = '<link rel="stylesheet" href="/fonts/fonts.css">'
    replaced_files = 0
    for hf in html_files:
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        new_html = GFONTS_LINK_RE.sub("", html)
        # usuń też preconnect do fonts.googleapis.com / fonts.gstatic.com
        new_html = re.sub(
            r'<link[^>]+(fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>',
            "", new_html, flags=re.IGNORECASE,
        )
        if new_html != html:
            # wstrzyknij lokalny CSS do <head>
            new_html = HEAD_CLOSE_RE.sub(f"  {new_link}\n</head>", new_html, count=1)
            hf.write_text(new_html, encoding="utf-8")
            replaced_files += 1

    log.append(f"   ✅ Pobrano {fonts_downloaded} plików .woff2")
    log.append(f"   ✅ Podmieniono linki w {replaced_files} plikach HTML")
    return log


# ─── FIX 7: SCHEMA JSON-LD INJECTION ──────────────────────────────────────────

def _build_organization_schema(site_name: str, base_url: str, description: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{base_url}/#organization",
        "name": site_name,
        "url": base_url,
        "description": description,
        "logo": f"{base_url}/icons/icon-512.png",
        "sameAs": [],
    }


def _build_website_schema(site_name: str, base_url: str, description: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{base_url}/#website",
        "name": site_name,
        "url": base_url,
        "description": description,
        "inLanguage": "pl-PL",
        "publisher": {"@id": f"{base_url}/#organization"},
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{base_url}/?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }


def _build_breadcrumb_schema(rel_path: str, base_url: str, title: str) -> dict:
    parts = [p for p in rel_path.replace("index.html", "").split("/") if p and not p.endswith(".html")]
    items = [{"@type": "ListItem", "position": 1, "name": "Strona główna", "item": base_url}]
    cur = base_url.rstrip("/")
    for i, part in enumerate(parts, start=2):
        cur = f"{cur}/{part}"
        items.append({"@type": "ListItem", "position": i, "name": part.replace("-", " ").title(), "item": cur})
    if rel_path.endswith(".html") and rel_path != "index.html":
        items.append({"@type": "ListItem", "position": len(items) + 1, "name": title, "item": f"{base_url}/{rel_path}"})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def _build_article_schema(title: str, description: str, url: str, base_url: str, published: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "url": url,
        "datePublished": published,
        "dateModified": published,
        "inLanguage": "pl-PL",
        "isPartOf": {"@id": f"{base_url}/#website"},
        "publisher": {"@id": f"{base_url}/#organization"},
        "author": {"@type": "Organization", "@id": f"{base_url}/#organization"},
    }


def fix_schema(target: Path, base_url: str, site_name: str, description: str) -> list[str]:
    log = ["\n🏷️  FIX: SCHEMA (JSON-LD injection)"]
    base = base_url.rstrip("/")
    html_files = list(target.rglob("*.html"))
    injected = 0
    skipped = 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for hf in html_files:
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not HEAD_CLOSE_RE.search(html):
            skipped += 1
            continue

        existing = _existing_jsonld_types(html)
        rel = hf.relative_to(target).as_posix()
        title = _extract_title(html) or _extract_h1(html) or rel
        page_desc = _extract_meta_description(html) or _extract_first_paragraph(html) or description
        page_url = f"{base}/{rel}".replace("/index.html", "/")

        new_blocks = []
        if "WebSite" not in existing:
            new_blocks.append(_build_website_schema(site_name, base, description))
        if "Organization" not in existing:
            new_blocks.append(_build_organization_schema(site_name, base, description))
        if "BreadcrumbList" not in existing:
            new_blocks.append(_build_breadcrumb_schema(rel, base, title))
        # Article tylko dla podstron (nie home)
        if rel != "index.html" and "Article" not in existing and rel.endswith(".html"):
            new_blocks.append(_build_article_schema(title, page_desc, page_url, base, today))

        if not new_blocks:
            continue

        injection = "\n".join(
            f'<script type="application/ld+json">\n{json.dumps(b, ensure_ascii=False, indent=2)}\n</script>'
            for b in new_blocks
        )
        new_html = HEAD_CLOSE_RE.sub(injection + "\n</head>", html, count=1)
        hf.write_text(new_html, encoding="utf-8")
        injected += 1

    log.append(f"   ✅ Wstrzyknięto schematy do {injected} plików HTML")
    if skipped:
        log.append(f"   ⚠️  Pominięto {skipped} plików (brak </head>)")
    return log


# ─── ORKIESTRACJA ─────────────────────────────────────────────────────────────

FIXERS = {
    "ai_files": lambda t, ctx: fix_ai_files(t, ctx["base_url"], ctx["site_name"], ctx["description"]),
    "robots":   lambda t, ctx: fix_robots(t, ctx["base_url"]),
    "sitemap":  lambda t, ctx: fix_sitemap(t, ctx["base_url"]),
    "security": lambda t, ctx: fix_security(t),
    "pwa":      lambda t, ctx: fix_pwa(t, ctx["site_name"], ctx["description"]),
    "fonts":    lambda t, ctx: fix_fonts(t),
    "schema":   lambda t, ctx: fix_schema(t, ctx["base_url"], ctx["site_name"], ctx["description"]),
}


def parse_modules(arg: str) -> list[str]:
    if arg == "all":
        return list(ALL_MODULES)
    requested = [m.strip() for m in arg.split(",") if m.strip()]
    invalid = [m for m in requested if m not in ALL_MODULES]
    if invalid:
        raise SystemExit(f"❌ Nieznane moduły: {invalid}. Dostępne: {ALL_MODULES + ['all']}")
    return requested


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Auto-fix engine SEO/AEO/GEO. Bezpieczny tryb domyślny: zmiany do {folder}_fixed/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python fixer.py --folder ./output/zdrowie-fit --apply all --base-url https://zdrowie.fit\n"
            "  python fixer.py --folder ./build --apply ai_files,robots,security\n"
            "  python fixer.py --folder ./build --apply all --in-place\n"
            f"\nDostępne moduły: {', '.join(ALL_MODULES)}, all\n"
        ),
    )
    ap.add_argument("--folder", required=True, help="Ścieżka do folderu z wygenerowaną stroną")
    ap.add_argument("--apply", required=True, help=f"Moduły fixów (csv) lub 'all'. Dostępne: {ALL_MODULES}")
    ap.add_argument("--in-place", action="store_true", help="Modyfikuj oryginał zamiast kopii _fixed/")
    ap.add_argument("--base-url", default="https://example.com", help="Base URL strony")
    ap.add_argument("--site-name", default="Strona", help="Nazwa strony (np. 'Zdrowie.fit')")
    ap.add_argument("--description", default="", help="Opis strony (do meta/llms.txt)")
    ap.add_argument("--json", help="Zapisz log fixów jako JSON")
    args = ap.parse_args()

    src = Path(args.folder).resolve()
    if not src.exists() or not src.is_dir():
        print(f"❌ Folder nie istnieje: {src}")
        return 2

    modules = parse_modules(args.apply)

    if not args.description:
        args.description = f"{args.site_name} — automatycznie generowany opis."

    target = prepare_target(src, args.in_place)

    print("=" * 60)
    print("  SEO / AEO / GEO FIXER")
    print("=" * 60)
    print(f"  Source:   {src}")
    print(f"  Target:   {target}{'  (IN-PLACE)' if args.in_place else '  (safe copy)'}")
    print(f"  Site:     {args.site_name}")
    print(f"  Base URL: {args.base_url}")
    print(f"  Modules:  {', '.join(modules)}")

    ctx = {
        "base_url": args.base_url,
        "site_name": args.site_name,
        "description": args.description,
    }

    all_log: list[str] = []
    for mod in modules:
        try:
            all_log.extend(FIXERS[mod](target, ctx))
        except Exception as e:  # noqa: BLE001
            all_log.append(f"\n⚠️  Moduł {mod} przerwany: {e}")

    for line in all_log:
        print(line)

    print("\n" + "=" * 60)
    print(f"  GOTOWE. Wynik w: {target}")
    print("=" * 60)
    print("  Następny krok:")
    print(f"  python auditor.py --folder \"{target}\"")
    print("=" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "source": str(src),
                    "target": str(target),
                    "modules": modules,
                    "lines": all_log,
                    "ctx": ctx,
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
