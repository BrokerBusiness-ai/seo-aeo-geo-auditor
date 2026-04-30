#!/usr/bin/env python3
"""
report_html.py — generator self-contained HTML raportu z audytów.

Wejście:
  - JSON z auditor.py i/lub auditor_advanced.py i/lub validator.py i/lub monitor.py
Wyjście:
  - Self-contained HTML (z embedded Chart.js z CDN), gotowy do druku jako PDF

Użycie:
    python report_html.py --inputs last_report.json,adv.json,validator.json --out report.html
    python report_html.py --history --site zdrowie-fit --out trend.html
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
from datetime import datetime
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "history"


HTML_TEMPLATE = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Raport audytu SEO/AEO/GEO — {site}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px;
    font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
    background: #f8f8f7; color: #0f172a; font-size: 14px; line-height: 1.55;
  }}
  .container {{ max-width: 980px; margin: 0 auto; }}
  header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    border-bottom: 2px solid #0f172a; padding-bottom: 16px; margin-bottom: 24px;
  }}
  h1 {{ font-size: 26px; margin: 0; font-weight: 700; letter-spacing: -0.02em; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
       color: #64748b; margin: 28px 0 10px 0; font-weight: 600; }}
  h3 {{ font-size: 16px; margin: 12px 0 6px 0; font-weight: 600; }}
  .meta {{ color: #64748b; font-size: 12px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 2fr; gap: 24px; }}
  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 18px; margin-bottom: 16px;
  }}
  .gauge-wrap {{ position: relative; width: 100%; max-width: 240px; aspect-ratio: 1; margin: 0 auto; }}
  .gauge-num {{
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    flex-direction: column; font-weight: 700; font-size: 44px;
  }}
  .gauge-num small {{ font-size: 11px; font-weight: 500; color: #64748b;
                     text-transform: uppercase; letter-spacing: 0.06em; margin-top: 4px; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px; }}
  .stat {{ text-align: center; padding: 10px 4px; background: #f8fafc; border-radius: 6px; }}
  .stat-num {{ font-size: 22px; font-weight: 700; }}
  .stat.ok .stat-num {{ color: #16a34a; }}
  .stat.fail .stat-num {{ color: #dc2626; }}
  .stat.warn .stat-num {{ color: #d97706; }}
  .stat-lbl {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table th, table td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e8f0; }}
  table th {{ background: #f8fafc; font-weight: 600; font-size: 11px;
              text-transform: uppercase; letter-spacing: 0.05em; color: #475569; }}
  .findings {{ font-size: 13px; margin: 0; padding-left: 22px; }}
  .findings li {{ margin: 4px 0; }}
  .module {{ margin-bottom: 14px; padding-bottom: 14px; border-bottom: 1px dashed #e2e8f0; }}
  .module:last-child {{ border-bottom: 0; }}
  .module-head {{ display: flex; justify-content: space-between; align-items: center; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
  }}
  .badge.ok {{ background: #dcfce7; color: #166534; }}
  .badge.fail {{ background: #fee2e2; color: #991b1b; }}
  .badge.warn {{ background: #fef3c7; color: #92400e; }}
  footer {{ text-align: center; color: #94a3b8; font-size: 11px; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; }}
  @media print {{
    body {{ padding: 16px; background: white; font-size: 12px; }}
    .card {{ break-inside: avoid; }}
    table {{ font-size: 11px; }}
  }}
</style>
</head>
<body>
<div class="container">

<header>
  <div>
    <h1>Audyt SEO / AEO / GEO</h1>
    <div class="meta">{site} · {timestamp}</div>
  </div>
  <div class="meta">v1.0 · seo-aeo-geo-auditor</div>
</header>

<div class="grid">
  <div class="card">
    <h2>Wynik łączny</h2>
    <div class="gauge-wrap">
      <canvas id="scoreGauge"></canvas>
      <div class="gauge-num">
        <span>{score}</span><small>SCORE</small>
      </div>
    </div>
    <div class="stats">
      <div class="stat ok"><div class="stat-num">{ok}</div><div class="stat-lbl">OK</div></div>
      <div class="stat fail"><div class="stat-num">{fail}</div><div class="stat-lbl">FAIL</div></div>
      <div class="stat warn"><div class="stat-num">{warn}</div><div class="stat-lbl">WARN</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Punktacja per warstwa</h2>
    <canvas id="layersChart" style="max-height:280px;"></canvas>
  </div>
</div>

<div class="card">
  <h2>Moduły szczegółowe</h2>
  {modules_html}
</div>

{trend_html}

<div class="card">
  <h2>Rekomendacje (top 10)</h2>
  <ol class="findings">
    {recommendations_html}
  </ol>
</div>

<footer>
  Wygenerowane przez seo-aeo-geo-auditor · {timestamp}<br>
  Marek Porycki · Claude Orchestrator
</footer>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
<script>
const SCORE = {score_num};
const SCORE_COLOR = SCORE >= 80 ? "#16a34a" : SCORE >= 50 ? "#d97706" : "#dc2626";
new Chart(document.getElementById("scoreGauge"), {{
  type: "doughnut",
  data: {{ datasets: [{{ data: [SCORE, 100 - SCORE], backgroundColor: [SCORE_COLOR, "#e2e8f0"], borderWidth: 0 }}] }},
  options: {{ cutout: "75%", plugins: {{ legend: {{ display: false }} }} }}
}});

new Chart(document.getElementById("layersChart"), {{
  type: "bar",
  data: {layers_data},
  options: {{
    indexAxis: "y",
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ min: 0, max: 100, ticks: {{ stepSize: 20 }} }} }}
  }}
}});

{trend_chart_js}
</script>

</body>
</html>"""


