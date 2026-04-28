#!/usr/bin/env python3
"""
auditor_advanced.py — zaawansowane moduły audytu (Performance, A11y, Content Quality).

Uzupełnia auditor.py o trzy obszary które są krytyczne dla SEO/AEO/GEO 2026:
  1. PERFORMANCE / CORE WEB VITALS — page weight, image format coverage,
     lazy loading, render-blocking, font preload, Lighthouse shell-out (opcjonalnie)
  2. ACCESSIBILITY / WCAG 2.2 AA — alt coverage, heading hierarchy, color contrast,
     ARIA landmarks, form labels, skip links, lang attribute
  3. CONTENT QUALITY — Flesch PL (formuła Pisarka), sentence length distribution,
     fact density (numbers + entities), citation density, TL;DR detect,
     H2-jako-pytania ratio, freshness signal

Użycie:
    python auditor_advanced.py --folder ./output/zdrowie-fit
    python auditor_advanced.py --url https://zdrowie.fit --pages 10
    python auditor_advanced.py --folder ./build --json adv_report.json --modules performance,a11y
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

USER_AGENT = "Mozilla/5.0 (compatible; SEO-AEO-GEO-Auditor-Advanced/1.0)"

# ─── REGEXY HTML ──────────────────────────────────────────────────────────────

IMG_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w[\w:-]*)\s*=\s*"([^"]*)"', re.IGNORECASE)
LINK_CSS_RE = re.compile(
    r'<link\b[^>]*rel\s*=\s*["\']stylesheet["\'][^>]*>', re.IGNORECASE
)
LINK_PRELOAD_FONT_RE = re.compile(
    r'<link\b[^>]*rel\s*=\s*["\']preload["\'][^>]*as\s*=\s*["\']font["\']', re.IGNORECASE
)
SCRIPT_BLOCKING_RE = re.compile(
    r"<script\b(?![^>]*\b(?:async|defer|type=[\"']module[\"'])\b)[^>]*\bsrc=", re.IGNORECASE
)
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
A_TAG_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
P_TAG_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
COLOR_HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
LANG_HTML_RE = re.compile(r'<html\b[^>]*\blang\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
INPUT_RE = re.compile(r"<input\b([^>]*)>", re.IGNORECASE)
LABEL_FOR_RE = re.compile(r'<label\b[^>]*for\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
META_DATE_PUB_RE = re.compile(
    r'<meta\b[^>]*property\s*=\s*["\']article:published_time["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
META_DATE_MOD_RE = re.compile(
    r'<meta\b[^>]*property\s*=\s*["\']article:modified_time["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def parse_attrs(s: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) for m in ATTR_RE.finditer(s)}


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_STRIP_RE.sub(" ", html)).strip()


# ─── ŹRÓDŁA ───────────────────────────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ct)
        charset = m.group(1) if m else "utf-8"
        return raw.decode(charset, errors="ignore"), len(raw)


@dataclass
class Page:
    name: str            # rel path (folder mode) lub URL
    html: str
    html_size: int       # rozmiar HTML w bajtach
    asset_sizes: dict[str, int] = field(default_factory=dict)  # path → bytes (folder mode only)


def collect_pages_local(folder: Path, max_pages: int) -> list[Page]:
    out: list[Page] = []
    files = sorted(folder.rglob("*.html"))[:max_pages]
    for hf in files:
        try:
            html = hf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        out.append(Page(
            name=str(hf.relative_to(folder)),
            html=html,
            html_size=hf.stat().st_size,
        ))
    return out


def collect_pages_url(base: str, max_pages: int, timeout: int = 15) -> list[Page]:
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    base = base.rstrip("/")
    out: list[Page] = []
    seen: set[str] = set()
    queue: list[str] = [base + "/"]
    # Spróbuj sitemap dla podstron
    try:
        sm, _ = fetch_url(base + "/sitemap.xml", timeout)
        for u in re.findall(r"<loc>(.*?)</loc>", sm):
            u = u.strip()
            if u.startswith(base) and u not in queue:
                queue.append(u)
    except Exception:
        pass
    queue = queue[:max_pages]
    for u in queue:
        if u in seen:
            continue
        seen.add(u)
        try:
            html, sz = fetch_url(u, timeout)
            out.append(Page(name=u.replace(base, "") or "/", html=html, html_size=sz))
        except Exception:
            continue
    return out


def asset_size_local(folder: Path, ref: str) -> int:
    """Zwróć rozmiar assetu (img/css/js) odwołującego się relatywnie do folderu."""
    if ref.startswith(("http://", "https://", "//", "data:")):
        return 0
    rel = ref.lstrip("/")
    p = folder / rel
    if p.exists() and p.is_file():
        try:
            return p.stat().st_size
        except Exception:
            return 0
    return 0


# ─── 1. PERFORMANCE / CORE WEB VITALS ─────────────────────────────────────────

def audit_performance(pages: list[Page], folder: Path | None) -> dict:
    findings: list[str] = []
    # Zbiorczo
    total_html = sum(p.html_size for p in pages)
    total_pages = len(pages) or 1
    avg_html = total_html / total_pages

    # Per strona analiza
    img_total = 0
    img_modern = 0  # webp / avif
    img_with_lazy = 0
    img_with_alt = 0
    img_total_bytes = 0
    css_blocking = 0
    css_total_size = 0
    js_blocking = 0
    js_total_size = 0
    font_preload = 0
    has_picture = 0

    # Liczniki obrazów per format (do raportu)
    fmt_counter: Counter[str] = Counter()
    largest_images: list[tuple[str, int, str]] = []  # (url, size, page)

    for p in pages:
        # OBRAZY
        for m in IMG_RE.finditer(p.html):
            attrs = parse_attrs(m.group(1))
            src = attrs.get("src", "")
            if not src:
                continue
            img_total += 1
            ext = src.rsplit(".", 1)[-1].lower().split("?")[0]
            fmt_counter[ext] += 1
            if ext in ("webp", "avif"):
                img_modern += 1
            if "loading" in attrs and attrs["loading"] == "lazy":
                img_with_lazy += 1
            if "alt" in attrs:
                img_with_alt += 1
            if folder:
                size = asset_size_local(folder, src)
                img_total_bytes += size
                if size > 0:
                    largest_images.append((src, size, p.name))

        # PICTURE element (responsive images)
        if "<picture>" in p.html.lower():
            has_picture += 1

        # CSS
        for m in LINK_CSS_RE.finditer(p.html):
            css_blocking += 1
            href_match = re.search(r'href\s*=\s*["\']([^"\']+)["\']', m.group(0), re.IGNORECASE)
            if href_match and folder:
                css_total_size += asset_size_local(folder, href_match.group(1))

        # JS
        for m in SCRIPT_BLOCKING_RE.finditer(p.html):
            js_blocking += 1
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', m.group(0), re.IGNORECASE)
            if src_match and folder:
                js_total_size += asset_size_local(folder, src_match.group(1))

        # Font preload
        if LINK_PRELOAD_FONT_RE.search(p.html):
            font_preload += 1

    findings.append(f"📊 Stron: {total_pages}, łączny HTML: {total_html/1024:.1f} KB, średnio: {avg_html/1024:.1f} KB/strona")
    if avg_html > 200_000:
        findings.append(f"❌ Średnia waga HTML > 200 KB ({avg_html/1024:.0f} KB) — za dużo. Cel: <100 KB")
    elif avg_html > 100_000:
        findings.append(f"⚠️ Średnia waga HTML 100-200 KB ({avg_html/1024:.0f} KB)")
    else:
        findings.append(f"✅ Średnia waga HTML < 100 KB ({avg_html/1024:.0f} KB)")

    if img_total:
        modern_pct = img_modern / img_total * 100
        lazy_pct = img_with_lazy / img_total * 100
        alt_pct = img_with_alt / img_total * 100
        if modern_pct >= 80:
            findings.append(f"✅ Obrazy modern (WebP/AVIF): {modern_pct:.0f}% ({img_modern}/{img_total})")
        elif modern_pct >= 50:
            findings.append(f"⚠️ Obrazy modern: {modern_pct:.0f}% — powinno być ≥80%")
        else:
            findings.append(f"❌ Obrazy modern: {modern_pct:.0f}% — za mało WebP/AVIF")

        if lazy_pct >= 80:
            findings.append(f"✅ Lazy-loading: {lazy_pct:.0f}%")
        elif lazy_pct >= 30:
            findings.append(f"⚠️ Lazy-loading: {lazy_pct:.0f}% — dodaj loading='lazy' do not-LCP")
        else:
            findings.append(f"❌ Lazy-loading: {lazy_pct:.0f}% — większość obrazów blokuje load")

        if alt_pct >= 95:
            findings.append(f"✅ Atrybut alt: {alt_pct:.0f}% (a11y)")
        else:
            findings.append(f"❌ Atrybut alt: {alt_pct:.0f}% — niezgodne z WCAG")

        findings.append(f"   Formaty obrazów: {dict(fmt_counter.most_common())}")

    if has_picture:
        findings.append(f"✅ <picture> z fallbackiem na {has_picture}/{total_pages} stronach")

    if folder and img_total_bytes:
        avg_img = img_total_bytes / max(img_total, 1)
        findings.append(f"📊 Łączna waga obrazów: {img_total_bytes/1024/1024:.1f} MB, średnio: {avg_img/1024:.0f} KB/img")
        # Top 5 największych
        largest_images.sort(key=lambda x: -x[1])
        for src, size, pname in largest_images[:5]:
            if size > 200_000:
                findings.append(f"   ⚠️ Duży obraz ({size/1024:.0f} KB): {src}")

    if folder and css_total_size:
        findings.append(f"📊 CSS łącznie: {css_total_size/1024:.1f} KB ({css_blocking//total_pages} arkuszy/stronę)")
        if css_total_size > 150_000:
            findings.append(f"⚠️ CSS > 150 KB — rozważ critical CSS inline + reszta async")

    if folder and js_total_size:
        findings.append(f"📊 JS blokujący: {js_total_size/1024:.1f} KB")
        if js_blocking > 0:
            findings.append(f"⚠️ {js_blocking} skryptów bez async/defer — blokują parsing")

    findings.append(f"✅ Font preload: {font_preload}/{total_pages} stron" if font_preload else "❌ Brak <link rel=preload as=font> — fonty będą blokowały LCP")

    # Lighthouse shell-out (opcjonalnie)
    lh_score = None
    if shutil.which("lighthouse") and pages and pages[0].name.startswith(("http://", "https://")):
        try:
            url = pages[0].name
            result = subprocess.run(
                ["lighthouse", url, "--output=json", "--quiet", "--chrome-flags=--headless"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                lh = json.loads(result.stdout)
                lh_score = {
                    "performance": int(lh["categories"]["performance"]["score"] * 100),
                    "accessibility": int(lh["categories"]["accessibility"]["score"] * 100),
                    "seo": int(lh["categories"]["seo"]["score"] * 100),
                    "best_practices": int(lh["categories"]["best-practices"]["score"] * 100),
                    "LCP_ms": lh["audits"]["largest-contentful-paint"]["numericValue"],
                    "CLS": lh["audits"]["cumulative-layout-shift"]["numericValue"],
                }
                findings.append(f"🚦 Lighthouse: perf {lh_score['performance']}, a11y {lh_score['accessibility']}, "
                                f"SEO {lh_score['seo']}, BP {lh_score['best_practices']}")
                findings.append(f"   LCP: {lh_score['LCP_ms']:.0f} ms (cel <2500ms) | CLS: {lh_score['CLS']:.3f} (cel <0.1)")
        except Exception:
            pass

    score_components = []
    if img_total:
        score_components.append(min(100, img_modern / img_total * 100))
        score_components.append(min(100, img_with_lazy / img_total * 100))
        score_components.append(min(100, img_with_alt / img_total * 100))
    if avg_html < 100_000:
        score_components.append(100)
    elif avg_html < 200_000:
        score_components.append(60)
    else:
        score_components.append(20)
    if font_preload:
        score_components.append(100)
    perf_score = int(sum(score_components) / len(score_components)) if score_components else 0

    return {
        "findings": findings,
        "score": perf_score,
        "stats": {
            "pages": total_pages,
            "avg_html_kb": round(avg_html / 1024, 1),
            "img_total": img_total,
            "img_modern_pct": round(img_modern / max(img_total, 1) * 100, 1),
            "img_lazy_pct": round(img_with_lazy / max(img_total, 1) * 100, 1),
            "img_alt_pct": round(img_with_alt / max(img_total, 1) * 100, 1),
            "img_total_mb": round(img_total_bytes / 1024 / 1024, 2),
            "css_kb": round(css_total_size / 1024, 1),
            "js_blocking": js_blocking,
            "font_preload_pages": font_preload,
            "lighthouse": lh_score,
        },
    }


# ─── 2. ACCESSIBILITY / WCAG 2.2 AA ───────────────────────────────────────────

# Lista wymaganych ARIA landmarks (per WCAG 2.2)
LANDMARK_ROLES = ["banner", "main", "navigation", "complementary", "contentinfo"]
LANDMARK_TAGS = ["<header", "<main", "<nav", "<aside", "<footer"]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * chan(rgb[0]) + 0.7152 * chan(rgb[1]) + 0.0722 * chan(rgb[2])


def contrast_ratio(c1: str, c2: str) -> float:
    try:
        l1, l2 = _luminance(_hex_to_rgb(c1)), _luminance(_hex_to_rgb(c2))
        light, dark = max(l1, l2), min(l1, l2)
        return (light + 0.05) / (dark + 0.05)
    except Exception:
        return 0.0


def audit_accessibility(pages: list[Page], folder: Path | None) -> dict:
    findings: list[str] = []
    total_pages = len(pages) or 1

    # Lang
    pages_with_lang = sum(1 for p in pages if LANG_HTML_RE.search(p.html))
    findings.append(f"✅ <html lang>: {pages_with_lang}/{total_pages}" if pages_with_lang == total_pages
                    else f"❌ <html lang> brakuje na {total_pages - pages_with_lang} stronach")

    # Skip links
    pages_with_skip = sum(1 for p in pages if "skip-link" in p.html or "skip-to-main" in p.html
                          or 'href="#main' in p.html or "href='#main" in p.html)
    findings.append(f"✅ Skip-link na {pages_with_skip}/{total_pages} stronach" if pages_with_skip
                    else "⚠️ Brak skip-link — utrudnia nawigację klawiaturową")

    # Alt coverage
    img_total = 0
    img_with_alt = 0
    img_empty_alt = 0  # decorative
    img_descriptive = 0
    for p in pages:
        for m in IMG_RE.finditer(p.html):
            attrs = parse_attrs(m.group(1))
            img_total += 1
            if "alt" in attrs:
                img_with_alt += 1
                if attrs["alt"]:
                    img_descriptive += 1
                else:
                    img_empty_alt += 1
    if img_total:
        findings.append(f"📊 Atrybut alt: {img_with_alt}/{img_total} ({img_with_alt/img_total*100:.0f}%) "
                        f"— opisowe: {img_descriptive}, decorative (alt=''): {img_empty_alt}")

    # Heading hierarchy
    skipped_levels_total = 0
    multiple_h1_total = 0
    for p in pages:
        levels = [int(m.group(1)) for m in HEADING_RE.finditer(p.html)]
        if levels.count(1) > 1:
            multiple_h1_total += 1
        for i in range(1, len(levels)):
            if levels[i] - levels[i-1] > 1:  # skok np. H2 → H4
                skipped_levels_total += 1
                break
    if multiple_h1_total:
        findings.append(f"⚠️ Wiele <h1> na {multiple_h1_total}/{total_pages} stronach — może mylić")
    else:
        findings.append("✅ Każda strona ma jedno <h1>")
    if skipped_levels_total:
        findings.append(f"❌ Pominięcia w hierarchii nagłówków na {skipped_levels_total}/{total_pages} stronach")
    else:
        findings.append("✅ Hierarchia nagłówków bez skoków")

    # Landmarks
    pages_with_landmarks = 0
    for p in pages:
        h = p.html.lower()
        present = sum(1 for tag in LANDMARK_TAGS if tag in h)
        if present >= 3:  # main + header + footer to minimum
            pages_with_landmarks += 1
    findings.append(f"✅ Landmarks (≥3 z [header/main/nav/aside/footer]): {pages_with_landmarks}/{total_pages}"
                    if pages_with_landmarks == total_pages else
                    f"⚠️ Pełne landmarks tylko na {pages_with_landmarks}/{total_pages} stronach")

    # Form inputs labels
    inputs_total = 0
    inputs_unlabeled = 0
    for p in pages:
        labels_for = set(LABEL_FOR_RE.findall(p.html))
        for m in INPUT_RE.finditer(p.html):
            attrs = parse_attrs(m.group(1))
            itype = attrs.get("type", "text").lower()
            if itype in ("hidden", "submit", "button", "reset"):
                continue
            inputs_total += 1
            input_id = attrs.get("id", "")
            has_label = input_id in labels_for or "aria-label" in attrs or "aria-labelledby" in attrs
            if not has_label:
                inputs_unlabeled += 1
    if inputs_total:
        if inputs_unlabeled == 0:
            findings.append(f"✅ Wszystkie {inputs_total} input mają label/aria-label")
        else:
            findings.append(f"❌ {inputs_unlabeled}/{inputs_total} input bez label — niedostępne dla SR")

    # Color contrast (sprawdzamy CSS w folder mode)
    contrast_findings = []
    if folder:
        css_files = list(folder.rglob("*.css"))
        all_colors = set()
        for cf in css_files[:5]:
            try:
                content = cf.read_text(encoding="utf-8", errors="ignore")
                for m in COLOR_HEX_RE.finditer(content):
                    all_colors.add("#" + m.group(1))
            except Exception:
                pass
        # Heurystycznie sprawdź pary tło/tekst (jak w polu --color-bg / --color-text)
        text_colors = set()
        bg_colors = set()
        for cf in css_files[:5]:
            try:
                content = cf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r"--color-(text|ink|fg)[^:]*:\s*(#[0-9a-fA-F]+)", content):
                    text_colors.add(m.group(2))
                for m in re.finditer(r"--color-(bg|background|surface)[^:]*:\s*(#[0-9a-fA-F]+)", content):
                    bg_colors.add(m.group(2))
            except Exception:
                pass
        worst_ratio = 99.0
        worst_pair = None
        for tc in text_colors:
            for bc in bg_colors:
                # Pomiń identyczne kolory
                if tc.lower() == bc.lower():
                    continue
                try:
                    tc_lum = _luminance(_hex_to_rgb(tc))
                    bc_lum = _luminance(_hex_to_rgb(bc))
                except Exception:
                    continue
                # Sparuj tylko semantycznie KONTRASTUJĄCE: jeden jasny, drugi ciemny.
                # Jeśli oba mają tę samą "polaryzację" (oba ciemne lub oba jasne)
                # → to nigdy nie będzie para tekst/tło, pomijamy.
                light = max(tc_lum, bc_lum)
                dark = min(tc_lum, bc_lum)
                if light < 0.5 or dark > 0.3:
                    continue  # nie kontrastująca para
                r = contrast_ratio(tc, bc)
                if r < worst_ratio:
                    worst_ratio = r
                    worst_pair = (tc, bc)
        if worst_pair:
            tc, bc = worst_pair
            if worst_ratio >= 7:
                contrast_findings.append(f"✅ Najgorsza para kontrastu: {tc}/{bc} = {worst_ratio:.1f} (WCAG AAA)")
            elif worst_ratio >= 4.5:
                contrast_findings.append(f"✅ Najgorsza para kontrastu: {tc}/{bc} = {worst_ratio:.1f} (WCAG AA)")
            elif worst_ratio >= 3:
                contrast_findings.append(f"⚠️ Najgorsza para kontrastu: {tc}/{bc} = {worst_ratio:.1f} (tylko duży tekst)")
            else:
                contrast_findings.append(f"❌ Najgorsza para kontrastu: {tc}/{bc} = {worst_ratio:.1f} — niezgodne z WCAG AA")
    findings.extend(contrast_findings)

    # Score
    score_parts = []
    score_parts.append(pages_with_lang / total_pages * 100)
    score_parts.append((pages_with_skip / total_pages * 100) if pages_with_skip else 50)
    if img_total:
        score_parts.append(img_with_alt / img_total * 100)
    score_parts.append(((total_pages - skipped_levels_total) / total_pages * 100))
    score_parts.append(pages_with_landmarks / total_pages * 100)
    if inputs_total:
        score_parts.append((inputs_total - inputs_unlabeled) / inputs_total * 100)
    a11y_score = int(sum(score_parts) / len(score_parts)) if score_parts else 0

    return {
        "findings": findings,
        "score": a11y_score,
        "stats": {
            "pages": total_pages,
            "lang_coverage": round(pages_with_lang / total_pages * 100, 1),
            "skip_link_coverage": round(pages_with_skip / total_pages * 100, 1),
            "img_alt_coverage": round(img_with_alt / max(img_total, 1) * 100, 1),
            "heading_skips": skipped_levels_total,
            "multiple_h1_pages": multiple_h1_total,
            "landmarks_coverage": round(pages_with_landmarks / total_pages * 100, 1),
            "unlabeled_inputs": inputs_unlabeled,
        },
    }


# ─── 3. CONTENT QUALITY (Polish-aware) ────────────────────────────────────────

# Polskie skróty (do detekcji końca zdania)
PL_ABBREVIATIONS = {"np", "tj", "tzn", "tzw", "wg", "ok", "dr", "mgr", "prof", "inż", "płk", "gen",
                    "ul", "al", "pl", "nr", "rok", "wiek", "godz", "min", "sek", "kg", "mln", "mld",
                    "tys", "in", "et", "vs", "etc", "z.o.o", "S.A"}


def _split_sentences_pl(text: str) -> list[str]:
    """Prosty splitter zdań po polsku — uwzględnia skróty."""
    # Zamień multikropki
    text = re.sub(r"\.{3,}", "…", text)
    # Tymczasowo zabezpiecz skróty
    placeholders = {}
    for i, abbr in enumerate(PL_ABBREVIATIONS):
        ph = f"\x01{i}\x01"
        placeholders[ph] = abbr + "."
        text = re.sub(rf"\b{re.escape(abbr)}\.", ph, text, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])", text)
    out = []
    for s in sentences:
        for ph, val in placeholders.items():
            s = s.replace(ph, val)
        s = s.strip()
        if s:
            out.append(s)
    return out


def _count_syllables_pl(word: str) -> int:
    """Liczba sylab dla polskiego słowa — przybliżenie po samogłoskach."""
    word = word.lower()
    # Polskie samogłoski + dwuznaki które są jedną sylabą
    vowels = "aąeęioóuyźż"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


def fog_pl(text: str) -> float:
    """FOG-PL — wskaźnik mglistości tekstu wg Pisarka (1969, 1984).

    Formuła: TR = (ASL + ASW_hard_pct) / 3
    gdzie:
      ASL = średnia długość zdania (słów)
      ASW_hard_pct = % słów z 4+ sylabami

    Skala (zalecenia czytelnicze):
      <5:  bardzo łatwe (klasy 4-6 SP)
      5-9: łatwe (klasy 7-8 SP)
      9-13: standardowe (LO)
      13-17: trudne (akademickie/specjalistyczne)
      17+: bardzo trudne (naukowe, prawnicze)

    Zwraca FOG-score (im niższy, tym łatwiejszy tekst).
    Dla porównania z anglo-Flesch (gdzie wyższy = łatwiejszy):
    converted_flesch_equiv ≈ max(0, 100 - fog_pl * 6)
    """
    sentences = _split_sentences_pl(text)
    if not sentences:
        return 0
    words = re.findall(r"\b[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+\b", text)
    if not words:
        return 0
    asl = len(words) / len(sentences)
    hard = sum(1 for w in words if _count_syllables_pl(w) >= 4)
    hard_pct = hard / len(words) * 100
    return (asl + hard_pct) / 3


# Wstecznie kompatybilne — alias żeby reszta modułu działała
flesch_pl = fog_pl


def audit_content_quality(pages: list[Page], folder: Path | None) -> dict:
    findings: list[str] = []
    total_pages = len(pages) or 1

    flesch_scores: list[float] = []
    sentence_lengths: list[int] = []  # słów per zdanie
    fact_density_scores: list[float] = []  # liczb+entitet per 100 słów
    citation_density_scores: list[float] = []
    h2_question_ratio: list[float] = []
    tldr_present = 0
    freshness_warnings = 0  # artykuły nieaktualizowane > 1 rok

    article_pages = [p for p in pages if "/artykul" in p.name.lower() or "article" in p.html.lower()[:1000]]
    if not article_pages:
        article_pages = pages  # fallback

    for p in article_pages[:30]:
        # Wyłącznie article body — strip head/script/style/nav/footer
        body = re.sub(r"<head\b.*?</head>", "", p.html, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<script\b.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<style\b.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<nav\b.*?</nav>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<footer\b.*?</footer>", "", body, flags=re.DOTALL | re.IGNORECASE)

        # Wyciągnij tekst paragrafów
        paragraphs = [strip_tags(m) for m in P_TAG_RE.findall(body)]
        full_text = " ".join(paragraphs)
        if not full_text or len(full_text) < 200:
            continue

        # Flesch PL
        score = flesch_pl(full_text)
        if score:
            flesch_scores.append(score)

        # Sentence length
        for s in _split_sentences_pl(full_text):
            sentence_lengths.append(len(s.split()))

        # Fact density: liczby + lata + jednostki + nazwy własne (heurystyka)
        words = re.findall(r"\b[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+\b", full_text)
        n_words = len(words)
        n_numbers = len(re.findall(r"\b\d+(?:[.,]\d+)?(?:%|°C|°F|kg|mg|μg|ng|min|sek|h|ms|mm|cm|m|km|x)?\b", full_text))
        n_years = len(re.findall(r"\b(19|20)\d{2}\b", full_text))
        # Nazwy własne: 2+ słowa zaczynające się dużą literą
        n_proper = len(re.findall(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+){1,3}", full_text))
        if n_words >= 100:
            density = (n_numbers + n_years + n_proper) / n_words * 100
            fact_density_scores.append(density)

        # Citation density — linki klikalne + plain-text DOI w bibliografii
        citations = 0
        # Klikalne <a href>
        for href, text in A_TAG_RE.findall(p.html):
            if any(d in href.lower() for d in (".edu", ".gov", "pubmed", "doi.org", "ncbi.nlm.nih.gov",
                                                "/10.", "scholar.google", "researchgate", "wikipedia.org",
                                                "arxiv.org", "biorxiv.org", "medrxiv.org")):
                citations += 1
        # Plain-text DOI w bibliografii (bardzo częste w pracach akademickich)
        # Format: 10.xxxx/yyyy lub https://doi.org/10.xxxx/yyyy
        plain_doi = len(re.findall(r"\b10\.\d{4,}/[^\s<>\"]+", body))
        # Plain-text URL-e do PubMed/PMC w body
        plain_authority = len(re.findall(
            r"https?://(?:www\.)?(?:pubmed|ncbi\.nlm\.nih\.gov|scholar\.google|arxiv\.org|biorxiv\.org)/\S+",
            body))
        # Unikamy double-counting — bierzemy maksimum z dwóch metod
        citations = max(citations, plain_doi + plain_authority)
        if n_words >= 100:
            citation_density_scores.append(citations / n_words * 1000)

        # H2-pytania ratio
        h2s = re.findall(r"<h2\b[^>]*>(.*?)</h2>", body, re.IGNORECASE | re.DOTALL)
        h2_total = len(h2s)
        h2_q = sum(1 for h in h2s if "?" in strip_tags(h))
        if h2_total:
            h2_question_ratio.append(h2_q / h2_total * 100)

        # TL;DR detection — first 150 words: czy zawiera ≥2 liczb i ≥1 nazwę własną
        first_paragraphs = " ".join(paragraphs[:3])
        first_text = " ".join(first_paragraphs.split()[:150])
        first_numbers = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", first_text))
        first_proper = len(re.findall(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+", first_text))
        if first_numbers >= 2 and first_proper >= 1:
            tldr_present += 1

        # Freshness — datePublished vs dateModified
        m_pub = META_DATE_PUB_RE.search(p.html)
        m_mod = META_DATE_MOD_RE.search(p.html)
        if m_pub:
            try:
                pub_dt = datetime.fromisoformat(m_pub.group(1).replace("Z", "+00:00"))
                check_dt = pub_dt
                if m_mod:
                    mod_dt = datetime.fromisoformat(m_mod.group(1).replace("Z", "+00:00"))
                    check_dt = mod_dt
                age_days = (datetime.now(timezone.utc) - check_dt).days if check_dt.tzinfo else (datetime.now() - check_dt).days
                if age_days > 365:
                    freshness_warnings += 1
            except Exception:
                pass

    # Raporty
    if flesch_scores:
        avg_fog = sum(flesch_scores) / len(flesch_scores)
        findings.append(f"📖 FOG-PL (Pisarek): średnio {avg_fog:.1f} (im niższy, tym łatwiejszy)")
        if avg_fog < 9:
            findings.append("   ✅ Łatwy tekst (klasy 7-8 SP)")
        elif avg_fog < 13:
            findings.append("   ✅ Standardowy poziom (LO) — dobry dla AEO i ogólnego odbiorcy")
        elif avg_fog < 17:
            findings.append("   ⚠️ Trudny (akademicki/specjalistyczny) — OK dla nauki, mniejsza cytowalność AI")
        else:
            findings.append("   ❌ Bardzo trudny (>17) — naukowy/prawniczy, ChatGPT cytuje rzadziej")

    if sentence_lengths:
        avg_sent = sum(sentence_lengths) / len(sentence_lengths)
        long_sent = sum(1 for x in sentence_lengths if x > 35)
        long_pct = long_sent / len(sentence_lengths) * 100
        findings.append(f"📏 Średnia długość zdania: {avg_sent:.1f} słów; >35 słów: {long_pct:.0f}%")
        if avg_sent > 25:
            findings.append("   ⚠️ Długie zdania — modele AI streszczają trudniej")

    if fact_density_scores:
        avg_fd = sum(fact_density_scores) / len(fact_density_scores)
        findings.append(f"🔢 Fact density: {avg_fd:.1f} (liczby + nazwy + lata) / 100 słów")
        if avg_fd >= 8:
            findings.append("   ✅ Wysoka gęstość faktów — ChatGPT/Perplexity to uwielbiają")
        elif avg_fd >= 4:
            findings.append("   ⚠️ Średnia gęstość — można podnieść konkretami")
        else:
            findings.append("   ❌ Niska gęstość faktów — treść mało cytowalna przez AI")

    if citation_density_scores:
        avg_cd = sum(citation_density_scores) / len(citation_density_scores)
        findings.append(f"🔗 Citation density: {avg_cd:.1f} linków autorytatywnych / 1000 słów")
        if avg_cd >= 5:
            findings.append("   ✅ Wysokie cytowanie — silny sygnał E-E-A-T")
        elif avg_cd >= 2:
            findings.append("   ⚠️ Średnie cytowanie")
        else:
            findings.append("   ❌ Brak linków do .edu/.gov/PubMed/DOI — straszne dla wiarygodności")

    if h2_question_ratio:
        avg_q = sum(h2_question_ratio) / len(h2_question_ratio)
        findings.append(f"❓ H2-pytania: {avg_q:.0f}% nagłówków")
        if avg_q >= 30:
            findings.append("   ✅ FAQ-ready — modele AI extraktują direct answers")
        else:
            findings.append("   ⚠️ Mało pytań w H2 — przeformułuj nagłówki na pytania")

    findings.append(f"📌 TL;DR (≥2 liczb + 1 nazwa własna w pierwszych 150 słowach): {tldr_present}/{len(article_pages)} stron")
    if freshness_warnings:
        findings.append(f"⏰ Artykuły niezaktualizowane >1 rok: {freshness_warnings}/{len(article_pages)}")

    # Score (composite)
    score_parts = []
    if flesch_scores:
        # FOG-PL: niższy = łatwiejszy. Konwertuj na 0-100 (im łatwiejszy, tym wyżej).
        # 9 (łatwe) → 100, 13 (LO) → 80, 17 (akademickie) → 50, 25+ → 0
        avg_fog = sum(flesch_scores) / len(flesch_scores)
        readability_score = max(0, min(100, 100 - (avg_fog - 9) * 6))
        score_parts.append(readability_score)
    if fact_density_scores:
        avg_fd = sum(fact_density_scores) / len(fact_density_scores)
        score_parts.append(min(100, avg_fd * 10))  # 10/100 słów = 100%
    if citation_density_scores:
        avg_cd = sum(citation_density_scores) / len(citation_density_scores)
        score_parts.append(min(100, avg_cd * 15))  # 6.66/1000 słów = 100%
    if h2_question_ratio:
        score_parts.append(min(100, sum(h2_question_ratio) / len(h2_question_ratio) * 2))
    if article_pages:
        score_parts.append(tldr_present / len(article_pages) * 100)
    quality_score = int(sum(score_parts) / len(score_parts)) if score_parts else 0

    return {
        "findings": findings,
        "score": quality_score,
        "stats": {
            "pages_scanned": len(article_pages),
            "fog_pl_avg": round(sum(flesch_scores) / max(len(flesch_scores), 1), 1) if flesch_scores else None,
            "sentence_avg_words": round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1) if sentence_lengths else None,
            "fact_density_per_100w": round(sum(fact_density_scores) / max(len(fact_density_scores), 1), 1) if fact_density_scores else None,
            "citation_density_per_1000w": round(sum(citation_density_scores) / max(len(citation_density_scores), 1), 1) if citation_density_scores else None,
            "h2_question_ratio_pct": round(sum(h2_question_ratio) / max(len(h2_question_ratio), 1), 1) if h2_question_ratio else None,
            "tldr_pages": tldr_present,
            "stale_pages": freshness_warnings,
        },
    }


# ─── MAIN ─────────────────────────────────────────────────────────────────────

MODULE_FUNCS = {
    "performance": audit_performance,
    "a11y": audit_accessibility,
    "content": audit_content_quality,
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Zaawansowany audyt: Performance/CWV + Accessibility/WCAG + Content Quality.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python auditor_advanced.py --folder ./output/zdrowie-fit\n"
            "  python auditor_advanced.py --url https://zdrowie.fit --pages 10\n"
            "  python auditor_advanced.py --folder ./build --modules content --json adv.json\n"
        ),
    )
    ap.add_argument("--folder", help="Folder z plikami HTML")
    ap.add_argument("--url", help="URL strony live")
    ap.add_argument("--pages", type=int, default=20, help="Limit stron (default 20)")
    ap.add_argument("--modules", default="performance,a11y,content",
                    help="csv modułów. Dostępne: performance, a11y, content (default: wszystkie)")
    ap.add_argument("--json", help="Zapisz raport jako JSON")
    args = ap.parse_args()

    if not args.folder and not args.url:
        print("❌ Podaj --folder lub --url")
        return 2

    folder = Path(args.folder).resolve() if args.folder else None
    if folder:
        pages = collect_pages_local(folder, args.pages)
        source_label = f"folder: {folder}"
    else:
        pages = collect_pages_url(args.url, args.pages)
        source_label = f"url: {args.url}"

    if not pages:
        print("❌ Brak stron do audytu")
        return 1

    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    invalid = [m for m in modules if m not in MODULE_FUNCS]
    if invalid:
        print(f"❌ Nieznane moduły: {invalid}. Dostępne: {list(MODULE_FUNCS.keys())}")
        return 2

    print("=" * 60)
    print("  SEO/AEO/GEO AUDIT — ADVANCED MODULES")
    print("=" * 60)
    print(f"  Source: {source_label}")
    print(f"  Pages:  {len(pages)}")
    print(f"  Modules: {', '.join(modules)}")

    results: dict[str, dict] = {}
    for m in modules:
        print(f"\n{'═' * 50}")
        print(f"  {m.upper()}")
        print('═' * 50)
        try:
            r = MODULE_FUNCS[m](pages, folder)
            results[m] = r
            for line in r["findings"]:
                print(line)
            print(f"\n  ┌─ SCORE [{m}]: {r['score']}/100")
        except Exception as e:
            print(f"⚠️ Moduł {m} przerwany: {e}")
            results[m] = {"error": str(e), "score": 0, "findings": []}

    # Aggregate
    avg_score = int(sum(r.get("score", 0) for r in results.values()) / len(results))
    print("\n" + "=" * 60)
    print(f"  ŚREDNIA SCORE: {avg_score}/100")
    print("=" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": source_label,
                "pages": len(pages),
                "modules": results,
                "avg_score": avg_score,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"💾 JSON: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
