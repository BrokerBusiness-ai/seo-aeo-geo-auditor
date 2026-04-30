#!/usr/bin/env python3
"""
gui.py — lokalny web GUI dla seo-aeo-geo-auditor.

JEDNO POLE. JEDEN PRZYCISK. PEŁNY RAPORT.

Użycie:
    python gui.py
    python gui.py --port 8765 --open
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
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable
REPORTS_DIR = HERE / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# In-memory progress per job_id
JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()

# TTL (seconds) — after this, completed jobs are evicted from JOBS to prevent
# unbounded memory growth on long-running servers.
JOB_TTL_SECONDS = 3600  # 1 hour
JOB_MAX_ENTRIES = 200    # hard cap; oldest evicted first


def _cleanup_jobs() -> None:
    """Evict old/excess JOBS entries. Caller must NOT hold JOB_LOCK."""
    now = time.time()
    with JOB_LOCK:
        # 1) TTL — drop completed jobs older than JOB_TTL_SECONDS
        stale = []
        for jid, j in JOBS.items():
            ts = j.get("_finished_at") or j.get("_started_at") or 0
            if j.get("done") and ts and (now - ts) > JOB_TTL_SECONDS:
                stale.append(jid)
        for jid in stale:
            JOBS.pop(jid, None)
        # 2) Hard cap — if still too many, drop oldest (by _started_at)
        if len(JOBS) > JOB_MAX_ENTRIES:
            ordered = sorted(
                JOBS.items(),
                key=lambda kv: kv[1].get("_started_at", 0),
            )
            for jid, _ in ordered[: len(JOBS) - JOB_MAX_ENTRIES]:
                JOBS.pop(jid, None)


# ─── HTML SPA ─────────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEO/AEO/GEO Auditor</title>
<style>
  :root { color-scheme: light; --bg: #f8f8f7; --card: #fff; --border: #e2e8f0;
          --text: #0f172a; --muted: #64748b; --accent: #0f172a; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 0; font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
         background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; }
  .wrap { max-width: 920px; margin: 0 auto; padding: 32px 24px 80px; }
  header { text-align: center; margin-bottom: 32px; }
  h1 { font-size: 32px; margin: 0 0 6px 0; font-weight: 700; letter-spacing: -0.025em; }
  .tagline { color: var(--muted); font-size: 15px; }

  .hero { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
          padding: 28px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }
  .input-row { display: flex; gap: 10px; }
  .input-row input { flex: 1; padding: 14px 16px; font-size: 16px; border: 1px solid #cbd5e1;
                     border-radius: 10px; background: #fff; outline: none; transition: border .15s; }
  .input-row input:focus { border-color: #0f172a; }
  .input-row button { padding: 14px 28px; font-size: 16px; font-weight: 600; cursor: pointer;
                      background: #0f172a; color: #fff; border: 0; border-radius: 10px;
                      transition: all .15s; white-space: nowrap; }
  .input-row button:hover:not(:disabled) { background: #1e293b; transform: translateY(-1px); }
  .input-row button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
  .hero-hint { color: var(--muted); font-size: 13px; margin-top: 10px; text-align: center; }

  /* Progress steps */
  .progress { margin-top: 22px; display: none; }
  .progress.show { display: block; }
  .step-list { display: flex; flex-direction: column; gap: 8px; }
  .step { display: flex; align-items: center; gap: 12px; padding: 10px 14px;
          border-radius: 8px; background: #f1f5f9; font-size: 13px; }
  .step.running { background: #fef3c7; color: #92400e; }
  .step.done    { background: #dcfce7; color: #166534; }
  .step.fail    { background: #fee2e2; color: #991b1b; }
  .step .icon { width: 18px; height: 18px; flex-shrink: 0; display: inline-flex;
                align-items: center; justify-content: center; }
  .spinner { width: 14px; height: 14px; border: 2px solid currentColor; border-top-color: transparent;
             border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Results */
  .results { margin-top: 28px; display: none; }
  .results.show { display: block; }
  .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
                margin-bottom: 22px; }
  .score-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
                padding: 18px; text-align: center; }
  .score-num { font-size: 38px; font-weight: 700; letter-spacing: -0.03em; line-height: 1; }
  .score-num.green { color: #16a34a; }
  .score-num.amber { color: #d97706; }
  .score-num.red   { color: #dc2626; }
  .score-num.gray  { color: #94a3b8; }
  .score-lbl { font-size: 11px; color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.06em; margin-top: 6px; font-weight: 600; }

  .findings-card { background: var(--card); border: 1px solid var(--border);
                   border-radius: 12px; padding: 22px; margin-bottom: 14px; }
  .findings-card h2 { margin: 0 0 12px 0; font-size: 14px; text-transform: uppercase;
                      letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
  .finding { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px dashed #e2e8f0;
             font-size: 13px; }
  .finding:last-child { border-bottom: 0; }
  .finding .icon { font-size: 14px; flex-shrink: 0; width: 20px; }

  .download-row { margin-top: 22px; display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
  .download-btn { padding: 12px 22px; font-size: 14px; border-radius: 10px;
                  border: 1px solid #cbd5e1; background: #fff; cursor: pointer;
                  text-decoration: none; color: var(--text); font-weight: 500;
                  display: inline-flex; align-items: center; gap: 8px; transition: all .15s; }
  .download-btn:hover { background: #f1f5f9; border-color: #94a3b8; transform: translateY(-1px); }
  .download-btn.primary { background: #0f172a; color: #fff; border-color: #0f172a; }
  .download-btn.primary:hover { background: #1e293b; }

  details { margin-top: 12px; }
  summary { cursor: pointer; font-size: 13px; color: var(--muted); padding: 6px 0;
            user-select: none; }
  summary:hover { color: var(--text); }
  pre.terminal { background: #0f172a; color: #f8fafc; padding: 14px; border-radius: 8px;
                 font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12px;
                 line-height: 1.5; overflow: auto; max-height: 400px; margin: 8px 0 0 0;
                 white-space: pre-wrap; word-break: break-all; }

  .error-box { background: #fee2e2; color: #991b1b; padding: 12px 16px; border-radius: 8px;
               margin-top: 14px; font-size: 13px; }
  .small { font-size: 12px; color: var(--muted); }

  @media (max-width: 700px) {
    .input-row { flex-direction: column; }
    .input-row button { width: 100%; }
    .score-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>SEO / AEO / GEO Auditor</h1>
  <div class="tagline">Wpisz adres strony — dostaniesz pełny raport</div>
</header>

<div class="hero">
  <div class="input-row">
    <input id="url" type="text" placeholder="https://twojadomena.pl"
           autofocus autocomplete="off" />
    <button id="run-btn" onclick="run()">🔍 Sprawdź stronę</button>
  </div>
  <div class="hero-hint">
    Audyt zajmuje 30–90 sekund. Sprawdzamy: SEO, AEO, GEO, Performance, dostępność, schema.org, jakość treści.
  </div>

  <div id="progress" class="progress">
    <div class="step-list" id="step-list"></div>
  </div>

  <div id="error" class="error-box" style="display:none;"></div>
</div>

<div id="results" class="results"></div>

</div>

<script>
const $ = (id) => document.getElementById(id);
const STEPS = [
  { id: "pagespeed", name: "PageSpeed Insights (Google)", icon: "🚦" },
  { id: "audit_main", name: "Audyt główny SEO/AEO/GEO", icon: "🔍" },
  { id: "advanced", name: "Audyt zaawansowany (Performance + A11y + Content)", icon: "⚡" },
  { id: "validator", name: "Walidacja schema.org", icon: "✓" },
];

let currentJob = null;

function setStep(stepId, state, info) {
  const el = document.getElementById("step-" + stepId);
  if (!el) return;
  el.className = "step " + state;
  const step = STEPS.find(s => s.id === stepId);
  let icon = step.icon;
  if (state === "running") icon = '<span class="spinner"></span>';
  if (state === "done") icon = "✓";
  if (state === "fail") icon = "✗";
  el.querySelector(".icon").innerHTML = icon;
  if (info) el.querySelector(".info").textContent = info;
}

function showError(msg) {
  $("error").style.display = "block";
  $("error").textContent = "❌ " + msg;
}

function hideError() {
  $("error").style.display = "none";
}

function colorClass(score) {
  if (score === null || score === undefined) return "gray";
  if (score >= 90) return "green";
  if (score >= 50) return "amber";
  return "red";
}

function renderResults(data) {
  const r = data.result || {};
  const psi = r.pagespeed || {};
  const main = r.audit_main || {};
  const adv = r.advanced || {};
  const val = r.validator || {};

  // Cztery podstawowe score'y
  const cards = [
    { lbl: "Performance", val: psi.categories?.performance },
    { lbl: "Accessibility", val: psi.categories?.accessibility },
    { lbl: "Best Practices", val: psi.categories?.best_practices },
    { lbl: "SEO", val: psi.categories?.seo ?? main.score },
  ];

  let html = '<div class="score-grid">';
  cards.forEach(c => {
    const v = c.val;
    const cls = colorClass(v);
    html += `<div class="score-card">
      <div class="score-num ${cls}">${v != null ? v : "—"}</div>
      <div class="score-lbl">${c.lbl}</div>
    </div>`;
  });
  html += '</div>';

  // Lab metrics
  if (psi.lab_metrics) {
    const lab = psi.lab_metrics;
    html += `<div class="findings-card">
      <h2>📊 Real metrics (Chrome lab)</h2>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;text-align:center;">
        <div><div style="font-size:20px;font-weight:700;">${lab.LCP?.value || "—"}</div><div class="small">LCP (cel &lt;2.5s)</div></div>
        <div><div style="font-size:20px;font-weight:700;">${lab.CLS?.value || "—"}</div><div class="small">CLS (cel &lt;0.1)</div></div>
        <div><div style="font-size:20px;font-weight:700;">${lab.TBT?.value || "—"}</div><div class="small">TBT (cel &lt;200ms)</div></div>
      </div>
    </div>`;
  }

  // Top problemy
  const issues = [];
  if (psi.opportunities) {
    psi.opportunities.slice(0, 5).forEach(o => {
      const saving = [];
      if (o.savings_ms) saving.push(`-${Math.round(o.savings_ms)}ms`);
      if (o.savings_kb) saving.push(`-${o.savings_kb}KB`);
      issues.push({ icon: "⚡", text: `${o.title} ${saving.length ? "(" + saving.join(" ") + ")" : ""}` });
    });
  }
  if (psi.accessibility_issues) {
    psi.accessibility_issues.slice(0, 3).forEach(a => {
      issues.push({ icon: "♿", text: `${a.title} (${a.items_count} elementów)` });
    });
  }
  if (val.summary?.errors > 0) {
    issues.push({ icon: "❌", text: `Schema.org: ${val.summary.errors} błędów, ${val.summary.warnings} ostrzeżeń` });
  }
  if (main.fail > 0) {
    issues.push({ icon: "❌", text: `Audyt główny: ${main.fail} pozycji wymaga poprawki` });
  }

  if (issues.length) {
    html += `<div class="findings-card">
      <h2>🎯 Co poprawić (priorytet)</h2>`;
    issues.forEach(i => {
      html += `<div class="finding"><span class="icon">${i.icon}</span><span>${i.text}</span></div>`;
    });
    html += '</div>';
  } else {
    html += `<div class="findings-card">
      <h2>✅ Brak krytycznych problemów</h2>
      <div class="small">Strona spełnia wymagania techniczne. Patrz pełny raport poniżej.</div>
    </div>`;
  }

  // Download buttons
  html += '<div class="download-row">';
  if (data.report_html) {
    html += `<a class="download-btn primary" href="/download?path=${encodeURIComponent(data.report_html)}" download>📄 Pobierz pełny raport (HTML)</a>`;
  }
  if (data.report_json) {
    html += `<a class="download-btn" href="/download?path=${encodeURIComponent(data.report_json)}" download>📦 Surowe dane (JSON)</a>`;
  }
  if (data.report_html) {
    html += `<a class="download-btn" href="/view?path=${encodeURIComponent(data.report_html)}" target="_blank">👁️ Otwórz raport</a>`;
  }
  html += '</div>';

  // Pełny output (collapsible)
  html += `<details><summary>Pokaż surowy output (debug)</summary>
    <pre class="terminal">${escapeHtml(data.full_output || "")}</pre>
  </details>`;

  $("results").innerHTML = html;
  $("results").classList.add("show");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function buildSteps() {
  $("step-list").innerHTML = STEPS.map(s =>
    `<div id="step-${s.id}" class="step">
      <span class="icon">${s.icon}</span>
      <span><b>${s.name}</b> <span class="info small"></span></span>
    </div>`
  ).join("");
}

async function pollStatus(jobId) {
  while (true) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch(`/status?job=${encodeURIComponent(jobId)}`);
      const j = await r.json();
      if (j.error) { showError(j.error); break; }
      // Update steps
      Object.entries(j.steps || {}).forEach(([id, s]) => {
        setStep(id, s.state, s.info || "");
      });
      if (j.done) {
        if (j.failed) {
          showError(j.error || "Audyt zakończony z błędem.");
        }
        renderResults(j);
        return;
      }
    } catch (e) {
      console.error(e);
    }
  }
}

async function run() {
  hideError();
  $("results").classList.remove("show");
  $("results").innerHTML = "";

  let url = $("url").value.trim();
  if (!url) { showError("Wpisz adres strony."); return; }
  if (!url.match(/^https?:\/\//)) { url = "https://" + url; $("url").value = url; }

  $("run-btn").disabled = true;
  $("progress").classList.add("show");
  buildSteps();
  STEPS.forEach(s => setStep(s.id, "pending"));

  try {
    const r = await fetch("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await r.json();
    if (data.error) { showError(data.error); $("run-btn").disabled = false; return; }
    currentJob = data.job_id;
    await pollStatus(currentJob);
  } catch (e) {
    showError("Błąd komunikacji: " + e.message);
  } finally {
    $("run-btn").disabled = false;
  }
}

// Załaduj ostatni URL
window.addEventListener("DOMContentLoaded", () => {
  try {
    const last = localStorage.getItem("last_url");
    if (last) $("url").value = last;
  } catch (e) {}
  $("url").addEventListener("change", () => {
    try { localStorage.setItem("last_url", $("url").value); } catch (e) {}
  });
  $("url").addEventListener("keydown", e => { if (e.key === "Enter") run(); });
});
</script>
</body>
</html>
"""