def render_module(name: str, status: str, findings: list[str]) -> str:
    badge_cls = status if status in ("ok", "fail", "warn") else "warn"
    findings_html = "".join(f"<li>{escape(f)}</li>" for f in findings[:15])
    return f"""<div class="module">
  <div class="module-head">
    <h3>{escape(name)}</h3>
    <span class="badge {badge_cls}">{status.upper()}</span>
  </div>
  <ul class="findings">{findings_html}</ul>
</div>"""


def aggregate_findings(inputs: list[dict]) -> tuple[list[str], int, int, int]:
    """Połącz findings ze wszystkich źródeł, policz ok/fail/warn."""
    all_findings: list[str] = []
    for inp in inputs:
        if "lines" in inp:  # auditor.py
            all_findings.extend(inp["lines"])
        if "modules" in inp:  # auditor_advanced.py
            for mod_name, mod_data in inp["modules"].items():
                all_findings.extend(mod_data.get("findings", []))

    ok = sum(1 for f in all_findings if "✅" in f)
    fail = sum(1 for f in all_findings if "❌" in f)
    warn = sum(1 for f in all_findings if "⚠️" in f)
    return all_findings, ok, fail, warn


def extract_recommendations(all_findings: list[str], top_n: int = 10) -> list[str]:
    """Wyciągnij top problemów (priority = errors first, potem warnings)."""
    errors = [f.strip() for f in all_findings if "❌" in f]
    warnings = [f.strip() for f in all_findings if "⚠️" in f]
    return (errors + warnings)[:top_n]


def build_modules_section(inputs: list[dict]) -> str:
    parts: list[str] = []
    for inp in inputs:
        if "modules" in inp:  # advanced
            for mod_name, mod_data in inp["modules"].items():
                score = mod_data.get("score", 0)
                status = "ok" if score >= 80 else "warn" if score >= 50 else "fail"
                parts.append(render_module(f"[ADV] {mod_name}", status, mod_data.get("findings", [])))
        elif "lines" in inp:  # main auditor
            # Grupuj po nagłówkach modułów
            current_name = "Moduł"
            current_findings: list[str] = []
            for line in inp.get("lines", []):
                # NOTE: auditor.py emits ASCII-only headers (JAKOSC, BEZPIECZ),
                # ale w razie kompatybilności wstecznej obsługujemy też wersje z diakrytykami.
                _module_keys = ("PLIKI", "ROBOTS", "SCHEMA", "SITEMAP",
                                "BEZPIECZ", "PWA", "FONTY",
                                "JAKOSC", "JAKOŚĆ")
                if line.startswith("\n") and any(x in line for x in _module_keys):
                    if current_findings:
                        ok = sum(1 for f in current_findings if "✅" in f)
                        fail = sum(1 for f in current_findings if "❌" in f)
                        status = "ok" if fail == 0 else "fail"
                        parts.append(render_module(current_name, status, current_findings))
                    current_name = line.strip()
                    current_findings = []
                elif line.strip() and not line.startswith("─"):
                    current_findings.append(line)
            if current_findings:
                ok = sum(1 for f in current_findings if "✅" in f)
                fail = sum(1 for f in current_findings if "❌" in f)
                status = "ok" if fail == 0 else "fail"
                parts.append(render_module(current_name, status, current_findings))
    return "\n".join(parts) if parts else "<p class=\"meta\">Brak modułów do raportu.</p>"


