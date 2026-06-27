"""Contact intelligence: build a contact graph from email history.

For each person the user has corresponded with, aggregate how often they emailed
each other, when, and what about (topics extracted from subjects via Claude
Haiku). The result powers contact context injection in chat and the Contacts
section of the Connections panel.
"""

import json
import logging
import re
from email.utils import parseaddr

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from services import provider_service, vector_service

logger = logging.getLogger(__name__)

# How many contacts to send to Claude per topic-extraction call.
TOPIC_BATCH_SIZE = 10
# How many recent subjects per contact to feed the topic extractor.
SUBJECTS_PER_CONTACT = 12


def _split_addr(raw: str) -> tuple[str, str]:
    """Parse ``"Name <a@b.com>"`` into ``(display_name, lowercased_email)``."""
    name, addr = parseaddr(raw or "")
    return name.strip(), addr.strip().lower()


async def _extract_topics(contacts: list[dict], db: AsyncSession) -> dict[str, list[str]]:
    """Ask the active provider's classify model for 1-4 topics per contact.

    Batched: one call per ``TOPIC_BATCH_SIZE`` contacts. Returns a map of
    ``email_address -> [topics]``. Degrades to empty topics on any failure —
    topics are a nice-to-have, never block the graph build.
    """
    topics_by_email: dict[str, list[str]] = {}

    for start in range(0, len(contacts), TOPIC_BATCH_SIZE):
        batch = contacts[start : start + TOPIC_BATCH_SIZE]
        lines = []
        for contact in batch:
            subjects = " | ".join(contact["subjects"][:SUBJECTS_PER_CONTACT])
            lines.append(f'{contact["email_address"]} :: {subjects}')

        prompt = (
            "For each contact below, list 1-4 short lowercase topic tags describing "
            "what they email about, inferred from their email subjects.\n"
            "Return ONLY a JSON object mapping each email address to an array of "
            "topic strings, no other text:\n"
            '{"a@b.com": ["housing", "lease"], ...}\n\n'
            "Contacts (email :: subjects):\n" + "\n".join(lines)
        )
        try:
            raw = await provider_service.call_classify(db, prompt, max_tokens=1000)
            obj_start, obj_end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[obj_start : obj_end + 1]) if obj_start != -1 else {}
        except Exception:  # noqa: BLE001
            logger.exception("Topic extraction failed for a contact batch")
            data = {}

        for email_addr, topics in data.items():
            if isinstance(topics, list):
                topics_by_email[email_addr.lower()] = [str(t) for t in topics][:4]

    return topics_by_email


async def build_contact_graph(account_id: int, db: AsyncSession) -> dict:
    """Aggregate an account's email history into the contacts table.

    Returns ``{contacts}`` — the number of contacts upserted.
    """
    owner_row = await db.execute(
        text("SELECT email FROM gmail_accounts WHERE id = :id"),
        {"id": account_id},
    )
    owner_email = (owner_row.scalar() or "").lower()

    # Received: emails FROM each address.
    received = await db.execute(
        text(
            """
            SELECT from_address, subject, received_at
            FROM emails
            WHERE account_id = :account_id AND from_address IS NOT NULL
            """
        ),
        {"account_id": account_id},
    )

    # contacts keyed by lowercased email address.
    contacts: dict[str, dict] = {}

    def _touch(display: str, email_addr: str) -> dict | None:
        if not email_addr or email_addr == owner_email:
            return None
        entry = contacts.setdefault(
            email_addr,
            {
                "email_address": email_addr,
                "display_name": display or None,
                "received_count": 0,
                "sent_count": 0,
                "first_contacted": None,
                "last_contacted": None,
                "subjects": [],
            },
        )
        if display and not entry["display_name"]:
            entry["display_name"] = display
        return entry

    for row in received.mappings().all():
        display, addr = _split_addr(row["from_address"])
        entry = _touch(display, addr)
        if entry is None:
            continue
        entry["received_count"] += 1
        when = row["received_at"]
        if when:
            if entry["first_contacted"] is None or when < entry["first_contacted"]:
                entry["first_contacted"] = when
            if entry["last_contacted"] is None or when > entry["last_contacted"]:
                entry["last_contacted"] = when
        if row["subject"]:
            entry["subjects"].append(row["subject"])

    # Sent: emails the owner sent, counted against each recipient.
    sent = await db.execute(
        text(
            """
            SELECT unnest(to_addresses) AS recipient, received_at
            FROM emails
            WHERE account_id = :account_id AND from_address ILIKE :owner
            """
        ),
        {"account_id": account_id, "owner": owner_email},
    )
    for row in sent.mappings().all():
        display, addr = _split_addr(row["recipient"])
        entry = _touch(display, addr)
        if entry is None:
            continue
        entry["sent_count"] += 1
        when = row["received_at"]
        if when:
            if entry["last_contacted"] is None or when > entry["last_contacted"]:
                entry["last_contacted"] = when

    if not contacts:
        return {"contacts": 0}

    contact_list = list(contacts.values())
    topics_by_email = await _extract_topics(contact_list, db)

    embed_config = await vector_service.get_embedding_config(db)
    expected_dim = embed_config["dim"]
    can_embed = embed_config["provider"] != "voyage" or bool(vector_service.settings.voyage_api_key)
    for entry in contact_list:
        entry["topics"] = topics_by_email.get(entry["email_address"], [])

    # Embed each contact for similarity search (best-effort, batched).
    embeddings: list[list[float] | None] = [None] * len(contact_list)
    if can_embed:
        summaries = [
            f"{c['display_name'] or c['email_address']} {c['email_address']} "
            f"topics: {', '.join(c['topics'])} "
            f"last contacted: {c['last_contacted'].date() if c['last_contacted'] else 'unknown'}"
            for c in contact_list
        ]
        try:
            embeddings = await vector_service.embed_texts(summaries, db)
        except Exception:  # noqa: BLE001
            logger.exception("Contact embedding failed — storing contacts without vectors")
            embeddings = [None] * len(contact_list)

    upserted = 0
    for entry, embedding in zip(contact_list, embeddings):
        # Step 1: upsert all scalar fields — asyncpg cannot infer the type of a
        # pgvector parameter in a CASE expression, so embedding is handled separately.
        await db.execute(
            text(
                """
                INSERT INTO contacts
                    (email_address, display_name, email_count, sent_count,
                     received_count, first_contacted, last_contacted, topics)
                VALUES
                    (:email_address, :display_name, :email_count, :sent_count,
                     :received_count, :first_contacted, :last_contacted, :topics)
                ON CONFLICT (email_address) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, contacts.display_name),
                    email_count = EXCLUDED.email_count,
                    sent_count = EXCLUDED.sent_count,
                    received_count = EXCLUDED.received_count,
                    first_contacted = EXCLUDED.first_contacted,
                    last_contacted = EXCLUDED.last_contacted,
                    topics = EXCLUDED.topics
                """
            ),
            {
                "email_address": entry["email_address"],
                "display_name": entry["display_name"],
                "email_count": entry["received_count"] + entry["sent_count"],
                "sent_count": entry["sent_count"],
                "received_count": entry["received_count"],
                "first_contacted": entry["first_contacted"],
                "last_contacted": entry["last_contacted"],
                "topics": entry["topics"],
            },
        )
        await db.commit()

        # Step 2: interpolate the vector string directly — asyncpg cannot parse
        # the :param::vector syntax, so we embed the sanitized literal in the SQL.
        if embedding is not None and len(embedding) == expected_dim:
            literal = vector_service.to_pgvector(embedding)
            safe_vec = literal.replace("'", "")
            await db.execute(
                text(f"UPDATE contacts SET embedding = '{safe_vec}'::vector WHERE email_address = :email_address"),
                {"email_address": entry["email_address"]},
            )
            await db.commit()

        upserted += 1

    logger.info("Built contact graph for account %s: %s contacts", account_id, upserted)
    return {"contacts": upserted}


