#!/usr/bin/env python3
"""
aeo_probe.py — AEO Active Probe: real-test cytowalności w LLM-ach.

To jest cecha która oddziela nas od OSS-konkurencji i równa nas z
hostowanym SaaS (HubSpot AEO, AIclicks, SE Ranking AEO Tool).

Jak działa:
  1. Pyta wybrane LLMy (OpenAI, Anthropic, Perplexity) zestawem
     generic queries związanych z tematyką strony.
  2. Mierzy:
     - Czy domena/marka jest CYTOWANA w odpowiedzi
     - Pozycja cytatu (1-szy, 2-gi, ostatni)
     - Sentiment cytatu (pozytywny/neutralny/negatywny)
     - Czy URL pojawia się jako klikalny link
  3. Generuje raport: citation frequency per LLM × per query
  4. Wskazuje top 5 queries gdzie domena CIĘ NIE cytuje (content gap)

Koszt: ~$0.10/audyt (3 modele × 10 queries × tanie modele).

Wymaga (opcjonalne — działa z dowolnym podzbiorem):
  - OPENAI_API_KEY      → testuje gpt-4o-mini ($0.15/1M tokens)
  - ANTHROPIC_API_KEY   → testuje claude-haiku-4.5 (~$1/1M)
  - PERPLEXITY_API_KEY  → testuje sonar-small ($0.20/1M)

Użycie:
    python aeo_probe.py --domain zdrowie.fit --topic "zdrowie holistyczne"
    python aeo_probe.py --domain zdrowie.fit --queries-file queries.txt
    python aeo_probe.py --domain zdrowie.fit --topic "..." --json probe.json --md probe.md
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
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; SEO-AEO-GEO-Probe/1.0)"

# ─── KONFIGURACJA LLM PROVIDERÓW ──────────────────────────────────────────────

# OpenAI Chat Completions
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"  # tani, kompetentny

# Anthropic Messages
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Perplexity (web search wbudowany, ale wymaga $50 minimum doładowania)
PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

# Google Gemini — DARMOWY tier 1500 req/day, ten sam klucz co PSI!
# Wystarczy włączyć "Generative Language API" w tym samym projekcie Cloud
# Próbujemy 4 modele po kolei — pierwszy który zadziała wygrywa
GEMINI_MODELS_FALLBACK = [
    "gemini-2.5-flash",        # najnowszy, generalnie dostępny
    "gemini-2.0-flash",        # stabilny, wszystkie konta
    "gemini-1.5-flash-002",    # legacy stable
    "gemini-1.5-flash",        # ostatnia szansa
]
GEMINI_MODEL = "gemini-2.0-flash"  # default raportowany w wynikach
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# DeepSeek — najtańszy ($0.14/1M input), OpenAI-compatible API
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# xAI Grok — szybki, OpenAI-compatible
XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-4-1-fast-non-reasoning"

# Domyślne queries — używane jeśli user nie poda topic-u
GENERIC_QUERY_TEMPLATES = [
    "co to jest {topic}",
    "najlepsze {topic} 2026",
    "jak zacząć z {topic}",
    "{topic} dla początkujących",
    "{topic} - poradnik",
    "porównanie {topic}",
    "najczęstsze błędy w {topic}",
    "{topic} vs alternatywy",
    "skuteczne metody {topic}",
    "ekspert {topic} polska",
]


# ─── DATA STRUCTURES ──────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    provider: str           # "openai" | "anthropic" | "perplexity"
    model: str
    query: str
    response_text: str
    cited: bool             # czy domena pojawia się w odpowiedzi
    citation_count: int     # ile razy domena wymieniona
    citation_position: int | None  # pozycja pierwszego cytatu (1=najbliżej początku)
    has_url: bool           # czy odpowiedź zawiera klikalny URL z domeną
    sentiment: str          # "positive" | "neutral" | "negative" | "n/a"
    error: str = ""


# ─── DETEKCJA CYTOWANIA ──────────────────────────────────────────────────────

def analyze_citation(response_text: str, domain: str, brand: str | None = None) -> dict:
    """Analizuj odpowiedź LLM pod kątem cytowania domeny/marki.
    Deduplikuje pokrywające się matche (domain vs brand mogą być identyczne po lower)."""
    domain_clean = domain.replace("https://", "").replace("http://", "").rstrip("/")
    if domain_clean.startswith("www."):
        domain_clean = domain_clean[4:]
    domain_lc = domain_clean.lower()

    text_lc = response_text.lower()

    # Zbierz unikalne pozycje matchu (range start, range end)
    match_ranges: list[tuple[int, int]] = []
    for m in re.finditer(re.escape(domain_lc), text_lc):
        match_ranges.append((m.start(), m.end()))

    if brand:
        brand_lc = brand.lower()
        # Dodaj brand match TYLKO jeśli nie pokrywa się z istniejącym domain match
        if brand_lc != domain_lc:
            for m in re.finditer(re.escape(brand_lc), text_lc):
                rng = (m.start(), m.end())
                # Nie dodawaj jeśli przecina się z istniejącym
                if not any(s <= rng[0] < e or s < rng[1] <= e for s, e in match_ranges):
                    match_ranges.append(rng)

    match_ranges.sort()
    all_matches = [s for s, _ in match_ranges]
    citation_count = len(all_matches)
    cited = citation_count > 0

    # Pozycja w tekście (jako % długości tekstu)
    citation_position = None
    if all_matches:
        first_pos = all_matches[0]
        citation_position = round((first_pos / max(len(text_lc), 1)) * 100, 1)

    # URL detection — TYLKO klikalne URL-e (z protokołem). Bare mention domeny
    # liczy się jako citation, nie jako URL.
    has_url = bool(re.search(rf"https?://(?:www\.)?{re.escape(domain_lc)}", text_lc))

    # Sentiment heuristyka — szuka kluczowych słów wokół cytatu
    sentiment = "n/a"
    if cited:
        # Wyciągnij kontekst (±100 znaków od pierwszego cytatu)
        first = all_matches[0]
        ctx_start = max(0, first - 100)
        ctx_end = min(len(text_lc), first + 100)
        ctx = text_lc[ctx_start:ctx_end]

        # PL + EN keywords — sentiment heuristic dwujęzyczny
        positive_kws = [
            # PL
            "polec", "świetn", "doskonał", "wartościow", "wiarygodn",
            "rzeteln", "popularn", "uznan", "ekspert", "najlepsz",
            "godny pole", "warto", "zaufan", "poleca", "rekomenduj",
            # EN
            "recommend", "excellent", "trustworth", "reliable", "expert",
            "valuable", "best", "top-rated", "authoritative", "credible",
            "reputable", "high-quality",
        ]
        negative_kws = [
            # PL
            "nie polec", "słab", "kiepsk", "wątpliw", "nieaktualne",
            "nierzeteln", "kontrowers", "krytyk",
            # EN
            "not recommend", "poor", "unreliable", "outdated", "questionable",
            "controvers", "low-quality", "unverified", "biased",
        ]

        pos_hits = sum(1 for kw in positive_kws if kw in ctx)
        neg_hits = sum(1 for kw in negative_kws if kw in ctx)

        if pos_hits > neg_hits:
            sentiment = "positive"
        elif neg_hits > pos_hits:
            sentiment = "negative"
        else:
            sentiment = "neutral"

    return {
        "cited": cited,
        "citation_count": citation_count,
        "citation_position": citation_position,
        "has_url": has_url,
        "sentiment": sentiment,
    }


# ─── LLM PROVIDERS ────────────────────────────────────────────────────────────

def _http_post_json(url: str, headers: dict, body: dict, timeout: int = 60) -> dict:
    """POST JSON; on HTTP error, raise with status + response body for diagnostics."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Read response body so caller sees provider's error JSON, not just "HTTP 400".
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        raise urllib.error.HTTPError(
            url, e.code, f"{e.reason} — body: {err_body}",
            e.headers, None,
        ) from e


