#!/usr/bin/env python3
"""
monitor.py — continuous monitoring + diff reporter dla SEO/AEO/GEO audytów.

Workflow:
  1. Uruchamia auditor.py + auditor_advanced.py + validator.py na celu (folder/URL)
  2. Łączy wszystkie wyniki w jednym snapshot.json
  3. Zapisuje do history/{YYYY-MM-DD-HHMM}_{slug}.json
  4. Porównuje z poprzednim snapshotem tego samego celu — generuje diff
  5. Flag regresji (score spadł, znikły schematy, cofnięto fixy)
  6. Opcjonalnie: wysłanie alertu emailem (SMTP) gdy regression

Użycie:
    python monitor.py --folder C:/output/zdrowie-fit --site zdrowie-fit
    python monitor.py --url https://zdrowie.fit --site zdrowie-fit
    python monitor.py --folder ./output/zdrowie-fit --site zdrowie-fit --alert-email me@example.com
    python monitor.py --history          # tylko raport diff bez nowego audytu
    python monitor.py --schedule         # zarejestruj w Windows Task Scheduler (pokaże komendę)
"""
from __future__ import annotations

import argparse
import json
import re
import smtplib
import subprocess
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY_DIR = HERE / "history"


# ─── ZBIERANIE SNAPSHOTU ──────────────────────────────────────────────────────

