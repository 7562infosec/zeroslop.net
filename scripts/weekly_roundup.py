#!/usr/bin/env python3
"""
zeroslop.net — Weekly roundup generator
Reads the past 7 daily posts from _posts/, extracts all stories,
picks the top highlights, and writes a "Week in AI" roundup post.
"""

import os
import re
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT   = SCRIPT_DIR.parent
POSTS_DIR   = REPO_ROOT / "_posts"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_week_stories() -> list[dict]:
    """Parse the last 7 daily digest posts and return all stories."""
    today = datetime.now(timezone.utc).date()
    stories = []

    for days_ago in range(1, 8):
        date = today - timedelta(days=days_ago)
        post_path = POSTS_DIR / f"{date}-daily-digest.md"
        if not post_path.exists():
            continue

        content = post_path.read_text(encoding="utf-8")
        # Extract story blocks: ## Source / **[Title](URL)** / summary
        blocks = re.split(r"\n## ", content)
        for block in blocks[1:]:  # skip front matter block
            lines = block.strip().splitlines()
            if not lines:
                continue
            source = lines[0].strip()
            title_match = re.search(r"\*\*\[(.+?)\]\((.+?)\)\*\*", block)
            if not title_match:
                continue
            title = title_match.group(1)
            url   = title_match.group(2)
            # Summary is the line after the title line
            title_line_idx = next(
                (i for i, l in enumerate(lines) if "**[" in l), None
            )
            summary = ""
            if title_line_idx is not None and title_line_idx + 1 < len(lines):
                summary = lines[title_line_idx + 1].strip()

            stories.append({
                "date":    str(date),
                "source":  source,
                "title":   title,
                "url":     url,
                "summary": summary,
            })

    log.info(f"Loaded {len(stories)} stories from the past week")
    return stories


def generate_roundup_intro(stories: list[dict], client: anthropic.Anthropic) -> str:
    titles = "\n".join(f"- {s['title']}" for s in stories[:20])
    prompt = (
        "You write for zeroslop.net, a site celebrating AI breakthroughs and innovation. "
        "Write a lively 3-sentence intro paragraph for this week's 'Week in AI' roundup. "
        "Mention 2–3 themes you noticed this week based on the story headlines below. "
        "Be enthusiastic and forward-looking — make the reader excited about what's happening in AI.\n\n"
        f"This week's headlines:\n{titles}\n\nIntro:"
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.warning(f"Intro generation failed: {e}")
        return "Another week packed with AI breakthroughs. Here are the highlights."


def build_roundup_post(stories: list[dict], intro: str, week_start: str, week_end: str) -> str:
    start_display = datetime.strptime(week_start, "%Y-%m-%d").strftime("%B %-d")
    end_display   = datetime.strptime(week_end,   "%Y-%m-%d").strftime("%B %-d, %Y")

    lines = [
        "---",
        "layout: post",
        f'title: "Week in AI — {start_display}–{end_display}"',
        f"date: {week_end}",
        "categories: [weekly-roundup]",
        "tags: [ai, innovation, technology, weekly, breakthroughs]",
        "---",
        "",
        intro,
        "",
        "---",
        "",
    ]

    # Group by source for a cleaner weekly format
    by_source: dict[str, list[dict]] = {}
    for s in stories:
        by_source.setdefault(s["source"], []).append(s)

    for source, source_stories in sorted(by_source.items()):
        lines.append(f"## {source}")
        lines.append("")
        for s in source_stories:
            lines.append(f"**[{s['title']}]({s['url']})**  ")
            if s["summary"]:
                lines.append(s["summary"])
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    today  = datetime.now(timezone.utc).date()

    stories = load_week_stories()
    if not stories:
        log.warning("No daily posts found in the past 7 days — skipping weekly roundup.")
        return

    log.info("Generating roundup intro with Claude Haiku...")
    intro = generate_roundup_intro(stories, client)

    week_end   = str(today)
    week_start = str(today - timedelta(days=6))

    POSTS_DIR.mkdir(exist_ok=True)
    post_path = POSTS_DIR / f"{week_end}-week-in-ai.md"
    content   = build_roundup_post(stories, intro, week_start, week_end)
    post_path.write_text(content, encoding="utf-8")
    log.info(f"Weekly roundup written: {post_path}")


if __name__ == "__main__":
    main()
