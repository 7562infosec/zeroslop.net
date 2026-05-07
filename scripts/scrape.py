#!/usr/bin/env python3
"""
zeroslop.net — Daily positive AI & innovation news scraper
Fetches stories from 40 RSS feeds, filters for breakthrough/innovation content,
scores by relevance, generates upbeat Claude Haiku summaries, and writes a Jekyll post.
"""

import os
import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import anthropic

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT   = SCRIPT_DIR.parent
POSTS_DIR   = REPO_ROOT / "_posts"
SEEN_FILE   = SCRIPT_DIR / "seen_urls.json"
MAX_STORIES = 12   # stories per daily post
MIN_SCORE   = 2    # minimum relevance score to include

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

import urllib.parse

def sanitize_url(url: str) -> str:
    """Accept only http/https URLs; return empty string for anything else."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return ""
        # Reconstruct to normalize
        return urllib.parse.urlunparse(parsed)
    except Exception:
        return ""

def sanitize_text(text: str) -> str:
    """Strip control chars and escape markdown-sensitive characters in titles/summaries."""
    if not text:
        return ""
    # Remove control characters (except tab/newline)
    text = "".join(c for c in text if c >= " " or c in "\t\n")
    # Truncate very long tokens
    return text[:500]


# ─────────────────────────────────────────────────────────────────────────────
# RSS Feeds  (original 12 + innovation-focused additions)
# ─────────────────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # ── Core Tech / AI ──────────────────────────────────────────────────────
    ("The Verge AI",         "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Ars Technica",         "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Wired AI",             "https://www.wired.com/feed/tag/ai/latest/rss"),
    ("Wired Security",       "https://www.wired.com/feed/category/security/latest/rss"),
    ("MIT Tech Review",      "https://www.technologyreview.com/feed/"),
    ("MIT Tech Review AI",   "https://www.technologyreview.com/topic/artificial-intelligence/feed/"),
    ("VentureBeat AI",       "https://venturebeat.com/category/ai/feed/"),
    ("TechCrunch AI",        "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("Futurism",             "https://futurism.com/feed"),
    ("The Guardian Tech",    "https://www.theguardian.com/technology/rss"),
    ("NY Times Tech",        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("Reuters Tech",         "https://feeds.reuters.com/reuters/technologyNews"),
    ("404 Media",            "https://www.404media.co/rss/"),
    ("Tom's Hardware",       "https://www.tomshardware.com/rss.xml"),
    ("Slashdot",             "https://rss.slashdot.org/Slashdot/slashdotMain"),
    ("It's FOSS",            "https://itsfoss.com/rss/"),

    # ── Innovation / Startup / VC ───────────────────────────────────────────
    ("a16z",                 "https://a16z.com/feed/"),
    ("NVIDIA Blog",          "https://blogs.nvidia.com/feed/"),
    ("Microsoft AI",         "https://blogs.microsoft.com/ai/feed/"),
    ("AWS Blog",             "https://aws.amazon.com/blogs/aws/feed/"),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("MarkTechPost",         "https://www.marktechpost.com/feed/"),
    ("Hugging Face Blog",    "https://huggingface.co/blog/feed.xml"),
    ("arXiv CS.AI",          "https://rss.arxiv.org/rss/cs.AI"),

    # ── AI Lab Blogs ────────────────────────────────────────────────────────
    ("OpenAI News",          "https://openai.com/news/rss.xml"),
    ("Anthropic News",       "https://www.anthropic.com/rss.xml"),
    ("Google DeepMind",      "https://deepmind.google/blog/rss.xml"),
    ("Google AI Blog",       "https://blog.google/technology/ai/rss/"),

    # ── Cybersecurity / AI Security ─────────────────────────────────────────
    ("AWS Security",         "https://aws.amazon.com/blogs/security/feed/"),
    ("CISA Alerts",          "https://us-cert.cisa.gov/ncas/alerts.xml"),
    ("Krebs on Security",    "http://krebsonsecurity.com/feed/"),
    ("Schneier on Security", "https://www.schneier.com/blog/atom.xml"),
    ("Recorded Future",      "https://www.recordedfuture.com/feed/"),
    ("Cisco Security",       "https://blogs.cisco.com/security/feed"),
    ("Cisco Talos",          "http://feeds.feedburner.com/feedburner/Talos"),
    ("SecurityWeek",         "http://feeds.feedburner.com/Securityweek"),
    ("Google Security Blog", "http://googleonlinesecurity.blogspot.com/atom.xml"),
    ("Darknet Hackers",      "http://feeds.feedburner.com/darknethackers"),
    ("EFF Updates",          "https://www.eff.org/rss/updates.xml"),
    ("The Intercept",        "https://theintercept.com/feed/?rss"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Keywords — positive / innovation framing
# ─────────────────────────────────────────────────────────────────────────────

# High-weight positive keywords (score += 3 each)
POSITIVE_KEYWORDS = [
    "breakthrough", "launches", "released", "milestone", "innovation",
    "achievement", "solves", "improves", "enables", "discovers",
    "raises", "partnership", "collaboration", "open source",
    "safety", "responsible ai", "alignment", "beneficial",
    "cybersecurity ai", "ai security", "threat detection", "ai defense",
    "generative ai", "multimodal", "agentic",
]

# General AI / tech keywords (score += 1 each)
GENERAL_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "large language model", "llm", "foundation model",
    "chatgpt", "claude", "gemini", "gpt", "mistral", "llama",
    "ai model", "ai agent", "ai tool", "ai system",
    "automation", "robotics", "neural network",
    "funding", "investment", "startup", "raises",
    "research", "paper", "study",
]

# Negative/slop filter — downrank these
NEGATIVE_KEYWORDS = [
    "controversy", "lawsuit", "sued", "scandal", "misinformation",
    "hallucination", "bias", "discrimination", "layoffs", "fired",
    "ban", "blocked", "censored", "copyright", "plagiarism",
    "deepfake", "scam", "fraud", "manipulation",
]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_seen_urls() -> set:
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            data = json.load(f)
        return set(data.keys())
    return set()


def save_seen_urls(seen: dict):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def score_story(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    score = 0
    for kw in POSITIVE_KEYWORDS:
        if kw in text:
            score += 3
    for kw in GENERAL_KEYWORDS:
        if kw in text:
            score += 1
    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
            score -= 2
    return score


def clean_html(raw: str) -> str:
    soup = BeautifulSoup(raw or "", "html.parser")
    return soup.get_text(separator=" ", strip=True)[:800]


def fetch_feed(name: str, url: str) -> list[dict]:
    stories = []
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "zeroslop-bot/1.0"})
        for entry in feed.entries[:30]:
            link  = entry.get("link", "")
            title = entry.get("title", "").strip()
            raw_summary = (
                entry.get("summary")
                or entry.get("description")
                or entry.get("content", [{}])[0].get("value", "")
            )
            summary = clean_html(raw_summary)
            published = ""
            for field in ("published", "updated", "created"):
                if hasattr(entry, field):
                    try:
                        published = dateparser.parse(getattr(entry, field)).isoformat()
                    except Exception:
                        pass
                    break
            if link and title:
                stories.append({
                    "source": name,
                    "url":    link,
                    "title":  title,
                    "summary": summary,
                    "published": published,
                })
    except Exception as e:
        log.warning(f"Failed to fetch {name}: {e}")
    return stories


def summarize_with_claude(title: str, summary: str, client: anthropic.Anthropic) -> str:
    prompt = (
        f"You are a tech journalist for zeroslop.net — a site that celebrates AI breakthroughs, "
        f"innovation, and technology that makes a positive difference. "
        f"Write a punchy 2–3 sentence summary of this story with an enthusiastic, forward-looking tone. "
        f"Highlight what's exciting, what was achieved, or why it matters. No hype or filler — just clear, "
        f"energetic writing that makes the reader want to learn more.\n\n"
        f"Story title: {title}\n\n"
        f"Story excerpt: {summary}\n\n"
        f"Summary:"
    )
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        log.warning(f"Claude summary failed: {e}")
        return summary[:300] + "..."


def build_post(stories: list[dict], date_str: str) -> str:
    today_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    lines = [
        "---",
        "layout: post",
        f'title: "ZeroSlop — {today_display}"',
        f"date: {date_str}",
        "categories: [daily-digest]",
        "tags: [ai, innovation, technology, breakthroughs]",
        "---",
        "",
        f"*{len(stories)} stories worth knowing about today — AI breakthroughs, launches, and innovations making a difference.*",
        "",
    ]
    for story in stories:
        lines += [
            f"## {story['source']}",
            "",
            f"**[{sanitize_text(story['title'])}]({sanitize_url(story['url']) or '#'})**  ",
            story["ai_summary"],
            "",
            "---",
            "",
        ]
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load previous URLs
    seen_data: dict = {}
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            seen_data = json.load(f)
    seen_urls = set(seen_data.keys())

    # Fetch all feeds
    log.info("Fetching RSS feeds...")
    all_stories: list[dict] = []
    for name, url in RSS_FEEDS:
        stories = fetch_feed(name, url)
        log.info(f"  {name}: {len(stories)} entries")
        all_stories.extend(stories)

    log.info(f"Total raw stories: {len(all_stories)}")

    # Deduplicate by URL
    seen_this_run: set[str] = set()
    unique_stories: list[dict] = []
    for s in all_stories:
        url = s["url"]
        if url in seen_urls or url in seen_this_run:
            continue
        seen_this_run.add(url)
        unique_stories.append(s)

    log.info(f"After dedup: {len(unique_stories)} stories")

    # Score and filter
    for s in unique_stories:
        s["score"] = score_story(s["title"], s["summary"])

    candidates = [s for s in unique_stories if s["score"] >= MIN_SCORE]
    candidates.sort(key=lambda s: s["score"], reverse=True)
    top_stories = candidates[:MAX_STORIES]

    log.info(f"Top stories selected: {len(top_stories)}")

    if not top_stories:
        log.warning("No qualifying stories found today — skipping post generation.")
        return

    # Generate Claude summaries
    log.info("Generating summaries with Claude Haiku...")
    for i, story in enumerate(top_stories):
        log.info(f"  [{i+1}/{len(top_stories)}] {story['title'][:70]}...")
        story["ai_summary"] = summarize_with_claude(story["title"], story["summary"], client)

    # Write Jekyll post
    POSTS_DIR.mkdir(exist_ok=True)
    post_path = POSTS_DIR / f"{today}-daily-digest.md"
    post_content = build_post(top_stories, today)
    post_path.write_text(post_content, encoding="utf-8")
    log.info(f"Post written: {post_path}")

    # Update seen_urls
    for s in top_stories:
        seen_data[s["url"]] = today
    save_seen_urls(seen_data)
    log.info("seen_urls.json updated")


if __name__ == "__main__":
    main()