def build_layers_data(inputs: list[dict]) -> dict:
    labels: list[str] = []
    scores: list[int] = []
    colors: list[str] = []

    for inp in inputs:
        if "score" in inp and "lines" in inp:
            labels.append("SEO/AEO/GEO Main")
            scores.append(inp["score"])
        if "modules" in inp:
            for mod_name, mod_data in inp["modules"].items():
                labels.append(mod_name.title())
                scores.append(mod_data.get("score", 0))
        if "summary" in inp:  # validator
            errs = inp["summary"].get("errors", 0)
            warns = inp["summary"].get("warnings", 0)
            labels.append("Schema.org Validator")
            scores.append(max(0, 100 - errs * 5 - warns))

    for s in scores:
        colors.append("#16a34a" if s >= 80 else "#d97706" if s >= 50 else "#dc2626")

    return {
        "labels": labels,
        "datasets": [{
            "data": scores,
            "backgroundColor": colors,
            "borderRadius": 4,
        }]
    }


def build_trend_section(history_files: list[Path]) -> tuple[str, str]:
    """Buduje sekcję trendu jeśli mamy >1 snapshot."""
    if len(history_files) < 2:
        return "", ""
    snapshots = []
    for f in sorted(history_files):
        try:
            snapshots.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    if len(snapshots) < 2:
        return "", ""
    labels = [s["timestamp"][:16].replace("T", " ") for s in snapshots]
    scores = [s.get("composite_score", 0) for s in snapshots]
    html = """<div class="card">
  <h2>Trend score (historia)</h2>
  <canvas id="trendChart" style="max-height:280px;"></canvas>
</div>"""
    js = f"""new Chart(document.getElementById("trendChart"), {{
  type: "line",
  data: {{
    labels: {json.dumps(labels, ensure_ascii=False)},
    datasets: [{{
      label: "Composite Score",
      data: {json.dumps(scores)},
      borderColor: "#0f172a",
      backgroundColor: "rgba(15, 23, 42, 0.1)",
      tension: 0.3,
      fill: true,
    }}]
  }},
  options: {{ scales: {{ y: {{ min: 0, max: 100 }} }} }}
}});"""
    return html, js


def main() -> int:
    ap = argparse.ArgumentParser(description="Generator HTML raportu z audytów SEO/AEO/GEO.")
    ap.add_argument("--inputs", help="CSV ścieżek do JSON-ów (auditor, advanced, validator)")
    ap.add_argument("--history", action="store_true", help="Dorzucić trend z history/")
    ap.add_argument("--site", help="Slug strony (do filtra historii i tytułu)")
    ap.add_argument("--out", required=True, help="Plik wyjściowy HTML")
    args = ap.parse_args()

    inputs: list[dict] = []
    if args.inputs:
        for path in args.inputs.split(","):
            p = Path(path.strip())
            if p.exists():
                try:
                    inputs.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception as e:
                    print(f"⚠️ Nie udało się wczytać {p}: {e}")

    if not inputs:
        print("❌ Brak danych wejściowych. Podaj --inputs path1.json,path2.json")
        return 2

    all_findings, ok, fail, warn = aggregate_findings(inputs)

    # Composite score: średnia ze score'ów we wszystkich inputach
    scores = [inp.get("score") for inp in inputs if "score" in inp]
    scores += [inp.get("avg_score") for inp in inputs if "avg_score" in inp]
    scores += [max(0, 100 - inp.get("summary", {}).get("errors", 0) * 5 - inp.get("summary", {}).get("warnings", 0))
               for inp in inputs if "summary" in inp]
    composite = int(sum(scores) / len(scores)) if scores else 0

    site = args.site or "(brak nazwy)"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    modules_html = build_modules_section(inputs)
    recommendations = extract_recommendations(all_findings, 10)
    recommendations_html = "".join(f"<li>{escape(r.strip())}</li>" for r in recommendations) or "<li>Brak rekomendacji — wszystko OK!</li>"
    layers_data = json.dumps(build_layers_data(inputs), ensure_ascii=False)

    trend_html, trend_js = "", ""
    if args.history and args.site:
        files = [f for f in HISTORY_DIR.glob("*.json") if args.site in f.stem]
        trend_html, trend_js = build_trend_section(files)

    final = HTML_TEMPLATE.format(
        site=escape(site),
        timestamp=escape(timestamp),
        score=composite,
        score_num=composite,
        ok=ok, fail=fail, warn=warn,
        modules_html=modules_html,
        recommendations_html=recommendations_html,
        layers_data=layers_data,
        trend_html=trend_html,
        trend_chart_js=trend_js,
    )

    Path(args.out).write_text(final, encoding="utf-8")
    print(f"✅ Raport HTML zapisany: {args.out}")
    print(f"   Otwórz w przeglądarce, lub: Plik > Drukuj > Zapisz jako PDF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
