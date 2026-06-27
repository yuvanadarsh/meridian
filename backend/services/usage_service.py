"""Provider-aware API usage logging with cost calculation.

Every call to Anthropic, ElevenLabs, or VoyageAI goes through log_usage so
costs are visible in the UI. log_usage never raises — a failed write is
only a warning; it never breaks the main request.

Cost rates are per million tokens for LLMs/embeddings, per 1000 characters
for ElevenLabs. Unknown models fall back to the provider's 'default' row.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Cost per million tokens (or per 1000 characters for ElevenLabs).
PROVIDER_PRICING: dict[str, dict[str, dict[str, Decimal]]] = {
    "anthropic": {
        "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
        "claude-haiku-4-5-20251001": {"input": Decimal("0.80"), "output": Decimal("4.00")},
        "claude-opus-4-8": {"input": Decimal("15.00"), "output": Decimal("75.00")},
        "claude-opus-4-6": {"input": Decimal("15.00"), "output": Decimal("75.00")},
        "default": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    },
    "openai": {
        "gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
        "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
        "default": {"input": Decimal("2.50"), "output": Decimal("10.00")},
    },
    "gemini": {
        "gemini-1.5-pro": {"input": Decimal("1.25"), "output": Decimal("5.00")},
        "gemini-1.5-flash": {"input": Decimal("0.075"), "output": Decimal("0.30")},
        "gemini-2.0-flash": {"input": Decimal("0.10"), "output": Decimal("0.40")},
        "default": {"input": Decimal("1.25"), "output": Decimal("5.00")},
    },
    "deepseek": {
        "deepseek-chat": {"input": Decimal("0.14"), "output": Decimal("0.28")},
        "default": {"input": Decimal("0.14"), "output": Decimal("0.28")},
    },
    # ElevenLabs — cost per 1000 characters.
    "elevenlabs": {
        "default": {"characters": Decimal("0.30")},
    },
    # VoyageAI — cost per million tokens.
    "voyageai": {
        "voyage-3-lite": {"embed_tokens": Decimal("0.06")},
        "voyage-large-2": {"embed_tokens": Decimal("0.12")},
        "default": {"embed_tokens": Decimal("0.06")},
    },
}


def calculate_cost(provider: str, model: str, usage_type: str, units: int) -> Decimal:
    """Calculate cost in USD for a usage event. Returns 0 for unknown providers/types."""
    provider_prices = PROVIDER_PRICING.get(provider, {})
    model_prices = provider_prices.get(model, provider_prices.get("default", {}))
    if not model_prices:
        return Decimal("0")

    # Map full usage_type names to their rate key in the pricing dict.
    rate_key = {
        "input_tokens": "input",
        "output_tokens": "output",
        "embed_tokens": "embed_tokens",
        "characters": "characters",
    }.get(usage_type, usage_type)

    rate = model_prices.get(rate_key, Decimal("0"))
    if not rate:
        return Decimal("0")

    if usage_type in ("input_tokens", "output_tokens", "embed_tokens"):
        return (Decimal(str(units)) / Decimal("1000000")) * rate
    if usage_type == "characters":
        return (Decimal(str(units)) / Decimal("1000")) * rate

    return Decimal("0")


async def log_usage(
    provider: str,
    model: str,
    usage_type: str,
    units: int,
    db: AsyncSession,
) -> None:
    """Insert a usage record. Never raises — failures are logged as warnings."""
    try:
        cost = calculate_cost(provider, model, usage_type, units)
        await db.execute(
            text(
                """
                INSERT INTO usage_log (provider, model, usage_type, units, cost_usd)
                VALUES (:provider, :model, :usage_type, :units, :cost_usd)
                """
            ),
            {
                "provider": provider,
                "model": model,
                "usage_type": usage_type,
                "units": units,
                "cost_usd": float(cost),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to log usage for %s/%s/%s", provider, model, usage_type)


async def get_usage_today(db: AsyncSession) -> dict:
    """Aggregate today's usage grouped by provider, with daily and monthly totals."""
    result = await db.execute(
        text(
            """
            SELECT
                provider,
                model,
                usage_type,
                SUM(units)    AS total_units,
                SUM(cost_usd) AS total_cost
            FROM usage_log
            WHERE DATE(created_at) = CURRENT_DATE
            GROUP BY provider, model, usage_type
            ORDER BY provider, usage_type
            """
        )
    )
    rows = result.fetchall()

    by_provider: dict[str, dict] = {}
    total_cost_today = Decimal("0")

    for row in rows:
        p = row.provider
        if p not in by_provider:
            by_provider[p] = {"model": row.model, "types": {}, "total_cost": 0.0}
        by_provider[p]["types"][row.usage_type] = {
            "units": int(row.total_units or 0),
            "cost_usd": float(row.total_cost or 0),
        }
        by_provider[p]["total_cost"] = round(
            by_provider[p]["total_cost"] + float(row.total_cost or 0), 6
        )
        total_cost_today += Decimal(str(row.total_cost or 0))

    monthly_result = await db.execute(
        text(
            """
            SELECT SUM(cost_usd) AS total
            FROM usage_log
            WHERE DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
            """
        )
    )
    monthly_row = monthly_result.fetchone()
    monthly_cost = float(monthly_row.total or 0)

    # Backward-compat: surface Anthropic token counts the existing way.
    anthropic_types = by_provider.get("anthropic", {}).get("types", {})
    input_tokens = int(anthropic_types.get("input_tokens", {}).get("units", 0))
    output_tokens = int(anthropic_types.get("output_tokens", {}).get("units", 0))

    return {
        "total_tokens_today": input_tokens + output_tokens,
        "total_cost_today": float(total_cost_today),
        "total_cost_month": monthly_cost,
        "by_provider": by_provider,
    }


