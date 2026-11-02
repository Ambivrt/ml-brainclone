"""
social-scan.py — Playwright-based morning scan of X, LinkedIn, Reddit, Gmail, and Teams.

Runs as nightly step (Step 0e) before the morning brief.
Outputs structured data to .data/social-scan.txt for the morning brief's
AI landscape section.
Reddit digest saved separately to 00-inbox/reddit-YYYY-MM-DD.md (for distillation).

Uses a persistent browser profile, run headless. Headless Edge must be given
a normal user agent: with "HeadlessChrome" in it Reddit answers 403 and X shows
no timeline. Headed mode gave pages that never reached domcontentloaded during
the night. Navigation now waits for "commit" and then for the service's own
selector, with one retry per page.

A read failure is never a quiet day: a service that threw, or a search service
that returned zero hits on every search, is reported as COULD NOT BE READ in
the output, not as an empty list.
"""

import json
import sys
import time
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
    "ArtificialInteligence",  # one "l": that is how the sub is spelled. The two-l spelling gave 0 posts
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
TIMEOUT_MS = 15000            # kept for older callers/tests

NAV_COMMIT_TIMEOUT_MS = 30000  # goto only waits for commit, the page hydrates afterwards
READY_TIMEOUT_MS = 30000       # wait for the service's own selector after commit
NAV_ATTEMPTS = 2               # one retry per page before it counts as a failure
SCAN_BUDGET_S = 420            # cap on the scanning itself, so the caller's timeout is not hit
FALLBACK_EDGE_MAJOR = "156"    # used when the Edge version cannot be read
_SCAN_STARTED = time.monotonic()

# Read failures per service during this run. A failure is never a quiet day:
# a service that threw every night was once read as "0 chats".
SCAN_ERRORS: dict[str, str] = {}
SCAN_STATUS: dict[str, str] = {}   # "ok" or "FAILED", filled by finalize_status


def _mark_failed(service: str, err) -> None:
    """Register a read failure for the service (the first line of the error is enough)."""
    msg = str(err).strip().splitlines()[0][:120] if str(err).strip() else type(err).__name__
    SCAN_ERRORS.setdefault(service, msg)


def finalize_status(service: str, results: list, searches: int = 0) -> str:
    """Set the service's final status: ok or FAILED.

    FAILED when the service threw and nothing came back, or when a search
    service (searches > 0) returned zero hits on every single search. That does
    not happen on an ordinary day, it is a broken scraper."""
    if not results and (service in SCAN_ERRORS or searches > 0):
        SCAN_STATUS[service] = "FAILED"
        SCAN_ERRORS.setdefault(service, f"zero hits on {searches} searches")
    else:
        SCAN_STATUS[service] = "ok"
    return SCAN_STATUS[service]


def _empty_line(service: str, default: str) -> str:
    if SCAN_STATUS.get(service) == "FAILED":
        return f"(COULD NOT BE READ: {SCAN_ERRORS.get(service, 'unknown error')}. Not the same as empty)"
    return default


def budget_left() -> bool:
    """False once the scan has used its time budget."""
    return (time.monotonic() - _SCAN_STARTED) < SCAN_BUDGET_S


