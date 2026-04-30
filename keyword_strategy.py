#!/usr/bin/env python3
"""
keyword_strategy.py — strategia słów kluczowych per artykuł + skala treści.

Co robi:
  1. PER ARTYKUŁ — wyciąga target keywords (z title, H1, H2, meta, first 200 słów + body)
     i liczy ich relevance score (TF-IDF light)
  2. CANNIBALIZATION — wykrywa kiedy >1 artykuł celuje w to samo zapytanie (zła rzecz)
  3. TOPICAL CLUSTERS — grupuje artykuły po wspólnych keywords (Jaccard similarity)
  4. CONTENT GAP — sugeruje brakujące tematy w klastrze (artykuły uzupełniające)
  5. MERIT SCORE — ocenia każdy artykuł: word count, fact density, citation density,
     unique vocab, cytaty, daty, badania → score 0-100 (czy to mięso czy filler?)
  6. SCALING REPORT — ile artykułów rzeczywiście niesie wartość, gdzie rozcieńczamy

Użycie:
    python keyword_strategy.py --folder ./output/zdrowie-fit --json strategy.json
    python keyword_strategy.py --folder ./output --md strategy.md
    python keyword_strategy.py --folder ./output --suggest 10  # top 10 sugestii nowych artykułów
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
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ─── POLSKIE STOP WORDS ───────────────────────────────────────────────────────

# Polskie + angielskie stop words (zbiór — duplikaty automatycznie pomijane).
# Lista posortowana, bez duplikatów (czyszczenie 2026-04-30).
_PL_STOPWORDS_RAW = (
    # Polskie
    "a aby ach acz aczkolwiek aj albo ale ależ ani aż "
    "bardziej bardzo bez bo bowiem by byli bynajmniej był "
    "była było były być będzie będą "
    "cali cała całą ci cię ciebie co cokolwiek coraz coś "
    "czasami czasem czemu czy czyli "
    "daleko dla dlaczego dlatego do dobrze dokąd dość dużo "
    "dwa dwaj dwie dwoje dziś dzisiaj "
    "gdy gdyby gdyż gdzie gdziekolwiek gdzieś go "
    "i ich ile im inna inne inny innych iż "
    "ja ją jak jakaś jakby jaki jakichś jakie jakiś jakiż jakkolwiek jako jakoś "
    "je jeden jedna jednak jednakże jedno jego jej jemu jest jestem jeszcze "
    "jeśli jeżeli już "
    "każdy kiedy kierunku kilka kimś "
    "kto ktokolwiek ktoś która które którego której który których którym którzy "
    "ku lat lecz lub "
    "ma mają mało mam mi miały mimo mnie mną mogą moi moim moja moje "
    "może możliwe można mój mu musi my "
    "na nad nam nami nas nasi nasz nasza nasze naszego naszej "
    "natomiast natychmiast nawet nią nic nich nie niech niego niej niemu "
    "nigdy nim nimi niż no nową nowe nowy "
    "o obok od około on ona one oni ono oraz oto owszem "
    "pan pana pani po pod podczas pomimo ponad ponieważ "
    "powinien powinna powinni powinno poza prawie "
    "przecież przed przede przedtem przez przy "
    "raz razie roku również "
    "sam sama są się skąd sobie sobą sposób swoje "
    "ta tak taka taki takie także tam te tego tej ten teraz też to "
    "tobą tobie toteż trzeba tu tutaj twoi twoim twoja twoje twym twój "
    "ty tych tylko tym tys "
    "u wam wami was wasi wasz wasza wasze we według "
    "wiele wielu więc więcej wszyscy wszystkich wszystkie wszystkim wszystko "
    "wtedy wy właśnie "
    "z za zapewne zawsze ze zł znowu znów "
    "żaden żadna żadne żadnych że żeby "
    # Angielskie częste w polskich tekstach naukowych
    "an the of and or in on at for to with as "
    "is are was were be been being this that these those "
    "but if then than so such from vs"
)
PL_STOPWORDS = frozenset(_PL_STOPWORDS_RAW.split())

# ─── EKSTRAKCJA HTML ──────────────────────────────────────────────────────────

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
META_KEYWORDS_RE = re.compile(
    r'<meta\b[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
TAG_RE = re.compile(
    r'<meta\b[^>]*property=["\']article:tag["\'][^>]*content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
A_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_STRIP = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"\b[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+\b")


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_STRIP.sub(" ", html)).strip()


@dataclass
class Article:
    path: str
    title: str
    h1: str
    h2_list: list[str]
    h3_list: list[str]
    meta_description: str
    article_tags: list[str]    # z article:tag meta
    body_text: str             # pełna treść (paragrafy)
    word_count: int
    first_200: str             # pierwsze ~200 słów (TL;DR area)
    citation_count: int        # linki do .edu/.gov/.org/PubMed/DOI
    fact_count: int            # liczby + lata + jednostki
    target_keywords: list[tuple[str, float]] = field(default_factory=list)  # (kw, score)
    merit_score: int = 0


def extract_article(path: Path, root: Path) -> Article | None:
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Wyłącznie article-content jeśli da się wyłuskać
    body = re.sub(r"<head\b.*?</head>", "", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style\b.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<nav\b.*?</nav>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<footer\b.*?</footer>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<aside\b.*?</aside>", "", body, flags=re.DOTALL | re.IGNORECASE)

    title = strip_tags(TITLE_RE.search(html).group(1)) if TITLE_RE.search(html) else ""
    h1 = strip_tags(H1_RE.search(body).group(1)) if H1_RE.search(body) else ""
    h2_list = [strip_tags(m) for m in H2_RE.findall(body)]
    h3_list = [strip_tags(m) for m in H3_RE.findall(body)]
    meta_desc = META_DESC_RE.search(html).group(1) if META_DESC_RE.search(html) else ""
    tags = TAG_RE.findall(html)
    paragraphs = [strip_tags(m) for m in P_RE.findall(body)]
    body_text = " ".join(paragraphs)
    words = WORD_RE.findall(body_text)
    word_count = len(words)
    first_200 = " ".join(body_text.split()[:200])

    # Citation count: klikalne <a href> + plain-text DOI/URL w bibliografii
    citation_count = 0
    for href, _t in A_RE.findall(html):
        h = href.lower()
        if any(d in h for d in (".edu", ".gov", "pubmed", "doi.org", "ncbi.nlm.nih.gov",
                                  "scholar.google", "wikipedia.org", "arxiv.org",
                                  "biorxiv.org", "medrxiv.org")):
            citation_count += 1
    # Plain-text DOI w body (np. bibliografia z DOI jako tekst, nie link)
    plain_doi = len(re.findall(r"\b10\.\d{4,}/[^\s<>\"]+", html))
    plain_authority = len(re.findall(
        r"https?://(?:www\.)?(?:pubmed|ncbi\.nlm\.nih\.gov|scholar\.google|arxiv\.org|biorxiv\.org)/\S+",
        html))
    # Bierzemy maksimum z dwóch metod (unikamy double-counting)
    citation_count = max(citation_count, plain_doi + plain_authority)

    # Fact count (liczby + lata + jednostki)
    fact_count = (
        len(re.findall(r"\b\d+(?:[.,]\d+)?(?:%|°C|°F|kg|mg|μg|min|sek|h|ms|mm|cm|m|km|x)?\b", body_text))
        + len(re.findall(r"\b(19|20)\d{2}\b", body_text))
    )

    return Article(
        path=str(path.relative_to(root)),
        title=title,
        h1=h1,
        h2_list=h2_list,
        h3_list=h3_list,
        meta_description=meta_desc,
        article_tags=tags,
        body_text=body_text,
        word_count=word_count,
        first_200=first_200,
        citation_count=citation_count,
        fact_count=fact_count,
    )


# ─── KEYWORD EXTRACTION (TF-IDF) ──────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)
            if w.lower() not in PL_STOPWORDS and len(w) >= 3 and not w.isdigit()]


def extract_ngrams(tokens: list[str], n: int = 2) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def extract_keywords_for_article(article: Article, idf: dict[str, float], top_k: int = 15) -> list[tuple[str, float]]:
    """TF-IDF light: 1-gramy + 2-gramy + 3-gramy.
    Boost dla terminów występujących w title/h1/h2/meta/tags."""
    tokens = tokenize(article.body_text)
    if not tokens:
        return []

    # Zbierz wszystkie kandydaty
    candidates: dict[str, float] = {}
    grams_all = (
        Counter(tokens)  # 1-grams
        + Counter(extract_ngrams(tokens, 2))  # 2-grams
        + Counter(extract_ngrams(tokens, 3))  # 3-grams
    )

    # Boost terms (title, H1, H2, meta_desc, tags)
    boost_text = " ".join([article.title, article.h1] + article.h2_list +
                           [article.meta_description] + article.article_tags).lower()

    for term, tf in grams_all.items():
        if tf < 2:  # ignoruj jednorazówki
            continue
        idf_val = idf.get(term, 1.0)
        score = (tf / max(article.word_count, 1)) * idf_val * 1000
        # Boost
        if term in boost_text:
            score *= 3
        if term in (article.title or "").lower() or term in article.h1.lower():
            score *= 2
        candidates[term] = score

    # Top k
    sorted_kws = sorted(candidates.items(), key=lambda x: -x[1])[:top_k]
    return [(kw, round(score, 2)) for kw, score in sorted_kws]


def build_idf(articles: list[Article]) -> dict[str, float]:
    """IDF dla wszystkich termów (1-3 gramy)."""
    n = len(articles)
    df: Counter[str] = Counter()
    for a in articles:
        tokens = tokenize(a.body_text)
        terms = set(tokens) | set(extract_ngrams(tokens, 2)) | set(extract_ngrams(tokens, 3))
        for t in terms:
            df[t] += 1
    return {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}


# ─── CANNIBALIZATION DETECTION ────────────────────────────────────────────────

def detect_cannibalization(articles: list[Article], top_k_per_article: int = 5) -> list[dict]:
    """Wykryj keywords które są target dla >1 artykułu (top_k każdego)."""
    keyword_to_articles: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for a in articles:
        for kw, score in a.target_keywords[:top_k_per_article]:
            keyword_to_articles[kw].append((a.path, score))

    issues = []
    for kw, refs in keyword_to_articles.items():
        if len(refs) > 1:
            refs_sorted = sorted(refs, key=lambda x: -x[1])
            issues.append({
                "keyword": kw,
                "competing_articles": [{"path": p, "score": s} for p, s in refs_sorted],
                "winner_score_delta": refs_sorted[0][1] - refs_sorted[1][1] if len(refs_sorted) > 1 else 0,
            })
    issues.sort(key=lambda x: -len(x["competing_articles"]))
    return issues


# ─── TOPICAL CLUSTERS (Jaccard similarity) ────────────────────────────────────

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def cluster_articles(articles: list[Article], threshold: float = 0.1,
                      min_shared: int = 3) -> list[list[str]]:
    """Klasteryzacja artykułów po wspólnych keywords.

    Dwa kryteria łączenia (OR):
      1. Jaccard similarity ≥ threshold (top 15 keywords)
      2. Liczba wspólnych keywords ≥ min_shared (z top 15)

    Druga metryka łapie klastry gdzie artykuły mają unikalne specjalistyczne
    słowa, ale dzielą wspólny rdzeń (np. 'depresja', 'mózg', 'badanie').
    """
    keyword_sets = {a.path: set(kw for kw, _ in a.target_keywords[:15]) for a in articles}
    clusters: list[list[str]] = []
    assigned: set[str] = set()
    for a in articles:
        if a.path in assigned:
            continue
        cluster = [a.path]
        assigned.add(a.path)
        for b in articles:
            if b.path == a.path or b.path in assigned:
                continue
            shared = keyword_sets[a.path] & keyword_sets[b.path]
            jacc = jaccard(keyword_sets[a.path], keyword_sets[b.path])
            if jacc >= threshold or len(shared) >= min_shared:
                cluster.append(b.path)
                assigned.add(b.path)
        clusters.append(cluster)
    return [c for c in clusters if len(c) >= 1]


# ─── MERIT SCORE ──────────────────────────────────────────────────────────────

def compute_merit_score(a: Article) -> tuple[int, list[str]]:
    """Score 0-100 + breakdown listy. Co decyduje:
      - word_count (≥1500 = pełnowartościowy long-form)
      - fact_count (gęstość faktów)
      - citation_count (linki do .edu/.gov/PubMed)
      - unique vocab ratio (ile różnych słów / total)
      - h2_question_ratio (FAQ-readiness)
      - meta_description present
      - article_tags present (≥3 tagi)
    """
    breakdown = []
    parts: list[float] = []

    # Word count
    if a.word_count >= 2000:
        parts.append(100); breakdown.append(f"✅ Long-form ({a.word_count} słów, ≥2000)")
    elif a.word_count >= 1200:
        parts.append(80); breakdown.append(f"✅ Pełna długość ({a.word_count} słów)")
    elif a.word_count >= 600:
        parts.append(50); breakdown.append(f"⚠️ Średnia długość ({a.word_count} słów, <1200)")
    elif a.word_count >= 300:
        parts.append(20); breakdown.append(f"❌ Krótki ({a.word_count} słów) — ryzyko thin content")
    else:
        parts.append(0); breakdown.append(f"❌ Bardzo krótki ({a.word_count} słów) — thin content")

    # Fact density (≥10 faktów na 1000 słów = wysoka)
    if a.word_count > 0:
        fd = a.fact_count / a.word_count * 1000
        if fd >= 10:
            parts.append(100); breakdown.append(f"✅ Wysoka gęstość faktów ({fd:.1f}/1000)")
        elif fd >= 5:
            parts.append(70); breakdown.append(f"⚠️ Średnia gęstość faktów ({fd:.1f}/1000)")
        else:
            parts.append(30); breakdown.append(f"❌ Niska gęstość faktów ({fd:.1f}/1000) — mało konkretów")

    # Citation count
    if a.citation_count >= 8:
        parts.append(100); breakdown.append(f"✅ {a.citation_count} cytowań autorytatywnych (.edu/.gov/PubMed)")
    elif a.citation_count >= 4:
        parts.append(70); breakdown.append(f"⚠️ {a.citation_count} cytowań")
    elif a.citation_count >= 1:
        parts.append(40); breakdown.append(f"❌ Tylko {a.citation_count} cytowań — mało E-E-A-T")
    else:
        parts.append(0); breakdown.append("❌ Brak cytowań do autorytatywnych źródeł")

    # Unique vocab ratio
    tokens = tokenize(a.body_text)
    if tokens:
        unique_ratio = len(set(tokens)) / len(tokens)
        if unique_ratio >= 0.5:
            parts.append(100); breakdown.append(f"✅ Bogate słownictwo (unique ratio {unique_ratio:.2f})")
        elif unique_ratio >= 0.35:
            parts.append(70); breakdown.append(f"⚠️ Średnie słownictwo ({unique_ratio:.2f})")
        else:
            parts.append(30); breakdown.append(f"❌ Powtarzalne słownictwo ({unique_ratio:.2f}) — możliwe filler")

    # H2-pytania (FAQ ready)
    if a.h2_list:
        q_pct = sum(1 for h in a.h2_list if "?" in h) / len(a.h2_list) * 100
        if q_pct >= 30:
            parts.append(100); breakdown.append(f"✅ {q_pct:.0f}% H2 jako pytania (FAQ-ready)")
        elif q_pct >= 10:
            parts.append(60); breakdown.append(f"⚠️ {q_pct:.0f}% H2 jako pytania")
        else:
            parts.append(20); breakdown.append(f"❌ Tylko {q_pct:.0f}% H2 jako pytania")

    # Meta description
    if a.meta_description and 70 <= len(a.meta_description) <= 165:
        parts.append(100); breakdown.append(f"✅ Meta description właściwa długość ({len(a.meta_description)} znaków)")
    elif a.meta_description:
        parts.append(50); breakdown.append(f"⚠️ Meta description nieoptymalna długość ({len(a.meta_description)} znaków, cel 70-165)")
    else:
        parts.append(0); breakdown.append("❌ Brak meta description")

    # Article tags
    if len(a.article_tags) >= 5:
        parts.append(100); breakdown.append(f"✅ {len(a.article_tags)} tagów")
    elif len(a.article_tags) >= 3:
        parts.append(70); breakdown.append(f"⚠️ {len(a.article_tags)} tagów")
    else:
        parts.append(30); breakdown.append(f"❌ Tylko {len(a.article_tags)} tagów (cel ≥5)")

    score = int(sum(parts) / len(parts)) if parts else 0
    return score, breakdown


# ─── CONTENT GAP SUGGESTIONS ──────────────────────────────────────────────────

def suggest_content_gaps(articles: list[Article], idf: dict[str, float], top_n: int = 10) -> list[dict]:
    """Sugestie nowych artykułów na bazie:
      1. Single-occurrence high-value 2-3 grams (w jednym artykule, ale wysoki IDF)
      2. Klastry z ≤2 artykułami → expand ten klaster
      3. H2 pytania nie pokryte własnymi artykułami → kandydat na samodzielny artykuł
    """
    suggestions: list[dict] = []

    # 1. High-IDF terms used only in 1-2 articles
    term_articles: dict[str, list[str]] = defaultdict(list)
    for a in articles:
        for kw, score in a.target_keywords[:10]:
            term_articles[kw].append(a.path)

    for term, paths in term_articles.items():
        if len(paths) == 1 and idf.get(term, 0) >= 1.5 and len(term.split()) >= 2:
            suggestions.append({
                "type": "expand_topic",
                "keyword": term,
                "mentioned_in": paths[0],
                "rationale": "Wartościowe słowo kluczowe wymienione tylko w 1 artykule — temat zasługuje na samodzielne pogłębienie",
                "priority": round(idf[term], 2),
            })

    # 2. H2 questions niepokryte przez własny artykuł
    article_titles_lower = " ".join(a.title.lower() for a in articles)
    for a in articles:
        for h2 in a.h2_list:
            if "?" in h2:
                # Wyciągnij keyword z pytania
                question_clean = re.sub(r"[?!,.:;]", "", h2.lower())
                tokens = [t for t in question_clean.split() if t not in PL_STOPWORDS and len(t) > 3]
                key_phrase = " ".join(tokens[:3])
                if key_phrase and key_phrase not in article_titles_lower and len(key_phrase) >= 8:
                    suggestions.append({
                        "type": "h2_to_article",
                        "question": h2[:120],
                        "extracted_phrase": key_phrase,
                        "from_article": a.path,
                        "rationale": "Pytanie w H2 zasługuje na samodzielny artykuł odpowiadający bezpośrednio",
                        "priority": 1.0,
                    })

    # Deduplicate similar suggestions
    seen = set()
    unique = []
    for s in suggestions:
        key = s.get("keyword") or s.get("extracted_phrase") or s.get("question", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    unique.sort(key=lambda x: -x.get("priority", 0))
    return unique[:top_n]


# ─── ZBIORCZY RAPORT ──────────────────────────────────────────────────────────

def render_markdown_report(articles: list[Article], cannib: list[dict],
                            clusters: list[list[str]], suggestions: list[dict]) -> str:
    lines = ["# Strategia słów kluczowych — raport\n"]
    lines.append(f"**Artykułów przeanalizowanych:** {len(articles)}")
    avg_merit = sum(a.merit_score for a in articles) / max(len(articles), 1)
    lines.append(f"**Średni merit score:** {avg_merit:.0f}/100")
    lines.append(f"**Klastrów tematycznych:** {len(clusters)}")
    lines.append(f"**Konfliktów (cannibalization):** {len(cannib)}")
    lines.append(f"**Sugestii nowych artykułów:** {len(suggestions)}\n")

    # Per artykuł
    lines.append("## Analiza per artykuł\n")
    for a in sorted(articles, key=lambda x: -x.merit_score):
        lines.append(f"### {a.title or a.path}")
        lines.append(f"- **Path:** `{a.path}`")
        lines.append(f"- **Merit score:** {a.merit_score}/100")
        lines.append(f"- **Word count:** {a.word_count}, **Fact count:** {a.fact_count}, **Citations:** {a.citation_count}")
        if a.target_keywords:
            kws_str = ", ".join(f"`{kw}` ({score:.1f})" for kw, score in a.target_keywords[:8])
            lines.append(f"- **Top keywords:** {kws_str}")
        lines.append("")

    # Cannibalization
    if cannib:
        lines.append("## Konflikty słów kluczowych (cannibalization)\n")
        lines.append("Te keywords są target dla wielu artykułów — wybierz jednego mistrza, do reszty dodaj canonical lub przekierowanie tematyczne:\n")
        for issue in cannib[:15]:
            lines.append(f"### `{issue['keyword']}` — {len(issue['competing_articles'])} artykułów konkuruje")
            for ref in issue["competing_articles"][:5]:
                lines.append(f"- `{ref['path']}` (score {ref['score']:.1f})")
            lines.append("")

    # Klastry
    if clusters:
        lines.append("## Klastry tematyczne\n")
        for i, cluster in enumerate(clusters, 1):
            if len(cluster) >= 2:
                lines.append(f"**Klaster #{i}** ({len(cluster)} artykułów):")
                for path in cluster:
                    lines.append(f"- `{path}`")
                lines.append("")

    # Sugestie
    if suggestions:
        lines.append("## Sugestie nowych artykułów\n")
        for i, s in enumerate(suggestions, 1):
            if s["type"] == "expand_topic":
                lines.append(f"{i}. **Pogłęb temat:** `{s['keyword']}` — wymieniony tylko w `{s['mentioned_in']}`. Priority {s['priority']}")
            else:
                lines.append(f"{i}. **Pytanie → artykuł:** \"{s['question']}\" (z `{s['from_article']}`)")
        lines.append("")

    return "\n".join(lines)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Strategia keywords + cannibalization + clusters + content gaps + merit score.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  python keyword_strategy.py --folder ./output/zdrowie-fit --md strategy.md\n"
            "  python keyword_strategy.py --folder ./output --json strategy.json --suggest 20\n"
        ),
    )
    ap.add_argument("--folder", required=True, help="Folder z plikami HTML")
    ap.add_argument("--md", help="Zapis raportu jako Markdown")
    ap.add_argument("--json", help="Zapis raportu jako JSON")
    ap.add_argument("--suggest", type=int, default=10, help="Ile sugestii nowych artykułów (default 10)")
    ap.add_argument("--limit", type=int, default=200, help="Max artykułów do analizy")
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.exists():
        print(f"❌ Folder nie istnieje: {folder}")
        return 2

    print(f"🔍 Skanuję {folder}…")
    html_files = sorted(folder.rglob("*.html"))[:args.limit]
    articles: list[Article] = []
    for hf in html_files:
        a = extract_article(hf, folder)
        if a and a.word_count >= 100:  # ignoruj indeksy/404 itp.
            articles.append(a)
    print(f"   Znaleziono {len(articles)} artykułów (≥100 słów)")

    if not articles:
        print("❌ Brak artykułów do analizy")
        return 1

    print("📊 Liczę IDF…")
    idf = build_idf(articles)

    print("🔑 Ekstrahuję keywords per artykuł…")
    for a in articles:
        a.target_keywords = extract_keywords_for_article(a, idf, top_k=15)
        a.merit_score, _ = compute_merit_score(a)

    print("⚔️  Sprawdzam kanibalizację…")
    cannib = detect_cannibalization(articles)

    print("🗂️  Klastrowanie tematyczne…")
    clusters = cluster_articles(articles)

    print("💡 Sugestie nowych artykułów…")
    suggestions = suggest_content_gaps(articles, idf, top_n=args.suggest)

    # Render
    md = render_markdown_report(articles, cannib, clusters, suggestions)
    print()
    print(md[:3000] + ("\n... (raport ucięty — pełny w pliku --md)" if len(md) > 3000 else ""))

    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"\n💾 Markdown: {args.md}")

    if args.json:
        data = {
            "articles": [
                {
                    "path": a.path, "title": a.title, "word_count": a.word_count,
                    "fact_count": a.fact_count, "citation_count": a.citation_count,
                    "merit_score": a.merit_score,
                    "target_keywords": a.target_keywords,
                    "h2_list": a.h2_list, "article_tags": a.article_tags,
                }
                for a in articles
            ],
            "cannibalization": cannib,
            "clusters": clusters,
            "suggestions": suggestions,
            "summary": {
                "n_articles": len(articles),
                "avg_merit_score": round(sum(a.merit_score for a in articles) / max(len(articles), 1), 1),
                "total_word_count": sum(a.word_count for a in articles),
                "total_citations": sum(a.citation_count for a in articles),
            },
        }
        Path(args.json).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"💾 JSON: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