def run_auditor(target: str, mode: str, extras: str = "") -> dict | None:
    """Uruchom auditor.py + zwróć JSON. Lub None przy błędzie."""
    out_json = HERE / "_tmp_main.json"
    cmd = [
        sys.executable, str(HERE / "auditor.py"),
        f"--{mode}", target,
        "--json", str(out_json),
    ]
    if mode == "url":
        cmd += ["--pages", "10"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if out_json.exists():
            return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ auditor.py nieudany: {e}")
    return None


def run_advanced(target: str, mode: str) -> dict | None:
    out_json = HERE / "_tmp_adv.json"
    cmd = [
        sys.executable, str(HERE / "auditor_advanced.py"),
        f"--{mode}", target,
        "--json", str(out_json),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        if out_json.exists():
            return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ auditor_advanced.py nieudany: {e}")
    return None


def run_validator(target: str, mode: str) -> dict | None:
    out_json = HERE / "_tmp_val.json"
    cmd = [
        sys.executable, str(HERE / "validator.py"),
        f"--{mode}", target,
        "--json", str(out_json),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        if out_json.exists():
            return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ validator.py nieudany: {e}")
    return None


def collect_snapshot(target: str, mode: str, site_slug: str) -> dict:
    print(f"\n📸 Robię snapshot: {site_slug} ({mode}: {target})")
    snapshot = {
        "site_slug": site_slug,
        "mode": mode,
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "main": run_auditor(target, mode),
        "advanced": run_advanced(target, mode),
        "validator": run_validator(target, mode),
    }

    # Składowy score
    scores = []
    if snapshot["main"] and "score" in snapshot["main"]:
        scores.append(snapshot["main"]["score"])
    if snapshot["advanced"] and "avg_score" in snapshot["advanced"]:
        scores.append(snapshot["advanced"]["avg_score"])
    if snapshot["validator"] and "summary" in snapshot["validator"]:
        s = snapshot["validator"]["summary"]
        # Score = 100 - errors * 5 - warnings (cap 0)
        v_score = max(0, 100 - s.get("errors", 0) * 5 - s.get("warnings", 0))
        scores.append(v_score)

    snapshot["composite_score"] = int(sum(scores) / len(scores)) if scores else 0
    snapshot["score_breakdown"] = {
        "main": snapshot["main"].get("score") if snapshot["main"] else None,
        "advanced": snapshot["advanced"].get("avg_score") if snapshot["advanced"] else None,
        "validator": v_score if snapshot["validator"] else None,
    }
    return snapshot


# ─── HISTORIA ─────────────────────────────────────────────────────────────────

def save_snapshot(snapshot: dict) -> Path:
    HISTORY_DIR.mkdir(exist_ok=True)
    ts = datetime.fromisoformat(snapshot["timestamp"].replace("Z", "+00:00"))
    fname = f"{ts.strftime('%Y-%m-%d-%H%M')}_{snapshot['site_slug']}.json"
    path = HISTORY_DIR / fname
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"💾 Zapisano: {path.relative_to(HERE)}")
    return path


def list_history(site_slug: str | None = None) -> list[Path]:
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("*.json"))
    if site_slug:
        files = [f for f in files if f.stem.endswith(f"_{site_slug}")]
    return files


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ─── DIFF REPORTER ────────────────────────────────────────────────────────────

def diff_snapshots(old: dict, new: dict) -> dict:
    """Porównaj dwa snapshoty — zwróć strukturę z deltami."""
    delta = {
        "site_slug": new.get("site_slug"),
        "from": old.get("timestamp"),
        "to": new.get("timestamp"),
        "score_delta": (new.get("composite_score", 0) - old.get("composite_score", 0)),
        "old_score": old.get("composite_score"),
        "new_score": new.get("composite_score"),
        "regressions": [],   # lista stringów
        "improvements": [],  # lista stringów
    }

    # Scores per warstwa
    old_b = old.get("score_breakdown", {}) or {}
    new_b = new.get("score_breakdown", {}) or {}
    for layer in ("main", "advanced", "validator"):
        ov = old_b.get(layer)
        nv = new_b.get(layer)
        if ov is None or nv is None:
            continue
        d = nv - ov
        if d <= -5:
            delta["regressions"].append(f"📉 {layer}: {ov} → {nv} ({d:+d})")
        elif d >= 5:
            delta["improvements"].append(f"📈 {layer}: {ov} → {nv} ({d:+d})")

    # Findings — wykryj zniknięte/dodane ✅ ❌
    def collect_findings(snap: dict) -> tuple[set[str], set[str], set[str]]:
        oks: set[str] = set()
        fails: set[str] = set()
        warns: set[str] = set()
        if snap.get("main") and "lines" in snap["main"]:
            for ln in snap["main"]["lines"]:
                ln = ln.strip()
                if "✅" in ln:
                    oks.add(ln)
                elif "❌" in ln:
                    fails.add(ln)
                elif "⚠️" in ln:
                    warns.add(ln)
        return oks, fails, warns

    o_ok, o_fail, o_warn = collect_findings(old)
    n_ok, n_fail, n_warn = collect_findings(new)

    new_failures = n_fail - o_fail
    fixed_failures = o_fail - n_fail
    for f in list(new_failures)[:10]:
        delta["regressions"].append(f"🆕 FAIL: {f[:120]}")
    for f in list(fixed_failures)[:10]:
        delta["improvements"].append(f"✅ NAPRAWIONE: {f[:120]}")

    # Validator-specific: czy ubyły schematy
    o_val = (old.get("validator") or {}).get("pages") or []
    n_val = (new.get("validator") or {}).get("pages") or []
    o_types = set(t for p in o_val for t in p.get("types", []))
    n_types = set(t for p in n_val for t in p.get("types", []))
    lost_types = o_types - n_types
    new_types = n_types - o_types
    for t in lost_types:
        delta["regressions"].append(f"⚠️ ZNIKNĄŁ schema: {t}")
    for t in new_types:
        delta["improvements"].append(f"➕ DODANO schema: {t}")

    delta["regression_count"] = len(delta["regressions"])
    delta["improvement_count"] = len(delta["improvements"])
    delta["status"] = (
        "REGRESSION" if delta["regression_count"] > delta["improvement_count"]
        else "IMPROVEMENT" if delta["improvement_count"] > 0
        else "STABLE"
    )
    return delta


def render_diff_report(delta: dict) -> str:
    lines = ["=" * 60]
    lines.append(f"  DIFF REPORT — {delta['site_slug']}")
    lines.append("=" * 60)
    lines.append(f"  Od:    {delta['from']}")
    lines.append(f"  Do:    {delta['to']}")
    lines.append(f"  Score: {delta['old_score']} → {delta['new_score']} ({delta['score_delta']:+d})")
    lines.append(f"  Status: {delta['status']}")
    lines.append("")
    if delta["regressions"]:
        lines.append(f"❌ REGRESJE ({delta['regression_count']}):")
        for r in delta["regressions"]:
            lines.append(f"  {r}")
        lines.append("")
    if delta["improvements"]:
        lines.append(f"✅ POPRAWY ({delta['improvement_count']}):")
        for i in delta["improvements"]:
            lines.append(f"  {i}")
        lines.append("")
    if not delta["regressions"] and not delta["improvements"]:
        lines.append("➖ Bez zmian.")
    return "\n".join(lines)


# ─── EMAIL ALERT ──────────────────────────────────────────────────────────────

def send_email_alert(to_email: str, delta: dict, smtp_config: dict) -> bool:
    """Wysłanie alertu SMTP. smtp_config = {host, port, user, password, from}"""
    body = render_diff_report(delta)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[SEO Monitor] {delta['status']} — {delta['site_slug']} ({delta['score_delta']:+d}pp)"
    msg["From"] = smtp_config.get("from", smtp_config.get("user"))
    msg["To"] = to_email
    try:
        server = smtplib.SMTP_SSL(smtp_config["host"], smtp_config.get("port", 465))
        server.login(smtp_config["user"], smtp_config["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False


# ─── SCHEDULE (Windows Task Scheduler) ────────────────────────────────────────

def show_schedule_command(target: str, mode: str, site_slug: str) -> str:
    """Pokaż komendę do zarejestrowania w Task Scheduler."""
    py = sys.executable
    script = HERE / "monitor.py"
    cmd = f'"{py}" "{script}" --{mode} "{target}" --site {site_slug}'
    schtasks = (
        f'schtasks /Create /SC DAILY /TN "SEO_Monitor_{site_slug}" '
        f'/TR \'{cmd}\' /ST 06:00 /F'
    )
    return schtasks


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Monitor SEO/AEO/GEO — historia + diff + alert",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python monitor.py --folder C:/output/zdrowie-fit --site zdrowie-fit\n"
            "  python monitor.py --url https://zdrowie.fit --site zdrowie-fit\n"
            "  python monitor.py --history --site zdrowie-fit\n"
            "  python monitor.py --schedule --folder C:/output/zdrowie-fit --site zdrowie-fit\n"
        ),
    )
    ap.add_argument("--folder", help="Folder z plikami HTML")
    ap.add_argument("--url", help="URL strony live")
    ap.add_argument("--site", help="Slug strony (np. zdrowie-fit) — używany w nazwach plików")
    ap.add_argument("--history", action="store_true", help="Tylko pokaż historię + diff (bez nowego audytu)")
    ap.add_argument("--schedule", action="store_true", help="Pokaż komendę do Windows Task Scheduler")
    ap.add_argument("--alert-email", help="Email do alertu przy regresji")
    ap.add_argument("--smtp-config", help="Plik JSON z konfiguracją SMTP {host, port, user, password, from}")
    ap.add_argument("--diff-only", action="store_true", help="Tylko diff vs poprzedni snapshot, bez nowego")
    args = ap.parse_args()

    # SCHEDULE
    if args.schedule:
        if not args.folder and not args.url:
            print("❌ --schedule wymaga --folder lub --url + --site")
            return 2
        if not args.site:
            print("❌ --schedule wymaga --site")
            return 2
        target = args.folder or args.url
        mode = "folder" if args.folder else "url"
        cmd = show_schedule_command(target, mode, args.site)
        print("📅 Komenda do zarejestrowania w Windows Task Scheduler:")
        print()
        print(cmd)
        print()
        print("Wykonaj ją w PowerShell jako administrator. Audyt będzie się uruchamiał codziennie o 06:00.")
        return 0

    # HISTORY
    if args.history:
        files = list_history(args.site)
        if not files:
            print(f"📂 Brak historii{(' dla ' + args.site) if args.site else ''}.")
            return 0
        print(f"📂 Historia ({len(files)} snapshotów):")
        prev = None
        for f in files:
            snap = load_snapshot(f)
            score = snap.get("composite_score", "?")
            ts = snap["timestamp"][:16].replace("T", " ")
            print(f"  {ts}  {snap['site_slug']:<20}  {score}/100")
            prev = snap
        if len(files) >= 2:
            old = load_snapshot(files[-2])
            new = load_snapshot(files[-1])
            if old.get("site_slug") == new.get("site_slug"):
                delta = diff_snapshots(old, new)
                print()
                print(render_diff_report(delta))
        return 0

    # NORMAL: nowy snapshot
    if not args.folder and not args.url:
        print("❌ Podaj --folder lub --url")
        return 2
    if not args.site:
        print("❌ Podaj --site (slug)")
        return 2

    target = args.folder or args.url
    mode = "folder" if args.folder else "url"

    if args.diff_only:
        files = list_history(args.site)
        if len(files) < 2:
            print("❌ Trzeba mieć ≥2 snapshoty w historii dla --diff-only")
            return 1
        old = load_snapshot(files[-2])
        new = load_snapshot(files[-1])
        delta = diff_snapshots(old, new)
        print(render_diff_report(delta))
        return 0

    snapshot = collect_snapshot(target, mode, args.site)
    save_snapshot(snapshot)

    print(f"\n📊 Composite score: {snapshot['composite_score']}/100")
    print(f"   Breakdown: {snapshot['score_breakdown']}")

    # Diff vs poprzedni
    files = list_history(args.site)
    if len(files) >= 2:
        old = load_snapshot(files[-2])
        delta = diff_snapshots(old, snapshot)
        print()
        print(render_diff_report(delta))

        # Alert email
        if args.alert_email and delta["status"] == "REGRESSION" and args.smtp_config:
            try:
                cfg = json.loads(Path(args.smtp_config).read_text(encoding="utf-8"))
                if send_email_alert(args.alert_email, delta, cfg):
                    print(f"📧 Alert wysłany na {args.alert_email}")
            except Exception as e:
                print(f"⚠️ Email config error: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
