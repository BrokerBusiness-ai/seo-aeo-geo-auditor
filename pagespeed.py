#!/usr/bin/env python3
"""
pagespeed.py — Google PageSpeed Insights API integration.

Real metrics z prawdziwego Chrome (lab) + opcjonalnie CrUX field data
(jeśli strona ma wystarczającą próbkę użytkowników). Bez klucza API
(rate-limit ~25/dzień). Z kluczem (free) — wyższy limit.

Co dostajesz:
  - 4 kategorie score (Performance, Accessibility, Best Practices, SEO) 0-100
  - Lab metrics: LCP, INP/TBT, CLS, FCP, TTI, SI
  - Field metrics (CrUX): real-user LCP/INP/CLS jeśli dostępne
  - Top 10 Opportunities z impactem (ms/KB save) + ścieżki plików
  - Top Accessibility issues z konkretnymi elementami
  - Markdown report + JSON export

Użycie:
    python pagespeed.py --url https://zdrowie.fit
    python pagespeed.py --url https://zdrowie.fit --strategy desktop
    python pagespeed.py --url https://zdrowie.fit --json psi.json --md psi.md
    python pagespeed.py --url https://zdrowie.fit --api-key XXX  # podwyższony limit

API:
    https://www.googleapis.com/pagespeedonline/v5/runPagespeed
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
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; SEO-AEO-GEO-PageSpeed/1.0)"
PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# ─── PSI CLIENT ───────────────────────────────────────────────────────────────

def call_psi(url: str, strategy: str = "mobile", api_key: str | None = None,
             timeout: int = 60) -> dict:
    """Wywołaj PageSpeed Insights API. Zwraca pełny JSON response."""
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance,accessibility,best-practices,seo",
    }
    if api_key:
        params["key"] = api_key

    # PSI wymaga MULTIPLE category= params (nie comma-separated)
    cats = "&".join(f"category={c}" for c in ["performance", "accessibility", "best-practices", "seo"])
    base_params = {k: v for k, v in params.items() if k != "category"}
    full_url = f"{PSI_ENDPOINT}?{urllib.parse.urlencode(base_params)}&{cats}"

    print(f"📡 PSI API call: {strategy} — {url}")
    print(f"   (może potrwać 30-60s, Google odpala prawdziwy Chrome)")

    req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("message", body)
        except Exception:
            msg = body
        raise RuntimeError(f"PSI API HTTP {e.code}: {msg}")
    except Exception as e:
        raise RuntimeError(f"PSI API error: {e}")


# ─── EKSTRAKCJA ───────────────────────────────────────────────────────────────

def extract_categories(psi: dict) -> dict[str, int]:
    cats = psi.get("lighthouseResult", {}).get("categories", {})
    return {
        "performance": int((cats.get("performance", {}).get("score") or 0) * 100),
        "accessibility": int((cats.get("accessibility", {}).get("score") or 0) * 100),
        "best_practices": int((cats.get("best-practices", {}).get("score") or 0) * 100),
        "seo": int((cats.get("seo", {}).get("score") or 0) * 100),
    }


LAB_METRICS_KEYS = {
    "LCP": "largest-contentful-paint",
    "FCP": "first-contentful-paint",
    "CLS": "cumulative-layout-shift",
    "TBT": "total-blocking-time",
    "TTI": "interactive",
    "SI":  "speed-index",
}


def extract_lab_metrics(psi: dict) -> dict[str, dict]:
    audits = psi.get("lighthouseResult", {}).get("audits", {})
    out = {}
    for short, key in LAB_METRICS_KEYS.items():
        a = audits.get(key, {})
        out[short] = {
            "value": a.get("displayValue", "—"),
            "numeric": a.get("numericValue"),
            "score": a.get("score"),
        }
    return out


CRUX_KEYS = {
    "LCP": "LARGEST_CONTENTFUL_PAINT_MS",
    "INP": "INTERACTION_TO_NEXT_PAINT",
    "CLS": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
    "FCP": "FIRST_CONTENTFUL_PAINT_MS",
    "FID": "FIRST_INPUT_DELAY_MS",
    "TTFB": "EXPERIMENTAL_TIME_TO_FIRST_BYTE",
}


def extract_crux(psi: dict) -> dict[str, dict] | None:
    """Real-user metrics z Chrome User Experience Report (jeśli dostępne)."""
    le = psi.get("loadingExperience", {})
    metrics = le.get("metrics", {})
    if not metrics:
        return None
    out = {}
    for short, key in CRUX_KEYS.items():
        m = metrics.get(key)
        if m:
            val = m.get("percentile")
            cat = m.get("category", "")
            if short == "CLS":
                # CLS jest w setnych — przekonwertuj
                val = val / 100 if val else val
                out[short] = {"value": f"{val:.3f}", "category": cat}
            elif "MS" in key:
                out[short] = {"value": f"{val} ms", "category": cat}
            else:
                out[short] = {"value": str(val), "category": cat}
    return out if out else None


# Audyty które są "Opportunities" — czyli mają numericSavings (oszczędność ms/B)
OPPORTUNITY_AUDITS = [
    "render-blocking-resources",
    "unused-css-rules",
    "unused-javascript",
    "modern-image-formats",
    "uses-optimized-images",
    "uses-text-compression",
    "uses-responsive-images",
    "efficient-animated-content",
    "duplicated-javascript",
    "legacy-javascript",
    "preload-lcp-image",
    "uses-rel-preconnect",
    "uses-rel-preload",
    "font-display",
    "third-party-summary",
    "bootup-time",
    "mainthread-work-breakdown",
    "dom-size",
    "critical-request-chains",
    "user-timings",
    "uses-long-cache-ttl",
    "total-byte-weight",
    "offscreen-images",
    "redirects",
    "server-response-time",
]


def extract_opportunities(psi: dict, top_n: int = 15) -> list[dict]:
    audits = psi.get("lighthouseResult", {}).get("audits", {})
    opps = []
    for key in OPPORTUNITY_AUDITS:
        a = audits.get(key)
        if not a:
            continue
        score = a.get("score")
        if score is None or score >= 0.9:
            continue  # już dobrze
        details = a.get("details", {}) or {}
        items = details.get("items", []) or []
        savings_ms = details.get("overallSavingsMs", 0)
        savings_bytes = details.get("overallSavingsBytes", 0)
        opps.append({
            "id": key,
            "title": a.get("title", key),
            "description": a.get("description", "").split(".")[0] + ".",
            "score": score,
            "display": a.get("displayValue", ""),
            "savings_ms": savings_ms,
            "savings_kb": round(savings_bytes / 1024) if savings_bytes else 0,
            "items_count": len(items),
            "items_top3": [
                {
                    "url": (it.get("url") or it.get("source", {}).get("url") or "—")[:120],
                    "wasted_ms": it.get("wastedMs", 0),
                    "wasted_kb": round(it.get("wastedBytes", 0) / 1024) if it.get("wastedBytes") else 0,
                }
                for it in items[:3]
            ],
        })
    # Sortuj po impact (savings_ms primary, savings_kb secondary)
    opps.sort(key=lambda x: (-x["savings_ms"], -x["savings_kb"]))
    return opps[:top_n]


A11Y_AUDIT_KEYS = [
    "color-contrast", "image-alt", "label", "link-name", "button-name",
    "html-has-lang", "html-lang-valid", "meta-viewport", "duplicate-id-aria",
    "aria-allowed-attr", "aria-required-attr", "aria-roles",
    "heading-order", "list", "listitem", "tabindex",
    "focus-traps", "focusable-controls", "interactive-element-affordance",
    "logical-tab-order", "managed-focus", "use-landmarks",
]


def extract_accessibility_issues(psi: dict, top_n: int = 15) -> list[dict]:
    audits = psi.get("lighthouseResult", {}).get("audits", {})
    issues = []
    for key in A11Y_AUDIT_KEYS:
        a = audits.get(key)
        if not a:
            continue
        score = a.get("score")
        if score is None or score == 1:
            continue  # passed
        details = a.get("details", {}) or {}
        items = details.get("items", []) or []
        if not items and score == 1:
            continue
        issues.append({
            "id": key,
            "title": a.get("title", key),
            "description": (a.get("description", "") or "").split(".")[0] + ".",
            "items_count": len(items),
            "items_top3": [
                {
                    "selector": (it.get("node", {}).get("selector") or "")[:100],
                    "snippet": (it.get("node", {}).get("snippet") or "")[:140].replace("\n", " "),
                    "explanation": (it.get("node", {}).get("explanation") or "")[:200],
                }
                for it in items[:3]
            ],
        })
    return issues[:top_n]


# ─── RENDER MARKDOWN ──────────────────────────────────────────────────────────

def render_md(url: str, strategy: str, psi: dict,
              cats: dict, lab: dict, crux: dict | None,
              opps: list[dict], a11y: list[dict]) -> str:
    lines = []
    lines.append(f"# PageSpeed Insights — {url}")
    lines.append(f"**Strategia:** {strategy} · **Wygenerowane:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Score table
    def emoji(s: int) -> str:
        return "✅" if s >= 90 else "⚠️" if s >= 50 else "❌"

    lines.append("## Wyniki kategorii")
    lines.append("")
    lines.append("| Kategoria | Score | Status |")
    lines.append("|---|---|---|")
    lines.append(f"| Performance      | **{cats['performance']}/100** | {emoji(cats['performance'])} |")
    lines.append(f"| Accessibility    | **{cats['accessibility']}/100** | {emoji(cats['accessibility'])} |")
    lines.append(f"| Best Practices   | **{cats['best_practices']}/100** | {emoji(cats['best_practices'])} |")
    lines.append(f"| SEO              | **{cats['seo']}/100** | {emoji(cats['seo'])} |")
    lines.append("")

    # Lab metrics
    lines.append("## Metryki LAB (Chrome headless)")
    lines.append("")
    lines.append("| Metryka | Wartość | Cel | Status |")
    lines.append("|---|---|---|---|")
    targets = {"LCP": "<2.5s", "FCP": "<1.8s", "CLS": "<0.1", "TBT": "<200ms", "TTI": "<3.8s", "SI": "<3.4s"}
    for k, v in lab.items():
        score = v.get("score")
        st = "✅" if (score or 0) >= 0.9 else "⚠️" if (score or 0) >= 0.5 else "❌"
        lines.append(f"| {k} | {v['value']} | {targets.get(k, '')} | {st} |")
    lines.append("")

    # CrUX
    if crux:
        lines.append("## Real-User Metrics (CrUX field data)")
        lines.append("")
        lines.append("| Metryka | Wartość | Kategoria |")
        lines.append("|---|---|---|")
        for k, v in crux.items():
            lines.append(f"| {k} | {v['value']} | {v['category']} |")
        lines.append("")
    else:
        lines.append("ℹ️ Brak CrUX field data — strona ma za mało użytkowników w Chrome User Experience Report. Tylko lab metrics dostępne.")
        lines.append("")

    # Opportunities
    if opps:
        lines.append("## 🎯 Opportunities — top fixy z impactem")
        lines.append("")
        for i, o in enumerate(opps, 1):
            saving = []
            if o["savings_ms"]:
                saving.append(f"-{o['savings_ms']:.0f}ms")
            if o["savings_kb"]:
                saving.append(f"-{o['savings_kb']}KB")
            saving_str = " ".join(saving) if saving else f"score {o['score']:.2f}"
            lines.append(f"### {i}. {o['title']}  `{saving_str}`")
            lines.append(f"{o['description']}")
            if o["display"]:
                lines.append(f"> {o['display']}")
            if o["items_top3"]:
                lines.append("**Konkretnie (top 3 zasoby):**")
                for it in o["items_top3"]:
                    extra = []
                    if it["wasted_ms"]:
                        extra.append(f"{it['wasted_ms']}ms")
                    if it["wasted_kb"]:
                        extra.append(f"{it['wasted_kb']}KB")
                    extra_str = f" ({', '.join(extra)})" if extra else ""
                    lines.append(f"- `{it['url']}`{extra_str}")
            lines.append("")
    else:
        lines.append("✅ Brak Opportunities — wszystkie performance audyty przeszły z 90+.")
        lines.append("")

    # A11y issues
    if a11y:
        lines.append("## ♿ Accessibility issues")
        lines.append("")
        for i, issue in enumerate(a11y, 1):
            lines.append(f"### {i}. {issue['title']}  ({issue['items_count']} elementów)")
            lines.append(f"{issue['description']}")
            for it in issue["items_top3"]:
                if it["selector"]:
                    lines.append(f"- `{it['selector']}`")
                    if it["snippet"]:
                        lines.append(f"  ```html\n  {it['snippet']}\n  ```")
                    if it["explanation"]:
                        lines.append(f"  > {it['explanation']}")
            lines.append("")
    else:
        lines.append("✅ Brak accessibility issues w PSI audicie.")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("*Raport wygenerowany przez `pagespeed.py` · seo-aeo-geo-auditor*")
    return "\n".join(lines)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="PageSpeed Insights real diagnose + actionable fixes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python pagespeed.py --url https://zdrowie.fit\n"
            "  python pagespeed.py --url https://zdrowie.fit --strategy desktop --md psi.md\n"
            "  python pagespeed.py --url https://example.com --json psi.json --api-key YOUR_KEY\n"
            "\n"
            "Bez klucza API — Google rate-limituje ~25 req/dzień. Klucz free na:\n"
            "  https://console.cloud.google.com → APIs → PageSpeed Insights API\n"
        ),
    )
    ap.add_argument("--url", required=True, help="Pełny URL strony do audytu")
    ap.add_argument("--strategy", choices=["mobile", "desktop"], default="mobile",
                    help="Strategia urządzenia (default: mobile — bo Google rankuje po mobile)")
    ap.add_argument("--api-key", default=os.environ.get("PSI_API_KEY", ""),
                    help="Google API key (opcjonalny). Domyślnie czyta z env PSI_API_KEY.")
    ap.add_argument("--json", help="Zapisz pełny PSI response jako JSON")
    ap.add_argument("--md", help="Zapisz raport Markdown")
    ap.add_argument("--quiet", action="store_true", help="Mniej outputu w terminalu")
    args = ap.parse_args()

    try:
        psi = call_psi(args.url, args.strategy, args.api_key)
    except Exception as e:
        print(f"❌ {e}")
        return 1

    cats = extract_categories(psi)
    lab = extract_lab_metrics(psi)
    crux = extract_crux(psi)
    opps = extract_opportunities(psi)
    a11y = extract_accessibility_issues(psi)

    md = render_md(args.url, args.strategy, psi, cats, lab, crux, opps, a11y)

    if not args.quiet:
        print()
        print(md)

    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"\n💾 Markdown: {args.md}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "url": args.url,
                "strategy": args.strategy,
                "timestamp": datetime.now().isoformat(),
                "categories": cats,
                "lab_metrics": lab,
                "crux_metrics": crux,
                "opportunities": opps,
                "accessibility_issues": a11y,
                "raw_psi": psi,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"💾 JSON: {args.json}")

    # Composite score (średnia 4 kategorii)
    avg = sum(cats.values()) // 4
    return 0 if avg >= 80 else 1


if __name__ == "__main__":
    sys.exit(main())