# ─── HTML REPORT TEMPLATE ─────────────────────────────────────────────────────

REPORT_HTML_TEMPLATE = r"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Raport audytu — {url}</title>
<style>
  body { font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
         max-width: 980px; margin: 0 auto; padding: 32px; background: #f8f8f7;
         color: #0f172a; font-size: 14px; line-height: 1.55; }
  header { border-bottom: 2px solid #0f172a; padding-bottom: 16px; margin-bottom: 22px; }
  h1 { margin: 0 0 4px 0; font-size: 26px; }
  .meta { color: #64748b; font-size: 13px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em;
       color: #64748b; margin: 26px 0 10px 0; font-weight: 600; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
          padding: 18px; margin-bottom: 14px; }
  .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
  .score { text-align: center; padding: 14px; background: #f8fafc; border-radius: 8px; }
  .score .num { font-size: 32px; font-weight: 700; }
  .score .num.green { color: #16a34a; } .score .num.amber { color: #d97706; }
  .score .num.red { color: #dc2626; } .score .num.gray { color: #94a3b8; }
  .score .lbl { font-size: 11px; color: #64748b; text-transform: uppercase;
                letter-spacing: 0.05em; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e2e8f0;
           font-size: 13px; }
  th { background: #f8fafc; font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: 0.04em; }
  ul { padding-left: 20px; margin: 8px 0; }
  li { margin: 3px 0; }
  pre { background: #f1f5f9; padding: 10px 14px; border-radius: 6px; font-size: 12px;
        overflow: auto; }
  footer { text-align: center; color: #94a3b8; font-size: 11px; margin-top: 32px;
           padding-top: 16px; border-top: 1px solid #e2e8f0; }
  @media print {
    body { background: white; padding: 16px; }
    .card { break-inside: avoid; }
  }
</style>
</head>
<body>

<header>
  <h1>Raport audytu SEO / AEO / GEO</h1>
  <div class="meta">{url} · {timestamp}</div>
</header>

<div class="card">
  <h2>Wyniki ogólne</h2>
  <div class="grid4">{score_cards}</div>
</div>

{lab_section}
{audit_main_section}
{advanced_section}
{validator_section}
{recommendations_section}

<footer>Wygenerowane przez seo-aeo-geo-auditor v1.0 · {timestamp}</footer>

</body>
</html>"""


def color_class(score):
    if score is None:
        return "gray"
    if score >= 90:
        return "green"
    if score >= 50:
        return "amber"
    return "red"


def build_html_report(url: str, result: dict) -> str:
    psi = result.get("pagespeed", {})
    main = result.get("audit_main", {})
    adv = result.get("advanced", {})
    val = result.get("validator", {})

    cats = psi.get("categories") or {}
    main_score = main.get("score")
    cards_data = [
        ("Performance", cats.get("performance")),
        ("Accessibility", cats.get("accessibility")),
        ("Best Practices", cats.get("best_practices")),
        ("SEO/AEO/GEO", cats.get("seo") if cats.get("seo") else main_score),
    ]
    score_cards = "".join(
        f'<div class="score"><div class="num {color_class(v)}">{v if v is not None else "—"}</div>'
        f'<div class="lbl">{lbl}</div></div>'
        for lbl, v in cards_data
    )

    # Lab metrics
    lab_section = ""
    if psi.get("lab_metrics"):
        lab = psi["lab_metrics"]
        lab_section = f"""<div class="card"><h2>Metryki LAB (Chrome lab)</h2>
<table><tr><th>Metryka</th><th>Wartość</th><th>Cel</th></tr>
<tr><td>LCP — Largest Contentful Paint</td><td>{lab.get("LCP", {}).get("value", "—")}</td><td>&lt;2.5s</td></tr>
<tr><td>FCP — First Contentful Paint</td><td>{lab.get("FCP", {}).get("value", "—")}</td><td>&lt;1.8s</td></tr>
<tr><td>CLS — Cumulative Layout Shift</td><td>{lab.get("CLS", {}).get("value", "—")}</td><td>&lt;0.1</td></tr>
<tr><td>TBT — Total Blocking Time</td><td>{lab.get("TBT", {}).get("value", "—")}</td><td>&lt;200ms</td></tr>
<tr><td>SI — Speed Index</td><td>{lab.get("SI", {}).get("value", "—")}</td><td>&lt;3.4s</td></tr>
</table></div>"""

    # Audit main
    audit_main_section = ""
    if main.get("lines"):
        lines = main["lines"][:80]
        items = "".join(f"<li>{escape_html(l.strip())}</li>" for l in lines if l.strip() and not l.startswith("─"))
        audit_main_section = f"""<div class="card"><h2>Audyt SEO / AEO / GEO — szczegóły</h2>
<p>Score: <b>{main.get("score", 0)}%</b> — {main.get("ok", 0)} ✅ · {main.get("fail", 0)} ❌ · {main.get("warn", 0)} ⚠️</p>
<ul>{items}</ul></div>"""

    # Advanced
    advanced_section = ""
    if adv.get("modules"):
        rows = ""
        for m, d in adv["modules"].items():
            rows += f'<tr><td><b>{m}</b></td><td>{d.get("score", 0)}/100</td>'
            findings_list = "".join(f"<li>{escape_html(x)}</li>" for x in (d.get("findings") or [])[:10])
            rows += f'<td><ul>{findings_list}</ul></td></tr>'
        advanced_section = f"""<div class="card"><h2>Performance + Accessibility + Content quality</h2>
<table><tr><th>Moduł</th><th>Score</th><th>Findings</th></tr>{rows}</table></div>"""

    # Validator
    validator_section = ""
    if val.get("summary"):
        s = val["summary"]
        types_seen = ", ".join(sorted(set(t for p in val.get("pages", []) for t in p.get("types", []))))
        validator_section = f"""<div class="card"><h2>Walidacja schema.org</h2>
<p>Stron: <b>{s.get("pages", 0)}</b> · Błędy: <b>{s.get("errors", 0)}</b> · Ostrzeżenia: <b>{s.get("warnings", 0)}</b></p>
<p><b>Typy znalezione:</b> {types_seen}</p></div>"""

    # Recommendations
    recs = []
    if psi.get("opportunities"):
        for o in psi["opportunities"][:8]:
            saving = []
            if o.get("savings_ms"):
                saving.append(f"-{int(o['savings_ms'])}ms")
            if o.get("savings_kb"):
                saving.append(f"-{o['savings_kb']}KB")
            recs.append(f"{o.get('title', '')} {('(' + ' '.join(saving) + ')') if saving else ''}")
    if psi.get("accessibility_issues"):
        for a in psi["accessibility_issues"][:5]:
            recs.append(f"{a.get('title', '')} ({a.get('items_count', 0)} elementów)")
    recommendations_section = ""
    if recs:
        items = "".join(f"<li>{escape_html(r)}</li>" for r in recs)
        recommendations_section = f"""<div class="card"><h2>Rekomendacje (priorytet)</h2>
<ol>{items}</ol></div>"""

    # Używamy .replace() zamiast .format() — bo CSS klamer { } kolizjuje z placeholderami .format()
    replacements = {
        "{url}": escape_html(url),
        "{timestamp}": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "{score_cards}": score_cards,
        "{lab_section}": lab_section,
        "{audit_main_section}": audit_main_section,
        "{advanced_section}": advanced_section,
        "{validator_section}": validator_section,
        "{recommendations_section}": recommendations_section,
    }
    out = REPORT_HTML_TEMPLATE
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


def escape_html(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ─── ORCHESTRATOR — uruchom wszystkie audyty równolegle ───────────────────────

def run_subprocess(cmd: list[str], timeout: int = 120) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                               encoding="utf-8", errors="replace")
        return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr,
                "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timeout ({timeout}s)", "returncode": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}


def run_audit_job(job_id: str, url: str):
    """Uruchamia 4 audyty sekwencyjnie i raportuje progress."""

    def update(step_id: str, state: str, info: str = ""):
        with JOB_LOCK:
            JOBS[job_id]["steps"][step_id] = {"state": state, "info": info}

    full_output = []
    result = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = (urllib.parse.urlparse(url).hostname or "site").replace(".", "-")

    def short_err(text: str, fallback: str = "brak szczegółów") -> str:
        if not text:
            return fallback
        # Wyciągnij ostatnią sensowną linię stderr (najczęściej tam jest exception)
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line and not line.startswith(("File ", "  ", "Traceback")):
                return line[:300]
        return text.strip()[:300] or fallback

    # 1. PageSpeed (najdłuższy — leci pierwszy)
    update("pagespeed", "running", "30-60s, Google odpala headless Chrome…")
    psi_json = REPORTS_DIR / f"{slug}_{timestamp}_psi.json"
    cmd = [PYTHON, str(HERE / "pagespeed.py"), "--url", url,
           "--json", str(psi_json), "--quiet"]
    api_key = os.environ.get("PSI_API_KEY", "")
    if api_key:
        cmd.extend(["--api-key", api_key])
    r = run_subprocess(cmd, timeout=120)
    full_output.append("=== PageSpeed Insights ===\nCMD: " + " ".join(cmd) +
                        "\n--- STDOUT ---\n" + r["stdout"] +
                        "\n--- STDERR ---\n" + r["stderr"])
    if r["ok"] and psi_json.exists():
        try:
            result["pagespeed"] = json.loads(psi_json.read_text(encoding="utf-8"))
            cats = result["pagespeed"].get("categories", {})
            update("pagespeed", "done",
                   f"Perf {cats.get('performance', '?')} · A11y {cats.get('accessibility', '?')} · BP {cats.get('best_practices', '?')} · SEO {cats.get('seo', '?')}")
        except Exception as e:
            update("pagespeed", "fail", f"Parse error: {e}")
    else:
        update("pagespeed", "fail", short_err(r["stderr"] or r["stdout"]))

    # 2. Audyt główny (URL mode)
    update("audit_main", "running", "Skanuję 15 stron z sitemap…")
    main_json = REPORTS_DIR / f"{slug}_{timestamp}_main.json"
    cmd = [PYTHON, str(HERE / "auditor.py"), "--url", url, "--pages", "15",
           "--json", str(main_json)]
    r = run_subprocess(cmd, timeout=120)
    full_output.append("\n=== Audyt główny ===\nCMD: " + " ".join(cmd) +
                        "\n--- STDOUT ---\n" + r["stdout"] +
                        "\n--- STDERR ---\n" + r["stderr"])
    if main_json.exists():
        try:
            result["audit_main"] = json.loads(main_json.read_text(encoding="utf-8"))
            update("audit_main", "done", f"Score {result['audit_main'].get('score', 0)}%")
        except Exception as e:
            update("audit_main", "fail", f"Parse error: {e}")
    else:
        update("audit_main", "fail", short_err(r["stderr"] or r["stdout"]))

    # 3. Advanced (URL mode)
    update("advanced", "running", "Performance + WCAG + Content quality…")
    adv_json = REPORTS_DIR / f"{slug}_{timestamp}_adv.json"
    cmd = [PYTHON, str(HERE / "auditor_advanced.py"), "--url", url, "--pages", "10",
           "--json", str(adv_json)]
    r = run_subprocess(cmd, timeout=120)
    full_output.append("\n=== Audyt zaawansowany ===\nCMD: " + " ".join(cmd) +
                        "\n--- STDOUT ---\n" + r["stdout"] +
                        "\n--- STDERR ---\n" + r["stderr"])
    if adv_json.exists():
        try:
            result["advanced"] = json.loads(adv_json.read_text(encoding="utf-8"))
            update("advanced", "done", f"Avg score {result['advanced'].get('avg_score', 0)}/100")
        except Exception as e:
            update("advanced", "fail", f"Parse error: {e}")
    else:
        update("advanced", "fail", short_err(r["stderr"] or r["stdout"]))

    # 4. Validator (URL mode — 1 strona)
    update("validator", "running", "Walidacja schema.org…")
    val_json = REPORTS_DIR / f"{slug}_{timestamp}_val.json"
    cmd = [PYTHON, str(HERE / "validator.py"), "--url", url, "--json", str(val_json)]
    r = run_subprocess(cmd, timeout=60)
    full_output.append("\n=== Validator schema.org ===\nCMD: " + " ".join(cmd) +
                        "\n--- STDOUT ---\n" + r["stdout"] +
                        "\n--- STDERR ---\n" + r["stderr"])
    if val_json.exists():
        try:
            result["validator"] = json.loads(val_json.read_text(encoding="utf-8"))
            s = result["validator"].get("summary", {})
            update("validator", "done",
                   f"{s.get('errors', 0)} błędów · {s.get('warnings', 0)} ostrzeżeń")
        except Exception as e:
            update("validator", "fail", f"Parse error: {e}")
    else:
        update("validator", "fail", short_err(r["stderr"] or r["stdout"]))

    # Generuj końcowy raport HTML
    report_html_path = REPORTS_DIR / f"{slug}_{timestamp}_report.html"
    report_json_path = REPORTS_DIR / f"{slug}_{timestamp}_report.json"
    try:
        html = build_html_report(url, result)
        report_html_path.write_text(html, encoding="utf-8")
    except Exception as e:
        full_output.append(f"\nReport HTML error: {e}")

    try:
        report_json_path.write_text(
            json.dumps({"url": url, "timestamp": timestamp, "result": result},
                        indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass

    with JOB_LOCK:
        JOBS[job_id].update({
            "done": True,
            "_finished_at": time.time(),
            "result": result,
            "full_output": "\n".join(full_output),
            "report_html": str(report_html_path) if report_html_path.exists() else None,
            "report_json": str(report_json_path) if report_json_path.exists() else None,
        })


# ─── HTTP HANDLER ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # cisza w logach

    def _send(self, code: int, body: bytes, content_type: str = "text/html; charset=utf-8",
              extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"))
            return
        if parsed.path == "/status":
            qs = urllib.parse.parse_qs(parsed.query)
            job_id = qs.get("job", [""])[0]
            with JOB_LOCK:
                job = JOBS.get(job_id, {}).copy()
            if not job:
                self._send_json({"error": "Job not found"}, 404)
                return
            self._send_json(job)
            return
        if parsed.path in ("/download", "/view"):
            qs = urllib.parse.parse_qs(parsed.query)
            raw_path = qs.get("path", [""])[0]
            if not raw_path:
                self._send(400, b"Missing path")
                return
            # Reject NUL/control bytes outright (Windows + traversal tricks).
            if "\x00" in raw_path:
                self._send(403, b"Forbidden")
                return
            try:
                path = Path(raw_path).resolve(strict=False)
                reports_root = REPORTS_DIR.resolve()
                # Must be a descendant of REPORTS_DIR — narrower than HERE.
                path.relative_to(reports_root)
            except (ValueError, RuntimeError, OSError):
                self._send(403, b"Forbidden")
                return
            if not path.is_file():
                self._send(404, b"Not found")
                return
            # Whitelist served file types — never serve .py / arbitrary blobs.
            allowed = {".html": "text/html; charset=utf-8",
                       ".json": "application/json; charset=utf-8",
                       ".md":   "text/markdown; charset=utf-8",
                       ".txt":  "text/plain; charset=utf-8",
                       ".csv":  "text/csv; charset=utf-8"}
            ct = allowed.get(path.suffix.lower())
            if ct is None:
                self._send(403, b"Forbidden")
                return
            extra = None
            if parsed.path == "/download":
                # Sanitize filename in Content-Disposition (strip quote/CR/LF).
                safe_name = path.name.replace('"', "").replace("\r", "").replace("\n", "")
                extra = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
            try:
                data = path.read_bytes()
            except OSError:
                self._send(500, b"Read error")
                return
            self._send(200, data, ct, extra)
            return
        self._send(404, b"Not Found")

    def do_POST(self):
        if self.path != "/start":
            self._send(404, b"Not Found")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json({"error": f"Bad JSON: {e}"}, 400)
            return

        url = body.get("url", "").strip()
        if not url:
            self._send_json({"error": "Brak URL"}, 400)
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # Cleanup expired/excess jobs before allocating a new one.
        _cleanup_jobs()

        now_ts = time.time()
        job_id = f"job_{int(now_ts * 1000)}"
        with JOB_LOCK:
            JOBS[job_id] = {
                "url": url,
                "started": datetime.now().isoformat(),
                "_started_at": now_ts,
                "_finished_at": None,
                "done": False,
                "steps": {
                    "pagespeed": {"state": "pending"},
                    "audit_main": {"state": "pending"},
                    "advanced": {"state": "pending"},
                    "validator": {"state": "pending"},
                },
            }

        threading.Thread(target=run_audit_job, args=(job_id, url), daemon=True).start()
        self._send_json({"job_id": job_id, "url": url})


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="SEO/AEO/GEO Auditor — local web GUI.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="Otwórz w przeglądarce automatycznie")
    args = ap.parse_args()

    server = HTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"

    print("=" * 60)
    print("  SEO/AEO/GEO Auditor — local GUI")
    print("=" * 60)
    print(f"  Otwórz:  {url}")
    print(f"  Reports: {REPORTS_DIR}")
    psi = os.environ.get("PSI_API_KEY", "")
    print(f"  PSI:     {'✓ klucz w env' if psi else '✗ brak PSI_API_KEY (PageSpeed nie zadziała)'}")
    print(f"  Stop:    Ctrl+C")
    print("=" * 60)

    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZamknięte.")
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
