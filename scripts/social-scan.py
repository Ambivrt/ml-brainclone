"""
social-scan.py — Playwright-based morning scan of X, LinkedIn, Reddit, Gmail, and Teams.

Runs as nightly step (Step 0e) before the morning brief.
Outputs structured data to .data/social-scan.txt for the morning brief's
AI landscape section.
Reddit digest saved separately to 00-inbox/reddit-YYYY-MM-DD.md (for distillation).

Uses a persistent browser profile (headed mode, never headless).
"""

import sys
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- Configuration (customize these) ---
PROFILE_PATH = r"YOUR_PLAYWRIGHT_PROFILE_PATH"
OUTPUT_DIR = Path(r"YOUR_VAULT/03-projects/ml-brainclone/nattskift/.data")
OUTPUT_FILE = OUTPUT_DIR / "social-scan.txt"
INBOX_DIR = Path(r"YOUR_VAULT/00-inbox")
TODAY = datetime.now().strftime("%Y-%m-%d")

X_SEARCHES = [
    "agentic AI",
    "OpenAI agents",
    "Gemini AI agents",
    "Claude Code",
    "AI enterprise governance",
]

LINKEDIN_SEARCHES = [
    "agentic AI enterprise",
    "AI agent consulting",
    "AI transformation 2026",
]

REDDIT_SUBREDDITS_P1 = [
    "MachineLearning",
    "LocalLLaMA",
    "ChatGPT",
    "ArtificialIntelligence",
    "ClaudeAI",
]

REDDIT_SUBREDDITS_P2 = [
    "StableDiffusion",
    "midjourney",
    "Entrepreneur",
    "productivity",
]

MAX_POSTS_PER_SEARCH = 5
MAX_REDDIT_POSTS_PER_SUB = 8
TIMEOUT_MS = 15000


def launch_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        PROFILE_PATH,
        channel="msedge",
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 900},
        timeout=30000,
    )
    return pw, context


def scan_x(context, search_terms):
    results = []
    page = context.new_page()
    try:
        for term in search_terms:
            log.info("X: searching '%s'", term)
            try:
                url = f"https://x.com/search?q={quote(term)}&f=top"
                page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                posts = page.query_selector_all('article[data-testid="tweet"]')
                for post in posts[:MAX_POSTS_PER_SEARCH]:
                    try:
                        text_el = post.query_selector('[data-testid="tweetText"]')
                        text = text_el.inner_text() if text_el else ""
                        if not text or len(text) < 20:
                            continue

                        author_el = post.query_selector('a[role="link"] span')
                        author = author_el.inner_text() if author_el else "unknown"

                        time_el = post.query_selector("time")
                        timestamp = time_el.get_attribute("datetime") if time_el else ""

                        results.append({
                            "platform": "X",
                            "search": term,
                            "author": author,
                            "text": text[:500],
                            "time": timestamp,
                        })
                    except Exception:
                        continue
            except Exception as e:
                log.warning("X search '%s' failed: %s", term, e)
                continue
    finally:
        page.close()
    return results


def scan_linkedin(context, search_terms):
    results = []
    page = context.new_page()
    try:
        for term in search_terms:
            log.info("LinkedIn: searching '%s'", term)
            try:
                url = f"https://www.linkedin.com/search/results/content/?keywords={quote(term)}&sortBy=%22date_posted%22"
                page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)

                posts = page.query_selector_all('.feed-shared-update-v2')
                if not posts:
                    posts = page.query_selector_all('[data-urn]')

                for post in posts[:MAX_POSTS_PER_SEARCH]:
                    try:
                        text_el = post.query_selector('.feed-shared-text__text-view, .update-components-text')
                        text = text_el.inner_text() if text_el else ""
                        if not text or len(text) < 30:
                            continue

                        author_el = post.query_selector('.update-components-actor__name span, .feed-shared-actor__name span')
                        author = author_el.inner_text() if author_el else "unknown"

                        results.append({
                            "platform": "LinkedIn",
                            "search": term,
                            "author": author,
                            "text": text[:500],
                            "time": "",
                        })
                    except Exception:
                        continue
            except Exception as e:
                log.warning("LinkedIn search '%s' failed: %s", term, e)
                continue
    finally:
        page.close()
    return results