def query_openai(query: str, api_key: str, system_prompt: str = "") -> str:
    """Zapytanie do OpenAI gpt-4o-mini."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": query})
    body = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.3,
    }
    resp = _http_post_json(OPENAI_ENDPOINT, headers, body)
    return resp["choices"][0]["message"]["content"]


def query_anthropic(query: str, api_key: str) -> str:
    """Zapytanie do Anthropic Claude Haiku."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": query}],
    }
    resp = _http_post_json(ANTHROPIC_ENDPOINT, headers, body)
    return resp["content"][0]["text"]


def query_perplexity(query: str, api_key: str) -> str:
    """Zapytanie do Perplexity sonar (z web search)."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": PERPLEXITY_MODEL,
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 800,
        "temperature": 0.3,
    }
    resp = _http_post_json(PERPLEXITY_ENDPOINT, headers, body)
    return resp["choices"][0]["message"]["content"]


def query_openai_compatible(query: str, api_key: str, endpoint: str, models: list[str],
                             allow_no_temp: bool = True) -> str:
    """Generic OpenAI-compatible API caller (DeepSeek, xAI Grok, OpenAI, vLLM itp.).

    models: lista fallback — pierwszy działający wygrywa.
    allow_no_temp: jeśli model rzuci 400 z parametrem temperature, retry bez."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    last_err = None
    for model in models:
        for use_temp in (True, False) if allow_no_temp else (True,):
            body = {
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 800,
            }
            if use_temp:
                body["temperature"] = 0.3
            try:
                resp = _http_post_json(endpoint, headers, body)
                return resp["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = f"{model} (temp={use_temp}): {str(e)[:120]}"
                continue
    raise RuntimeError(f"Wszystkie modele zfailowały. Ostatni: {last_err}")


# DeepSeek fallback chain — w 2025 zmieniły się nazwy modeli
DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-v3", "deepseek-coder"]
# xAI Grok fallback — różne warianty wymagają różnych parametrów
XAI_MODELS = ["grok-4-1-fast-non-reasoning", "grok-3-mini", "grok-2-1212", "grok-beta"]


def query_deepseek(query: str, api_key: str) -> str:
    return query_openai_compatible(query, api_key, DEEPSEEK_ENDPOINT, DEEPSEEK_MODELS)


def query_xai(query: str, api_key: str) -> str:
    return query_openai_compatible(query, api_key, XAI_ENDPOINT, XAI_MODELS)


def query_gemini(query: str, api_key: str) -> str:
    """Zapytanie do Google Gemini z auto-fallback przez kilka modeli.

    Free tier (AI Studio key): 1500 req/day, 15 RPM, BEZ google_search grounding.
    Paid tier: dostępny google_search.

    Strategia:
      - Domyślnie BEZ tools (działa zawsze na free tier)
      - Z tools jeśli env GEMINI_USE_GROUNDING=1 (paid tier z billingiem)
      - Auto-fallback przez 4 modele: 2.5-flash → 2.0-flash → 1.5-flash-002 → 1.5-flash"""
    use_grounding = os.environ.get("GEMINI_USE_GROUNDING", "0") == "1"
    last_err = None
    for model in GEMINI_MODELS_FALLBACK:
        url = f"{GEMINI_ENDPOINT_TEMPLATE.format(model=model)}?key={api_key}"
        headers = {"Content-Type": "application/json"}
        # Lista wariantów body — zaczynaj od najbezpieczniejszego (bez tools)
        body_variants = [None]  # bez tools (free tier)
        if use_grounding:
            body_variants = [{"google_search": {}}, None]  # tools first, fallback bez
        for tools in body_variants:
            body = {
                "contents": [{"parts": [{"text": query}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
            }
            if tools:
                body["tools"] = [tools]
            try:
                resp = _http_post_json(url, headers, body)
                cand = resp.get("candidates", [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                for p in parts:
                    if "text" in p and p["text"]:
                        return p["text"]
                last_err = f"{model}: empty response"
            except Exception as e:
                last_err = f"{model}: {str(e)[:120]}"
                continue
    raise RuntimeError(f"Wszystkie modele Gemini zfailowały. Ostatni: {last_err}")


# ─── PROBE EXECUTOR ───────────────────────────────────────────────────────────

def probe_query(query: str, domain: str, brand: str | None,
                providers: dict[str, str]) -> list[ProbeResult]:
    """Wywołaj zapytanie do wszystkich dostępnych providerów, analizuj cytowanie."""
    results = []

    if "openai" in providers:
        try:
            text = query_openai(query, providers["openai"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="openai", model=OPENAI_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="openai", model=OPENAI_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    if "anthropic" in providers:
        try:
            text = query_anthropic(query, providers["anthropic"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="anthropic", model=ANTHROPIC_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="anthropic", model=ANTHROPIC_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    if "perplexity" in providers:
        try:
            text = query_perplexity(query, providers["perplexity"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="perplexity", model=PERPLEXITY_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="perplexity", model=PERPLEXITY_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    if "gemini" in providers:
        try:
            text = query_gemini(query, providers["gemini"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="gemini", model=GEMINI_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="gemini", model=GEMINI_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    if "deepseek" in providers:
        try:
            text = query_deepseek(query, providers["deepseek"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="deepseek", model=DEEPSEEK_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="deepseek", model=DEEPSEEK_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    if "xai" in providers:
        try:
            text = query_xai(query, providers["xai"])
            analysis = analyze_citation(text, domain, brand)
            results.append(ProbeResult(
                provider="xai", model=XAI_MODEL, query=query,
                response_text=text, **analysis,
            ))
        except Exception as e:
            results.append(ProbeResult(
                provider="xai", model=XAI_MODEL, query=query,
                response_text="", cited=False, citation_count=0,
                citation_position=None, has_url=False, sentiment="n/a",
                error=str(e)[:200],
            ))

    return results


# ─── AGREGATY ──────────────────────────────────────────────────────────────────

def aggregate_results(results: list[ProbeResult]) -> dict:
    """Zbiorcze metryki per provider + per query."""
    by_provider: dict[str, dict] = {}
    by_query: dict[str, dict] = {}

    for r in results:
        # Per provider
        if r.provider not in by_provider:
            by_provider[r.provider] = {
                "total_queries": 0, "cited_count": 0, "errors": 0,
                "avg_position": None,
                "_pos_sum": 0.0, "_pos_count": 0,  # do prawdziwej średniej
                "sentiments": {"positive": 0, "neutral": 0, "negative": 0},
            }
        p = by_provider[r.provider]
        p["total_queries"] += 1
        if r.error:
            p["errors"] += 1
        if r.cited:
            p["cited_count"] += 1
            if r.citation_position is not None:
                # Bug fix: poprzedni "rolling average" dawał błędne wyniki
                # ((a+b)/2 + c)/2 ≠ (a+b+c)/3. Teraz suma + licznik.
                p["_pos_sum"] += r.citation_position
                p["_pos_count"] += 1
            if r.sentiment in p["sentiments"]:
                p["sentiments"][r.sentiment] += 1

        # Per query
        if r.query not in by_query:
            by_query[r.query] = {"providers_cited": [], "providers_total": 0}
        q = by_query[r.query]
        q["providers_total"] += 1
        if r.cited:
            q["providers_cited"].append(r.provider)

    # Citation rate per provider + finalna średnia pozycji
    for p in by_provider.values():
        p["citation_rate"] = round(p["cited_count"] / max(p["total_queries"], 1) * 100, 1)
        if p["_pos_count"] > 0:
            p["avg_position"] = round(p["_pos_sum"] / p["_pos_count"], 1)
        # Wyczyść akumulator z exposed dict
        p.pop("_pos_sum", None)
        p.pop("_pos_count", None)

    # Top 5 queries gdzie nikt nie cytuje (content gap)
    not_cited_queries = [q for q, d in by_query.items() if not d["providers_cited"]]
    cited_in_all = [q for q, d in by_query.items()
                     if len(d["providers_cited"]) == d["providers_total"]]

    overall_cite_rate = (
        sum(1 for r in results if r.cited and not r.error) /
        max(len([r for r in results if not r.error]), 1) * 100
    )

    return {
        "total_probes": len(results),
        "successful_probes": sum(1 for r in results if not r.error),
        "errors": sum(1 for r in results if r.error),
        "overall_citation_rate": round(overall_cite_rate, 1),
        "by_provider": by_provider,
        "content_gaps": not_cited_queries[:10],  # queries gdzie nikt nas nie cytuje
        "strong_queries": cited_in_all[:10],     # queries gdzie wszyscy cytują
    }


# ─── MARKDOWN REPORT ──────────────────────────────────────────────────────────

def render_md(domain: str, topic: str, results: list[ProbeResult], agg: dict) -> str:
    lines = [f"# AEO Active Probe — {domain}", ""]
    lines.append(f"**Topic:** {topic}")
    lines.append(f"**Wygenerowane:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total probes:** {agg['total_probes']} (✅ {agg['successful_probes']} · ❌ {agg['errors']})")
    lines.append("")
    lines.append(f"## 🎯 Overall Citation Rate: **{agg['overall_citation_rate']}%**")
    lines.append("")
    lines.append("Czyli w {} z 100 zapytań do LLM-ów twoja domena/marka jest wymieniona.".format(agg['overall_citation_rate']))
    lines.append("")

    # Per provider
    lines.append("## Per LLM provider")
    lines.append("")
    lines.append("| Provider | Citation rate | Avg position (% długości) | Sentiment | Errors |")
    lines.append("|---|---|---|---|---|")
    for prov, p in agg["by_provider"].items():
        sent = p["sentiments"]
        sent_str = f"+{sent['positive']} ={sent['neutral']} -{sent['negative']}"
        pos = f"{p['avg_position']}%" if p['avg_position'] else "—"
        lines.append(f"| **{prov}** | {p['citation_rate']}% ({p['cited_count']}/{p['total_queries']}) | {pos} | {sent_str} | {p['errors']} |")
    lines.append("")

    # Content gaps
    if agg["content_gaps"]:
        lines.append("## 🔥 Content gaps — queries gdzie NIKT cię nie cytuje")
        lines.append("")
        lines.append("To są tematy w których brakuje contentu który modele uznałyby za godny cytowania:")
        lines.append("")
        for q in agg["content_gaps"]:
            lines.append(f"- `{q}`")
        lines.append("")

    # Strong queries
    if agg["strong_queries"]:
        lines.append("## ✅ Strong queries — queries gdzie WSZYSCY cię cytują")
        lines.append("")
        for q in agg["strong_queries"]:
            lines.append(f"- `{q}`")
        lines.append("")

    # Per query detale
    lines.append("## Detale per query")
    lines.append("")
    for r in results:
        if r.error:
            lines.append(f"### ❌ [{r.provider}] `{r.query[:80]}`")
            lines.append(f"Error: {r.error}")
            lines.append("")
            continue
        icon = "✅" if r.cited else "❌"
        lines.append(f"### {icon} [{r.provider}] `{r.query[:80]}`")
        if r.cited:
            lines.append(f"**Cytowań:** {r.citation_count} · **Pozycja:** {r.citation_position}% · **Sentiment:** {r.sentiment}")
        snippet = r.response_text[:300].replace("\n", " ")
        lines.append(f"> {snippet}…")
        lines.append("")

    return "\n".join(lines)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def load_keys_from_file(path: Path | str, override: bool = True) -> int:
    """Wczytaj klucze API z pliku KEY=VALUE (jak .env) do os.environ.
    Zwraca liczbę załadowanych kluczy.

    override=True  → ZAWSZE nadpisz wartość w env (priorytet pliku)
    override=False → tylko jeśli klucza jeszcze nie ma w env

    Plik: C:\\PYTHON\\token\\Api_AI.txt (lub dowolny .env-style)."""
    p = Path(path)
    if not p.exists():
        return 0
    loaded = 0
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Tylko klucze API (skip BASE_URL, MODEL, STRIPE itp.)
        if any(k in key.upper() for k in ("API_KEY", "TOKEN")) and not key.startswith("STRIPE"):
            if override or not os.environ.get(key):
                os.environ[key] = val
                loaded += 1
    return loaded


def collect_providers() -> dict[str, str]:
    """Zbierz dostępne API keys z env.

    ZAWSZE auto-load z C:\\PYTHON\\token\\Api_AI.txt jeśli istnieje
    (override=True — plik ma priorytet, żeby świeże klucze przebijały stare env)."""
    default_keys_file = Path("C:/PYTHON/token/Api_AI.txt")
    if default_keys_file.exists():
        loaded = load_keys_from_file(default_keys_file, override=True)
        if loaded:
            print(f"📂 Załadowano {loaded} kluczy z {default_keys_file}")

    out = {}
    for env_key, name in [
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("PERPLEXITY_API_KEY", "perplexity"),
        ("GEMINI_API_KEY", "gemini"),  # albo użyj PSI_API_KEY (ten sam projekt Google)
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("XAI_API_KEY", "xai"),
    ]:
        key = os.environ.get(env_key, "").strip()
        if key:
            out[name] = key
    # Fallback: użyj PSI key dla Gemini jeśli osobny GEMINI_API_KEY nie ustawiony
    if "gemini" not in out:
        psi_key = os.environ.get("PSI_API_KEY", "").strip()
        if psi_key:
            out["gemini"] = psi_key
    return out


def build_queries(topic: str, queries_file: Path | None) -> list[str]:
    if queries_file and queries_file.exists():
        return [line.strip() for line in queries_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    return [t.format(topic=topic) for t in GENERIC_QUERY_TEMPLATES]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AEO Active Probe — real-test cytowalności w LLM-ach.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Wymaga przynajmniej JEDNEGO klucza API w env:\n"
            "  $env:OPENAI_API_KEY = 'sk-...'\n"
            "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
            "  $env:PERPLEXITY_API_KEY = 'pplx-...'\n\n"
            "Przykłady:\n"
            "  python aeo_probe.py --domain zdrowie.fit --topic 'zdrowie holistyczne' --md probe.md\n"
            "  python aeo_probe.py --domain marekporycki.pl --brand 'Marek Porycki' --topic 'psychologia'\n"
            "  python aeo_probe.py --domain zdrowie.fit --queries-file my_queries.txt\n"
        ),
    )
    ap.add_argument("--domain", required=True, help="Domena (np. zdrowie.fit)")
    ap.add_argument("--brand", help="Nazwa marki (alternatywa do detekcji, np. 'Zdrowie.fit')")
    ap.add_argument("--topic", help="Temat strony (do generowania queries)")
    ap.add_argument("--queries-file", help="Plik z własnymi queries (1 per linia)")
    ap.add_argument("--md", help="Zapisz raport jako Markdown")
    ap.add_argument("--json", help="Zapisz wynik jako JSON")
    ap.add_argument("--max-queries", type=int, default=10,
                    help="Limit zapytań (default 10, koszt ~$0.10)")
    args = ap.parse_args()

    providers = collect_providers()
    if not providers:
        print("❌ Brak kluczy API. Ustaw przynajmniej jeden w env:")
        print("   $env:OPENAI_API_KEY      = 'sk-...'")
        print("   $env:ANTHROPIC_API_KEY   = 'sk-ant-...'")
        print("   $env:PERPLEXITY_API_KEY  = 'pplx-...'")
        return 1

    print(f"📡 AEO Active Probe — {args.domain}")
    print(f"   Providers: {', '.join(providers.keys())}")

    queries_file = Path(args.queries_file) if args.queries_file else None
    if queries_file is None and not args.topic:
        print("❌ Podaj --topic albo --queries-file")
        return 2

    queries = build_queries(args.topic or "", queries_file)[: args.max_queries]
    print(f"   Queries: {len(queries)}")
    print(f"   Estimated cost: ~${len(queries) * len(providers) * 0.003:.2f}")
    print()

    all_results: list[ProbeResult] = []
    for i, q in enumerate(queries, 1):
        print(f"  [{i}/{len(queries)}] {q[:80]}…")
        results = probe_query(q, args.domain, args.brand, providers)
        for r in results:
            icon = "❌" if r.error else ("✅" if r.cited else "⚪")
            print(f"      {icon} {r.provider}: " +
                  (f"ERR {r.error[:80]}" if r.error else
                   (f"cited ×{r.citation_count} pos={r.citation_position}%" if r.cited else "no citation")))
        all_results.extend(results)
        time.sleep(0.5)  # gentle rate-limit

    agg = aggregate_results(all_results)

    print()
    print("=" * 60)
    print(f"  CITATION RATE: {agg['overall_citation_rate']}% ({agg['successful_probes']} probes)")
    print("=" * 60)
    for prov, p in agg["by_provider"].items():
        print(f"  {prov:12s}: {p['citation_rate']}% ({p['cited_count']}/{p['total_queries']})")
    print()
    if agg["content_gaps"]:
        print("🔥 Content gaps (queries gdzie NIKT cię nie cytuje):")
        for q in agg["content_gaps"][:5]:
            print(f"  - {q}")

    md = render_md(args.domain, args.topic or "(custom queries)", all_results, agg)

    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"\n💾 Markdown: {args.md}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "domain": args.domain,
                "brand": args.brand,
                "topic": args.topic,
                "timestamp": datetime.now().isoformat(),
                "providers_used": list(providers.keys()),
                "queries": queries,
                "results": [asdict(r) for r in all_results],
                "aggregate": agg,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"💾 JSON: {args.json}")

    return 0 if agg["overall_citation_rate"] >= 30 else 1


if __name__ == "__main__":
    sys.exit(main())