def load_ready(page, url: str, ready_selector: str,
               ready_timeout_ms: int = READY_TIMEOUT_MS,
               attempts: int = NAV_ATTEMPTS) -> bool:
    """Navigate and wait until the service has shown up. True = the selector
    appeared, False = the page loaded but the selector never came (empty list or
    changed layout, the caller reads what is there). Raises only when the
    navigation itself fails after every attempt.

    wait_until="commit" instead of domcontentloaded: social feeds, Teams and
    Outlook reach domcontentloaded late or never under load and gave 15-25 s
    timeouts per search."""
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, timeout=NAV_COMMIT_TIMEOUT_MS, wait_until="commit")
        except Exception as e:  # the navigation itself failed, try again
            last_err = e
            log.warning("Navigation to %s failed (attempt %d/%d): %s",
                        url[:70], attempt, attempts, str(e).splitlines()[0][:80])
            continue
        deadline = time.monotonic() + ready_timeout_ms / 1000
        while True:
            try:
                if page.query_selector(ready_selector):
                    page.wait_for_timeout(800)  # let the rest of the list render
                    return True
            except Exception:
                pass  # the context changes during a redirect, try again
            if time.monotonic() >= deadline:
                break
            page.wait_for_timeout(500)
        log.info("Selector never appeared within %d s: %s", ready_timeout_ms // 1000, url[:70])
        return False
    raise last_err if last_err else RuntimeError(f"navigation failed: {url}")


def headless_user_agent(pw) -> str:
    """Edge's normal user agent without "Headless". The version is read from a
    short-lived headless start that never touches the profile."""
    major = FALLBACK_EDGE_MAJOR
    try:
        browser = pw.chromium.launch(channel="msedge", headless=True, timeout=30000)
        try:
            major = browser.version.split(".")[0] or major
        finally:
            browser.close()
    except Exception as e:
        log.warning("Could not read the Edge version, using %s: %s", major, str(e)[:80])
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0")


def launch_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        user_agent = headless_user_agent(pw)
        context = pw.chromium.launch_persistent_context(
            PROFILE_PATH,
            channel="msedge",
            headless=True,
            user_agent=user_agent,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-background-timer-throttling",
                  "--disable-renderer-backgrounding"],
            viewport={"width": 1280, "height": 900},
            timeout=30000,
        )
    except Exception:
        try:
            pw.stop()
        except Exception:
            pass
        raise
    return pw, context


FOCUS_FILE = OUTPUT_DIR / "brief-focus.json"


