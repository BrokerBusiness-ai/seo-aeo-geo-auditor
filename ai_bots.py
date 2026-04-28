"""
ai_bots.py — kanoniczna lista AI crawlerów (kwiecień 2026).
Źródło: ai-robots-txt/ai.robots.txt + research SOTA.
"""

# Wszystkie znane boty AI z operatorami i typem działania
AI_BOTS = [
    # OpenAI
    ("GPTBot",                    "OpenAI",     "training"),
    ("ChatGPT-User",              "OpenAI",     "on-demand"),
    ("OAI-SearchBot",             "OpenAI",     "search-index"),
    # Anthropic
    ("ClaudeBot",                 "Anthropic",  "training"),
    ("Claude-Web",                "Anthropic",  "on-demand-legacy"),
    ("claude-searchbot",          "Anthropic",  "search-index"),
    # Perplexity
    ("PerplexityBot",             "Perplexity", "index"),
    ("Perplexity-User",           "Perplexity", "on-demand"),
    # Google
    ("Google-Extended",           "Google",     "training-optout"),
    ("GoogleOther",               "Google",     "research"),
    # Apple
    ("Applebot-Extended",         "Apple",      "training"),
    # Amazon
    ("Amazonbot",                 "Amazon",     "alexa-rufus"),
    # ByteDance / TikTok
    ("Bytespider",                "ByteDance",  "training"),
    # Common Crawl (feeds many LLMs)
    ("CCBot",                     "CommonCrawl","training"),
    # Meta
    ("Meta-ExternalAgent",        "Meta",       "training"),
    ("Meta-ExternalFetcher",      "Meta",       "on-demand"),
    # Cohere
    ("cohere-ai",                 "Cohere",     "training"),
    ("cohere-training-data-crawler", "Cohere",  "training"),
    # Diffbot (knowledge graph used by LLMs)
    ("Diffbot",                   "Diffbot",    "knowledge-graph"),
    # Mistral / Le Chat
    ("MistralAI-User",            "Mistral",    "on-demand"),
    # DuckDuckGo
    ("DuckAssistBot",             "DuckDuckGo", "duckassist"),
    # You.com
    ("YouBot",                    "You.com",    "index"),
    # Timpi
    ("Timpibot",                  "Timpi",      "index"),
    # Webz.io / omgili (resold to LLMs)
    ("omgili",                    "Webz.io",    "resold"),
    ("omgilibot",                 "Webz.io",    "resold"),
    # Hive image AI
    ("ImagesiftBot",              "Hive",       "image-ai"),
]

REQUIRED_AI_BOTS = [name for name, _, _ in AI_BOTS]


def render_robots_txt(
    sitemap_url: str = "https://example.com/sitemap.xml",
    allow_ai: bool = True,
    extra_disallow: list[str] | None = None,
) -> str:
    """Generuj kompletny robots.txt z wszystkimi botami AI."""
    extra_disallow = extra_disallow or ["/admin/", "/private/", "/.git/", "/data/"]
    lines = []
    lines.append("# robots.txt — wygenerowany przez seo-aeo-geo-auditor/fixer")
    lines.append("# Pełna lista AI crawlerów (kwiecień 2026)")
    lines.append("")
    lines.append("# === AI CRAWLERS ===")
    lines.append("# Zmień Allow: / na Disallow: / żeby zablokować trening AI")
    lines.append("")
    for name, op, kind in AI_BOTS:
        lines.append(f"User-agent: {name}")
    lines.append(f"{'Allow' if allow_ai else 'Disallow'}: /")
    lines.append("")
    lines.append("# === STANDARD CRAWLERS ===")
    lines.append("User-agent: *")
    lines.append("Allow: /")
    for path in extra_disallow:
        lines.append(f"Disallow: {path}")
    lines.append("")
    lines.append(f"Sitemap: {sitemap_url}")
    base = sitemap_url.rsplit("/sitemap.xml", 1)[0] or sitemap_url.rsplit("/", 1)[0]
    lines.append(f"# Pliki AI: {base}/llms.txt, {base}/llms-full.txt")
    lines.append("")
    return "\n".join(lines)