async def run_build_contact_graph_background(account_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await build_contact_graph(account_id, db)
        except Exception:  # noqa: BLE001
            logger.exception("Background contact graph build failed for account %s", account_id)


async def list_contacts(db: AsyncSession, limit: int = 200) -> list[dict]:
    """Return contacts sorted by total email volume, most active first."""
    result = await db.execute(
        text(
            """
            SELECT email_address, display_name, email_count, sent_count,
                   received_count, first_contacted, last_contacted, topics
            FROM contacts
            ORDER BY email_count DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]


async def search_contacts(db: AsyncSession, query: str, limit: int = 25) -> list[dict]:
    """Search contacts by name or email substring."""
    result = await db.execute(
        text(
            """
            SELECT email_address, display_name, email_count, sent_count,
                   received_count, first_contacted, last_contacted, topics
            FROM contacts
            WHERE email_address ILIKE :q OR display_name ILIKE :q
            ORDER BY email_count DESC
            LIMIT :limit
            """
        ),
        {"q": f"%{query}%", "limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]


_EXCLUDE_SINGLES = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "June", "July", "August",
    "September", "October", "November", "December",
    "Gmail", "Google", "Obsidian", "Meridian", "Claude",
    "Today", "Tomorrow", "Yesterday", "This", "That", "The", "Here",
    "There", "Some", "Just", "Also", "With", "From", "About", "Into",
    "What", "When", "Where", "Draft", "Email", "Send", "Write", "Reply",
    "Can", "Could", "Would", "Should", "Have", "Will", "Help",
}


def _extract_name_candidates(query: str) -> list[str]:
    """Extract likely person name tokens from a chat query.

    Returns full "First Last" names and single capitalized words (min 3 chars),
    filtering out common words, days, months, and service names. This keeps
    false positives from words like "Draft" or "Monday" out of contact lookups.
    """
    full_names = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query)
    single_names = re.findall(r"\b([A-Z][a-z]{2,})\b", query)
    seen = set(full_names)
    candidates = list(full_names)
    for name in single_names:
        if name not in seen and name not in _EXCLUDE_SINGLES:
            candidates.append(name)
            seen.add(name)
    return candidates


async def get_contact_context(query: str, db: AsyncSession) -> str:
    """If the chat query mentions a known contact, return a one-line summary block.

    Extracts capitalized name candidates from the query and searches contacts by
    partial ILIKE match. Returns an empty string when nothing matches.
    """
    candidates = _extract_name_candidates(query)
    if not candidates:
        return ""

    matches: dict[str, dict] = {}
    for term in candidates[:6]:
        rows = await db.execute(
            text(
                """
                SELECT email_address, display_name, email_count,
                       last_contacted, topics
                FROM contacts
                WHERE display_name ILIKE :q OR email_address ILIKE :q
                ORDER BY email_count DESC
                LIMIT 3
                """
            ),
            {"q": f"%{term}%"},
        )
        for row in rows.mappings().all():
            matches[row["email_address"]] = dict(row)

    if not matches:
        return ""

    lines = ["KNOWN CONTACTS:"]
    for contact in list(matches.values())[:5]:
        name = contact["display_name"] or contact["email_address"]
        last = contact["last_contacted"].strftime("%B %Y") if contact["last_contacted"] else "unknown"
        topics = ", ".join(contact["topics"] or []) or "n/a"
        lines.append(
            f"- {name} ({contact['email_address']}): {contact['email_count']} emails, "
            f"last contacted {last}, topics: {topics}"
        )
    return "\n".join(lines)