def _history_buckets(timeframe: str) -> tuple[list[dict], datetime]:
    """Build the ordered, fixed list of time buckets for a usage-history chart.

    Each bucket is ``{"start", "end", "label"}`` with a half-open ``[start, end)``
    window. Returns the buckets plus the earliest start (the overall query range).
    Empty buckets are kept so the chart always shows the full timeframe.
    """
    now = datetime.now()
    buckets: list[dict] = []

    if timeframe == "daily":
        # Last 24 hours in six 4-hour blocks, aligned to 4-hour boundaries.
        block_start = now.replace(minute=0, second=0, microsecond=0)
        block_start = block_start.replace(hour=(block_start.hour // 4) * 4)
        for i in range(5, -1, -1):
            start = block_start - timedelta(hours=4 * i)
            hour = start.hour % 12 or 12
            meridiem = "am" if start.hour < 12 else "pm"
            buckets.append(
                {"start": start, "end": start + timedelta(hours=4), "label": f"{hour}{meridiem}"}
            )
    elif timeframe == "monthly":
        # Last 4 weeks; Week 1 is the oldest, Week 4 the most recent.
        today = datetime.combine(date.today(), datetime.min.time())
        for i in range(4):
            start = today - timedelta(days=7 * (3 - i) + 6)
            buckets.append(
                {"start": start, "end": start + timedelta(days=7), "label": f"Week {i + 1}"}
            )
    elif timeframe == "yearly":
        # Last 12 months, oldest first, labelled by month abbreviation.
        first_of_month = datetime.combine(date.today().replace(day=1), datetime.min.time())
        months: list[datetime] = []
        cursor = first_of_month
        for _ in range(12):
            months.append(cursor)
            # Step back one month.
            year, month = cursor.year, cursor.month
            cursor = cursor.replace(
                year=year - 1 if month == 1 else year,
                month=12 if month == 1 else month - 1,
            )
        for start in reversed(months):
            year, month = start.year, start.month
            end = start.replace(
                year=year + 1 if month == 12 else year,
                month=1 if month == 12 else month + 1,
            )
            buckets.append({"start": start, "end": end, "label": start.strftime("%b")})
    else:
        # weekly (default): last 7 days, oldest first.
        today = datetime.combine(date.today(), datetime.min.time())
        for i in range(6, -1, -1):
            start = today - timedelta(days=i)
            buckets.append(
                {"start": start, "end": start + timedelta(days=1), "label": start.strftime("%a %b %-d")}
            )

    return buckets, buckets[0]["start"]


# Maps a (provider, usage_type) pair to the output field names for a data point.
_HISTORY_FIELDS = {
    ("anthropic", "input_tokens"): ("anthropic_input", "anthropic_cost"),
    ("anthropic", "output_tokens"): ("anthropic_output", "anthropic_cost"),
    ("voyageai", "embed_tokens"): ("voyageai_tokens", "voyageai_cost"),
    ("elevenlabs", "characters"): ("elevenlabs_chars", "elevenlabs_cost"),
}


async def get_usage_history(db: AsyncSession, timeframe: str = "weekly") -> dict:
    """Return usage grouped into fixed time buckets for the analytics charts."""
    buckets, range_start = _history_buckets(timeframe)

    result = await db.execute(
        text(
            """
            SELECT provider, usage_type, units, cost_usd, created_at
            FROM usage_log
            WHERE created_at >= :range_start
            """
        ),
        {"range_start": range_start},
    )
    rows = result.mappings().all()

    # Seed every bucket with zeroed fields so empty periods still render.
    data: list[dict] = []
    for bucket in buckets:
        data.append(
            {
                "label": bucket["label"],
                "anthropic_input": 0,
                "anthropic_output": 0,
                "anthropic_cost": 0.0,
                "voyageai_tokens": 0,
                "voyageai_cost": 0.0,
                "elevenlabs_chars": 0,
                "elevenlabs_cost": 0.0,
                "total_cost": 0.0,
            }
        )

    totals = {
        "total_cost": 0.0,
        "anthropic_cost": 0.0,
        "voyageai_cost": 0.0,
        "elevenlabs_cost": 0.0,
    }

    for row in rows:
        created = row["created_at"]
        # Find the bucket this row falls into.
        idx = next(
            (i for i, b in enumerate(buckets) if b["start"] <= created < b["end"]),
            None,
        )
        if idx is None:
            continue
        point = data[idx]
        units = int(row["units"] or 0)
        cost = float(row["cost_usd"] or 0)
        fields = _HISTORY_FIELDS.get((row["provider"], row["usage_type"]))
        if fields:
            unit_field, cost_field = fields
            point[unit_field] += units
            point[cost_field] = round(point[cost_field] + cost, 6)
            if cost_field in totals:
                totals[cost_field] = round(totals[cost_field] + cost, 6)
        point["total_cost"] = round(point["total_cost"] + cost, 6)
        totals["total_cost"] = round(totals["total_cost"] + cost, 6)

    return {"timeframe": timeframe, "data": data, "totals": totals}
