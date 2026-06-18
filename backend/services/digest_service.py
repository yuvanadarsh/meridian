"""Daily digest: calendar + email summary + AI-fetched news + stock watchlist.

Each section is built independently and degrades to a short placeholder on
failure so a single flaky source never sinks the whole brief. The assembled
``full_text`` is written for the voice — plain, spoken language with no markdown.
"""

import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services import calendar_service, claude_service, gmail_service

logger = logging.getLogger(__name__)

# Cheaper model for news search + final assembly — quality is fine here.
DIGEST_MODEL = "claude-haiku-4-5-20251001"

# Tickers the user follows. Kept here (not in the DB) until a watchlist UI lands.
WATCHLIST = ["GOOGL", "MSFT", "NVDA", "AMZN", "AAPL", "ORCL", "SPY"]


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------


def _fetch_stock_summary() -> str:
    """Blocking yfinance lookups for the watchlist — run via a thread."""
    import yfinance as yf

    lines = ["Market summary:"]
    for ticker in WATCHLIST:
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            previous = info.previous_close
            change_pct = ((price - previous) / previous) * 100
            arrow = "▲" if change_pct > 0 else "▼"
            lines.append(f"{ticker}: ${price:.2f} {arrow}{abs(change_pct):.1f}%")
        except Exception:  # noqa: BLE001 — one bad ticker shouldn't break the rest
            lines.append(f"{ticker}: unavailable")
    return "\n".join(lines)


async def get_stock_summary() -> str:
    """Return a watchlist price/percent-change summary."""
    try:
        return await asyncio.to_thread(_fetch_stock_summary)
    except Exception:  # noqa: BLE001
        logger.exception("Stock summary failed")
        return "Market summary: unavailable right now."


# ---------------------------------------------------------------------------
# News (Claude web search)
# ---------------------------------------------------------------------------

_NEWS_PROMPT = """\
Search for today's top news and summarize in these categories.
For each category give 2-3 bullet points, one sentence each, no links.

Categories:
1. AI & Technology — new models, what people are building with AI, ML advances
2. US Politics — key developments today
3. Geopolitics — major international events
4. Markets — how major indices performed, any notable moves

Be factual and concise. Today's date is {today}."""


async def get_news_digest() -> str:
    """Use Claude with the web search tool to fetch and summarize current news."""
    import anthropic

    from config import get_settings

    settings = get_settings()
    today = date.today().isoformat()

    def _run() -> str:
        sync_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = sync_client.messages.create(
            model=DIGEST_MODEL,
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": _NEWS_PROMPT.format(today=today)}],
        )
        return "\n".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

    try:
        return await asyncio.to_thread(_run)
    except Exception:  # noqa: BLE001
        logger.exception("News digest failed")
        return "News is unavailable right now."


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def _format_event_time(start: datetime | None, end: datetime | None) -> str:
    if start and end:
        return f"{start.strftime('%I:%M %p').lstrip('0')} – {end.strftime('%I:%M %p').lstrip('0')}"
    if start:
        return start.strftime("%I:%M %p").lstrip("0")
    return "all day"


async def get_digest_calendar(db: AsyncSession) -> str:
    """Summarize today's and tomorrow's events across all accounts."""
    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:  # noqa: BLE001
        return "No calendar connected."
    if not accounts:
        return "No calendar connected."

    lines: list[str] = []
    for account in accounts:
        try:
            events = await calendar_service.get_upcoming(account["id"], db, days=2)
        except Exception:  # noqa: BLE001
            continue
        for event in events:
            when = _format_event_time(event["start_time"], event["end_time"])
            title = event["title"] or "(untitled)"
            lines.append(f"{when} — {title}")

    if not lines:
        return "Nothing on your calendar for today or tomorrow."
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


async def get_digest_emails(db: AsyncSession) -> str:
    """Summarize the last 24h of keep-status (action-needed) emails."""
    since = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        text(
            """
            SELECT from_address, subject
            FROM emails
            WHERE triage_status = 'keep'
              AND received_at >= (:since::timestamp - INTERVAL '24 hours')
            ORDER BY received_at DESC
            LIMIT 10
            """
        ),
        {"since": since},
    )
    rows = result.mappings().all()
    if not rows:
        return "No new emails needing attention."

    lines = [f"{len(rows)} email(s) need attention:"]
    for row in rows[:5]:
        sender = row["from_address"] or "unknown sender"
        subject = row["subject"] or "(no subject)"
        lines.append(f"- {sender}: {subject}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

_ASSEMBLY_PROMPT = """\
You are Meridian reading the user their morning brief aloud. Turn the four \
sections below into a short, natural spoken digest. No markdown, no emojis, no \
bullet symbols, no stock arrows — say "up" or "down" instead. Keep it warm and \
efficient, a few sentences per topic at most. Start with a brief greeting that \
mentions today's date.

Today is {today}.

CALENDAR:
{calendar}

EMAILS:
{emails}

NEWS:
{news}

STOCKS:
{stocks}"""


async def _assemble_full_text(
    *, calendar: str, emails: str, news: str, stocks: str
) -> str:
    """Have Claude weave the four sections into voice-ready prose."""
    today = date.today().strftime("%B %-d, %Y")
    prompt = _ASSEMBLY_PROMPT.format(
        today=today, calendar=calendar, emails=emails, news=news, stocks=stocks
    )
    try:
        reply, _ = await claude_service.chat(
            system="You assemble concise spoken daily briefs.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        return reply
    except Exception:  # noqa: BLE001
        logger.exception("Digest assembly failed — falling back to raw sections")
        return (
            f"Here is your brief for {today}. "
            f"Calendar: {calendar}. Emails: {emails}. News: {news}. Stocks: {stocks}."
        )


async def build_digest(db: AsyncSession) -> dict:
    """Assemble the full daily digest.

    DB-bound sections run sequentially — AsyncSession is not safe for concurrent
    access from multiple coroutines. Non-DB sections (news, stocks) run concurrently
    after the DB work is done.
    """
    # Sequential: shared AsyncSession cannot be used concurrently
    calendar = await get_digest_calendar(db)
    emails = await get_digest_emails(db)

    # Concurrent: both hit external APIs, no shared DB session
    news, stocks = await asyncio.gather(
        get_news_digest(),
        get_stock_summary(),
    )
    full_text = await _assemble_full_text(
        calendar=calendar, emails=emails, news=news, stocks=stocks
    )
    return {
        "calendar": calendar,
        "emails": emails,
        "news": news,
        "stocks": stocks,
        "full_text": full_text,
    }