def load_focus() -> dict:
    """A one-off focus for today's brief, written by a session or the bot:
    {"date": "YYYY-MM-DD", "x": [...], "linkedin": [...]}. Only today's counts."""
    try:
        d = json.loads(FOCUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get("date") == datetime.now().strftime("%Y-%m-%d") else {}


def merge_terms(base: list, extra: list) -> list:
    """The standing terms plus today's focus, focus first, no duplicates."""
    seen, out = set(), []
    for t in list(extra or []) + list(base):
        k = str(t).strip().lower()
        if k and k not in seen:
            seen.add(k); out.append(str(t).strip())
    return out


def scan_x(context, search_terms):
    results = []
    page = context.new_page()
    try:
        for term in search_terms:
            if not budget_left():
                _mark_failed("X", RuntimeError("time budget used up"))
                break
            log.info("X: searching '%s'", term)
            try:
                url = f"https://x.com/search?q={quote(term)}&f=top"
                load_ready(page, url, 'article[data-testid="tweet"]')

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
                _mark_failed("X", e)
                continue
    finally:
        page.close()
    return results


def scan_linkedin(context, search_terms):
    results = []
    page = context.new_page()
    try:
        for term in search_terms:
            if not budget_left():
                _mark_failed("LinkedIn", RuntimeError("time budget used up"))
                break
            log.info("LinkedIn: searching '%s'", term)
            try:
                url = f"https://www.linkedin.com/search/results/content/?keywords={quote(term)}&sortBy=%22date_posted%22"
                load_ready(page, url, '[data-testid="expandable-text-box"], .feed-shared-update-v2')

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
                _mark_failed("LinkedIn", e)
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
            if not budget_left():
                _mark_failed("Reddit", RuntimeError("time budget used up"))
                break
            log.info("Reddit: r/%s", sub)
            try:
                load_ready(page, f"https://old.reddit.com/r/{sub}/hot/",
                           '#siteTable > .thing.link', ready_timeout_ms=20000)

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
                _mark_failed("Reddit", e)
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
        load_ready(page, "https://mail.google.com/mail/u/0/#inbox",
                   '[role="main"]', ready_timeout_ms=25000)
        page.wait_for_timeout(2500)  # the rows are drawn after [role=main]

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
        _mark_failed("Gmail", e)
    finally:
        page.close()
    return results


TEAMS_READY = '[data-tid="all-phased-rendering-complete"]'
TEAMS_CHAT_JS = """() => {
    const out = [];
    const items = document.querySelectorAll('[role="treeitem"]');
    for (const it of items) {
        const title = it.querySelector('[id^="title-chat-list-item"]');
        if (!title) continue;  // the headings (Chats, Copilot) have no chat title
        const prev = it.querySelector('[id^="message-preview-chat-list-item"]');
        const time = it.querySelector('[id^="time-chat-list-item"]');
        const label = (it.getAttribute('aria-labelledby') || '') + ' ' + (it.className || '');
        out.push({
            name: (title.textContent || '').trim(),
            preview: prev ? (prev.textContent || '').trim() : '',
            time: time ? (time.textContent || '').trim() : '',
            unread: /unread/i.test(label) || !!it.querySelector('[id*="unread" i]'),
        });
    }
    return out;
}"""


def scan_teams(context):
    """Scrape recent Teams chats (titles, previews when the list shows them).

    Teams v2 loads the list after 30-40 s and opens in Chat already. An earlier
    version waited 6 s and clicked a Chat button: it failed every night. Now it
    waits for Teams' own ready signal. The compact chat list shows names only,
    no preview."""
    results = []
    page = context.new_page()
    try:
        log.info("Teams: opening chat")
        load_ready(page, "https://teams.microsoft.com/v2/", TEAMS_READY,
                   ready_timeout_ms=75000)
        page.wait_for_timeout(2000)

        chats = page.evaluate(TEAMS_CHAT_JS) or []
        log.info("Teams: %d chats visible", len(chats))

        for chat in chats[:10]:
            name = chat.get("name") or "unknown"
            preview = chat.get("preview") or "(no preview in the chat list)"
            results.append({
                "platform": "Teams",
                "author": name,
                "text": preview[:500],
                "time": chat.get("time", ""),
                "unread": bool(chat.get("unread")),
            })
        if not chats:
            raise RuntimeError("Teams: the chat list was not there after the wait")
    except Exception as e:
        log.warning("Teams scan failed: %s", e)
        _mark_failed("Teams", e)
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
    failed = [k for k, v in SCAN_STATUS.items() if v == "FAILED"]
    lines = [
        f"# Social Scan — {TODAY}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        f"# {counts}",
        f"# Could not be read: {', '.join(failed) if failed else 'none'}",
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
        lines.append(_empty_line("X", "(no results)"))
        lines.append("")

    lines.append("## LinkedIn")
    lines.append("")
    if linkedin_results:
        for r in linkedin_results:
            lines.append(f"### [{r['search']}] {r['author']}")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append(_empty_line("LinkedIn", "(no results)"))
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
        lines.append(_empty_line("Reddit", "(no results)"))
        lines.append("")

    lines.append("## Gmail (unread)")
    lines.append("")
    if gmail_results:
        for r in gmail_results:
            lines.append(f"### {r['author']}")
            lines.append(r["text"])
            lines.append("")
    else:
        lines.append(_empty_line("Gmail", "(no unread emails)"))
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
        lines.append(_empty_line("Teams", "(no chats)"))
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

    global _SCAN_STARTED
    _SCAN_STARTED = time.monotonic()

    try:
        pw, context = launch_browser()
    except Exception as e:
        log.error("Could not start Playwright: %s", e)
        write_output([], [], [], [], [])
        return 1

    try:
        focus = load_focus()
        x_terms = merge_terms(X_SEARCHES, focus.get("x", []))
        x_results = scan_x(context, x_terms)
        log.info("X: %d posts (%s)", len(x_results), finalize_status("X", x_results, len(x_terms)))

        li_terms = merge_terms(LINKEDIN_SEARCHES, focus.get("linkedin", []))
        linkedin_results = scan_linkedin(context, li_terms)
        log.info("LinkedIn: %d posts (%s)", len(linkedin_results),
                 finalize_status("LinkedIn", linkedin_results, len(li_terms)))

        all_subs = REDDIT_SUBREDDITS_P1 + REDDIT_SUBREDDITS_P2
        reddit_results = scan_reddit(context, all_subs)
        log.info("Reddit: %d posts (%s)", len(reddit_results),
                 finalize_status("Reddit", reddit_results, len(all_subs)))

        gmail_results = scan_gmail(context)
        log.info("Gmail: %d unread (%s)", len(gmail_results), finalize_status("Gmail", gmail_results))

        teams_results = scan_teams(context)
        log.info("Teams: %d chats (%s)", len(teams_results), finalize_status("Teams", teams_results))

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
