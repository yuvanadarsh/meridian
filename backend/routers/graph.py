"""Knowledge graph routes: the contact relationship network for the /graph page.

Nodes and edges are derived entirely from PostgreSQL — `contacts` for the people
and `email_threads.participants` for who corresponds with whom. There is no file
system involved (this replaces the old Obsidian graph view).

Addresses in `email_threads.participants` and `emails.from_address` are stored
raw as ``"Display Name <addr@host>"``. Contacts are keyed by a clean lowercased
email, so every join extracts the bracketed address (falling back to the whole
string when there are no angle brackets) before matching.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

# SQL fragment: turn a raw ``"Name <a@b.com>"`` participant string into the clean
# lowercased email used as the contacts key. Reused by both endpoints.
_CLEAN_EMAIL = "lower(trim(coalesce(substring({col} from '<([^>]*)>'), {col})))"


@router.get("/data")
async def get_graph_data(db: AsyncSession = Depends(get_db)):
    """Return nodes and edges for the contact relationship graph.

    Nodes: every contact with at least one email, plus a single center "you" node.
    Edges: you → each contact (weighted by email volume), and contact → contact
    for people who appear together in the same email thread.
    """
    # Contacts become nodes, busiest first so the force layout seeds large hubs.
    contacts_result = await db.execute(
        text(
            """
            SELECT id, display_name, email_address, email_count,
                   topics, sent_count, received_count
            FROM contacts
            WHERE email_count > 0
            ORDER BY email_count DESC
            """
        )
    )
    contacts = contacts_result.fetchall()

    nodes = [
        {
            "id": f"contact_{c.id}",
            "type": "contact",
            "label": c.display_name or c.email_address.split("@")[0],
            "email": c.email_address,
            "emailCount": c.email_count or 0,
            "topics": c.topics or [],
            "sentCount": c.sent_count or 0,
            "receivedCount": c.received_count or 0,
        }
        for c in contacts
    ]

    # The center node is the user. Use the first connected account's address.
    user_row = (
        await db.execute(text("SELECT email FROM gmail_accounts ORDER BY id LIMIT 1"))
    ).fetchone()
    nodes.insert(
        0,
        {
            "id": "user",
            "type": "user",
            "label": "You",
            "email": user_row.email if user_row else "you",
            "emailCount": 0,
            "topics": [],
            "sentCount": 0,
            "receivedCount": 0,
        },
    )

    # Contact ↔ contact edges: two contacts are linked when they share a thread.
    # `participants` is a raw-address array per thread, so we clean each address,
    # join to contacts, then self-join on the thread to form unordered pairs.
    edges_result = await db.execute(
        text(
            f"""
            WITH thread_contacts AS (
                SELECT DISTINCT t.id AS thread_id, c.id AS contact_id
                FROM email_threads t
                CROSS JOIN LATERAL unnest(t.participants) AS p(raw)
                JOIN contacts c
                  ON c.email_address = {_CLEAN_EMAIL.format(col="p.raw")}
                WHERE c.email_count > 1
            )
            SELECT a.contact_id AS source_id,
                   b.contact_id AS target_id,
                   COUNT(DISTINCT a.thread_id) AS shared_threads
            FROM thread_contacts a
            JOIN thread_contacts b
              ON a.thread_id = b.thread_id AND a.contact_id < b.contact_id
            GROUP BY a.contact_id, b.contact_id
            ORDER BY shared_threads DESC
            LIMIT 2000
            """
        )
    )
    thread_edges = edges_result.fetchall()

    edges = [
        {
            "source": "user",
            "target": f"contact_{c.id}",
            # Cap so a few very busy contacts don't dominate the layout forces.
            "weight": min(c.email_count or 1, 50),
            "sharedThreads": c.email_count or 0,
        }
        for c in contacts
    ]
    edges.extend(
        {
            "source": f"contact_{e.source_id}",
            "target": f"contact_{e.target_id}",
            "weight": e.shared_threads,
            "sharedThreads": e.shared_threads,
        }
        for e in thread_edges
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "totalContacts": len(contacts),
            "totalEdges": len(edges),
        },
    }


@router.get("/contact/{contact_id}/threads")
async def get_contact_threads(contact_id: int, db: AsyncSession = Depends(get_db)):
    """Return a contact's most recent email threads for the detail panel."""
    result = await db.execute(
        text(
            f"""
            SELECT DISTINCT t.id, t.subject, t.last_message_at, t.message_count
            FROM email_threads t
            WHERE EXISTS (
                SELECT 1 FROM unnest(t.participants) AS p(raw)
                WHERE {_CLEAN_EMAIL.format(col="p.raw")} = (
                    SELECT email_address FROM contacts WHERE id = :contact_id
                )
            )
            ORDER BY t.last_message_at DESC NULLS LAST
            LIMIT 10
            """
        ),
        {"contact_id": contact_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]
