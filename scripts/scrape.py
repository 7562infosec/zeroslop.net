#!/usr/bin/env python3
"""
zeroslop.net — Daily positive AI & innovation news scraper
Fetches stories from 40 RSS feeds, filters for breakthrough/innovation content,
scores by relevance, generates upbeat summaries via GitHub Models, and writes a Jekyll post.
"""

import os
import json
import re
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from openai import OpenAI

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
        return urllib.parse.urlunparse(parsed)
    except Exception:
        return ""

def sanitize_text(text: str) -> str:
    """Strip control chars and truncate."""
    if not text:
        return ""
    text = "".join(c for c in text if c >= " " or c in "\t\n")
    return text[:500]


def fix_encoding(text: str) -> str:
    """Fix UTF-8/Latin-1 double-encoding artifacts (e.g. Â· → ·)."""
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


# ─────────────────────────────────────────────────────────────────────────────
# RSS Feeds
# ─────────────────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # ── Core Tech / AI ────────────────────────────────────────────────────────────
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

    # ── Innovation / Startup / VC ─────────────────────────────────────────────────────
    ("a16z",                 "https://a16z.com/feed/"),
    ("NVIDIA Blog",          "https://blogs.nvidia.com/feed/"),
    ("Microsoft AI",         "https://blogs.microsoft.com/ai/feed/"),
    ("AWS Blog",             "https://aws.amazon.com/blogs/aws/feed/"),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("MarkTechPost",         "https://www.marktechpost.com/feed/"),
    ("Hugging Face Blog",    "https://huggingface.co/blog/feed.xml"),
    ("arXiv CS.AI",          "https://rss.arxiv.org/rss/cs.AI"),

    # ── AI Lab Blogs ──────────────────────────────────────────────────────────────────
    ("OpenAI News",          "https://openai.com/news/rss.xml"),
    ("Anthropic News",       "https://www.anthropic.com/rss.xml"),
    ("Google DeepMind",      "https://deepmind.google/blog/rss.xml"),
    ("Google AI Blog",       "https://blog.google/technology/ai/rss/"),

    # ── Cybersecurity / AI Security ───────────────────────────────────────────────
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

POSITIVE_KEYWORDS = [
    "breakthrough", "launches", "released", "milestone", "innovation",
    "achievement", "solves", "improves", "enables", "discovers",
    "raises", "partnership", "collaboration", "open source",
    "safety", "responsible ai", "alignment", "beneficial",
    "cybersecurity ai", "ai security", "threat detection", "ai defense",
    "generative ai", "multimodal", "agentic",
]

GENERAL_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning",
    "large language model", "llm", "foundation model",
    "chatgpt", "claude", "gemini", "gpt", "mistral", "llama",
    "ai model", "ai agent", "ai tool", "ai system",
    "automation", "robotics", "neural network",
    "funding", "investment", "startup", "raises",
    "research", "paper", "study",
]

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
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    pruned = {url: date for url, date in seen.items() if date >= cutoff}
    with open(SEEN_FILE, "w") as f:
        json.dump(pruned, f, indent=2)


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
            title = fix_encoding(entry.get("title", "").strip())
            raw_summary = (
                entry.get("summary")
                or entry.get("description")
                or entry.get("content", [{}])[0].get("value", "")
            )
            summary = fix_encoding(clean_html(raw_summary))
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


def summarize_with_llm(title: str, summary: str, client: OpenAI) -> str:
    prompt = (
        f"You are a tech journalist for zeroslop.net — a site that celebrates AI breakthroughs, "
        f"innovation, and technology that makes a positive difference. "
        f"Write a punchy 2–3 sentence summary of this story with an enthusiastic, forward-looking tone. "
        f"Highlight what's exciting, what was achieved, or why it matters. No hype or filler — just clear, "
        f"energetic writing that makes the reader want to learn more. "
        f"Do not begin your response with a Markdown heading.\n\n"
        f"Story title: {title}\n\n"
        f"Story excerpt: {summary}\n\n"
        f"Summary:"
    )
    try:
        model = os.environ.get("GITHUB_MODEL", "gpt-4o-mini")
        response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content.strip()
        text = re.sub(r'^#{1,6}\s+.*\n?', '', text, flags=re.MULTILINE).strip()
        return text
    except Exception as e:
        log.warning(f"LLM summary failed: {e}")
        return summary[:300] + "..."


def build_post(stories: list[dict], date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    today_display = d.strftime("%B ") + str(d.day) + ", " + str(d.year)
    lines = [
        "---",
        "layout: post",
        f'title: "ZeroSlop — {today_display}"',
        f"date: {date_str}",
        f'description: "Top AI and technology breakthroughs for {today_display} — launches, innovations, and ideas worth knowing."',
        "categories: [daily-digest]",
        "tags: [ai, innovation, technology, breakthroughs]",
        "---",
        "",
        f"*{len(stories)} stories worth knowing about today — AI breakthroughs, launches, and innovations making a difference.*",
        "",
        "<!--more-->",
        "",
    ]
    for i, story in enumerate(stories):
        lines += [
            f"## {story['source']}",
            "",
            f"**[{sanitize_text(story['title'])}]({sanitize_url(story['url']) or '#'})**  ",
            story["ai_summary"],
            "",
        ]
        if i < len(stories) - 1:
            lines += ["---", ""]
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise SystemExit("ERROR: GITHUB_TOKEN environment variable not set")

    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=github_token,
    )
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    seen_data: dict = {}
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            seen_data = json.load(f)
    seen_urls = set(seen_data.keys())

    log.info("Fetching RSS feeds...")
    all_stories: list[dict] = []
    for name, url in RSS_FEEDS:
        stories = fetch_feed(name, url)
        log.info(f"  {name}: {len(stories)} entries")
        all_stories.extend(stories)

    log.info(f"Total raw stories: {len(all_stories)}")

    seen_this_run: set[str] = set()
    unique_stories: list[dict] = []
    for s in all_stories:
        url = s["url"]
        if url in seen_urls or url in seen_this_run:
            continue
        seen_this_run.add(url)
        unique_stories.append(s)

    log.info(f"After dedup: {len(unique_stories)} stories")

    for s in unique_stories:
        s["score"] = score_story(s["title"], s["summary"])

    candidates = [s for s in unique_stories if s["score"] >= MIN_SCORE]
    candidates.sort(key=lambda s: s["score"], reverse=True)
    top_stories = candidates[:MAX_STORIES]

    log.info(f"Top stories selected: {len(top_stories)}")

    if not top_stories:
        log.warning("No qualifying stories found today — skipping post generation.")
        return

    model = os.environ.get("GITHUB_MODEL", "gpt-4o-mini")
    log.info(f"Generating summaries with GitHub Models ({model})...")
    for i, story in enumerate(top_stories):
        log.info(f"  [{i+1}/{len(top_stories)}] {story['title'][:70]}...")
        story["ai_summary"] = summarize_with_llm(story["title"], story["summary"], client)

    POSTS_DIR.mkdir(exist_ok=True)
    post_path = POSTS_DIR / f"{today}-daily-digest.md"
    post_content = build_post(top_stories, today)
    post_path.write_text(post_content, encoding="utf-8")
    log.info(f"Post written: {post_path}")

    for s in top_stories:
        seen_data[s["url"]] = today
    save_seen_urls(seen_data)
    log.info("seen_urls.json updated")


if __name__ == "__main__":
    main()