def scan_reddit(context, subreddits):
    """Scrape hot posts from subreddits via old.reddit.com."""
    results = []
    page = context.new_page()
    try:
        for sub in subreddits:
            log.info("Reddit: r/%s", sub)
            try:
                page.goto(f"https://old.reddit.com/r/{sub}/hot/",
                          timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                entries = page.query_selector_all('#siteTable > .thing.link')
                for entry in entries[:MAX_REDDIT_POSTS_PER_SUB]:
                    try:
                        title_el = entry.query_selector('a.title')
                        title = title_el.inner_text() if title_el else ""
                        href = title_el.get_attribute("href") if title_el else ""
                        if href and href.startswith("/"):
                            href = f"https://old.reddit.com{href}"

                        score = entry.get_attribute("data-score") or "0"
                        try:
                            score_int = int(score)
                        except ValueError:
                            score_int = 0

                        comments_el = entry.query_selector("a.comments")
                        comments_text = comments_el.inner_text() if comments_el else "0 comments"

                        if not title or title.lower().startswith("promoted"):
                            continue

                        results.append({
                            "platform": "Reddit",
                            "subreddit": f"r/{sub}",
                            "title": title[:300],
                            "url": href,
                            "score": score_int,
                            "comments": comments_text,
                            "text": title[:300],
                            "time": "",
                        })
                    except Exception:
                        continue
            except Exception as e:
                log.warning("Reddit r/%s failed: %s", sub, e)
                continue
    finally:
        page.close()
    return results


def scan_gmail(context):
    """Scrape unread emails from Gmail inbox."""
    results = []
    page = context.new_page()
    try:
        log.info("Gmail: opening inbox")
        page.goto("https://mail.google.com/mail/u/0/#inbox",
                   timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        rows = page.query_selector_all("tr.zE")
        log.info("Gmail: %d unread emails found", len(rows))

        for row in rows[:10]:
            try:
                sender_el = row.query_selector("[email]")
                sender = sender_el.get_attribute("email") if sender_el else ""
                if not sender:
                    name_el = row.query_selector(".yW span")
                    sender = name_el.inner_text() if name_el else "unknown"

                subject_el = row.query_selector(".bog span, .bqe")
                subject = subject_el.inner_text() if subject_el else ""

                snippet_el = row.query_selector(".y2")
                snippet = ""
                if snippet_el:
                    snippet = snippet_el.inner_text().lstrip(" - ")

                if not subject:
                    continue

                results.append({
                    "platform": "Gmail",
                    "author": sender,
                    "text": f"{subject}\n{snippet}"[:500],
                    "time": "",
                })
            except Exception:
                continue
    except Exception as e:
        log.warning("Gmail scan failed: %s", e)
    finally:
        page.close()
    return results


def scan_teams(context):
    """Scrape recent Teams chat messages."""
    results = []
    page = context.new_page()
    try:
        log.info("Teams: opening chat")
        page.goto("https://teams.microsoft.com/v2/",
                   timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        page.click('button:has-text("Chat"), [data-tid="app-bar-Chat"]',
                    timeout=5000)
        page.wait_for_timeout(3000)

        chat_items = page.query_selector_all(
            '[data-tid="chat-list-item"], '
            '[role="treeitem"], '
            '.chat-list-item'
        )
        log.info("Teams: %d chats visible", len(chat_items))

        for item in chat_items[:10]:
            try:
                name_el = item.query_selector(
                    '[data-tid="chat-list-item-title"], '
                    '.chat-title, '
                    'span[class*="title"]'
                )
                name = name_el.inner_text() if name_el else "unknown"

                preview_el = item.query_selector(
                    '[data-tid="chat-list-item-message"], '
                    '.chat-last-message, '
                    'span[class*="message"]'
                )
                preview = preview_el.inner_text() if preview_el else ""

                time_el = item.query_selector(
                    '[data-tid="chat-list-item-timestamp"], '
                    '.chat-time, '
                    'span[class*="timestamp"]'
                )
                time_str = time_el.inner_text() if time_el else ""

                unread_el = item.query_selector(
                    '[data-tid="unread-count"], '
                    '.unread-count, '
                    '[class*="unread"]'
                )
                is_unread = unread_el is not None

                if not preview:
                    continue

                results.append({
                    "platform": "Teams",
                    "author": name,
                    "text": preview[:500],
                    "time": time_str,
                    "unread": is_unread,
                })
            except Exception:
                continue
    except Exception as e:
        log.warning("Teams scan failed: %s", e)
    finally:
        page.close()
    return results


def write_output(x_results, linkedin_results, reddit_results, gmail_results, teams_results):
    """Write social-scan.txt with all sources."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts = (
        f"X: {len(x_results)} | LinkedIn: {len(linkedin_results)} | "
        f"Reddit: {len(reddit_results)} | Gmail: {len(gmail_results)} | "
        f"Teams: {len(teams_results)}"
    )
    lines = [
        f"# Social Scan — {TODAY}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        f"# {counts}",
        "",
    ]

    lines.append("## X (Twitter)")
    lines.append("")
    if x_results:
        for r in x_results:
            ts = r["time"][:10] if r.get("time") else "unknown"
            lines.append(f"### [{r['search']}] @{r['author']} ({ts})")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append("(no results)")
        lines.append("")

    lines.append("## LinkedIn")
    lines.append("")
    if linkedin_results:
        for r in linkedin_results:
            lines.append(f"### [{r['search']}] {r['author']}")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append("(no results)")
        lines.append("")

    lines.append("## Reddit")
    lines.append("")
    if reddit_results:
        top = sorted(reddit_results, key=lambda r: r.get("score", 0), reverse=True)
        for r in top[:20]:
            lines.append(f"### [{r['subreddit']}] {r['title']} (score: {r['score']}, {r['comments']})")
            if r.get("url"):
                lines.append(r["url"])
            lines.append("")
    else:
        lines.append("(no results)")
        lines.append("")

    lines.append("## Gmail (unread)")
    lines.append("")
    if gmail_results:
        for r in gmail_results:
            lines.append(f"### {r['author']}")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append("(no unread emails)")
        lines.append("")

    lines.append("## Teams")
    lines.append("")
    if teams_results:
        for r in teams_results:
            unread_tag = " [UNREAD]" if r.get("unread") else ""
            lines.append(f"### {r['author']}{unread_tag} ({r.get('time', '')})")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append("(no chats)")
        lines.append("")

    _atomic_write(OUTPUT_FILE, "\n".join(lines))
    log.info("Output written: %s (%d lines)", OUTPUT_FILE, len(lines))


def write_reddit_digest(reddit_results):
    """Write reddit-YYYY-MM-DD.md to inbox (for distillation)."""
    if not reddit_results:
        return

    top = sorted(reddit_results, key=lambda r: r.get("score", 0), reverse=True)
    significant = [r for r in top if r.get("score", 0) >= 50]
    if not significant:
        significant = top[:10]

    lines = [
        "---",
        "tags: [type/reddit-digest, generated/nightly]",
        "status: draft",
        f"created: {TODAY}",
        "privacy: 1",
        "---",
        "",
        f"# Reddit digest — {TODAY}",
        "",
        "## Top stories",
        "",
    ]

    for r in significant[:15]:
        url = r.get("url", "")
        title = r.get("title", "")
        sub = r.get("subreddit", "")
        score = r.get("score", 0)
        comments = r.get("comments", "")

        if url:
            lines.append(f"### [{title}]({url})")
        else:
            lines.append(f"### {title}")
        lines.append(f"**Subreddit:** {sub} | **Score:** {score} | **Comments:** {comments}")
        lines.append("")

    remaining = [r for r in top if r not in significant][:10]
    if remaining:
        lines.append("## Relevant threads")
        lines.append("")
        for r in remaining:
            url = r.get("url", "")
            title = r.get("title", "")
            sub = r.get("subreddit", "")
            if url:
                lines.append(f"- [{title}]({url}) ({sub})")
            else:
                lines.append(f"- {title} ({sub})")
        lines.append("")

    digest_file = INBOX_DIR / f"reddit-{TODAY}.md"
    _atomic_write(digest_file, "\n".join(lines))
    log.info("Reddit digest written: %s (%d posts)", digest_file, len(significant))


def _atomic_write(target: Path, content: str):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(target)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def main():
    log.info("Social scan starting — %s", TODAY)
    log.info("Sources: X, LinkedIn, Reddit, Gmail, Teams")

    try:
        pw, context = launch_browser()
    except Exception as e:
        log.error("Could not start Playwright: %s", e)
        write_output([], [], [], [], [])
        return 1

    try:
        x_results = scan_x(context, X_SEARCHES)
        log.info("X: %d posts", len(x_results))

        linkedin_results = scan_linkedin(context, LINKEDIN_SEARCHES)
        log.info("LinkedIn: %d posts", len(linkedin_results))

        all_subs = REDDIT_SUBREDDITS_P1 + REDDIT_SUBREDDITS_P2
        reddit_results = scan_reddit(context, all_subs)
        log.info("Reddit: %d posts", len(reddit_results))

        gmail_results = scan_gmail(context)
        log.info("Gmail: %d unread", len(gmail_results))

        teams_results = scan_teams(context)
        log.info("Teams: %d chats", len(teams_results))

        write_output(x_results, linkedin_results, reddit_results, gmail_results, teams_results)
        write_reddit_digest(reddit_results)
    except Exception as e:
        log.error("Scan error: %s", e)
        write_output([], [], [], [], [])
        return 1
    finally:
        context.close()
        pw.stop()

    log.info("Social scan complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
