"""Afternoon email review task — triage the day's mail and queue draft replies.

Runs once in the afternoon over emails that arrived today and are still pending.
It classifies each one, keeps a short summary, and for emails that look like they
expect a reply it generates a draft (queued for approval — never auto-sent). The
results are stored in ``afternoon_reviews`` for the Daily Review panel to render.

Nothing here mutates Gmail or applies triage: the user approves in the panel
before any action is taken.
"""

import json
import logging
import re

from sqlalchemy import text

from .base import BaseTask

logger = logging.getLogger(__name__)

# Patterns that suggest the email is proposing a meeting/call worth adding to the
# calendar. Kept deliberately conservative — false positives clutter the review.
MEETING_PATTERNS = (
    r"\b(meet|meeting|call|coffee|lunch|catch up|sync)\b.*\b(monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|\d{1,2}\s?(am|pm)|\d{1,2}:\d{2})\b",
    r"\b(let'?s|lets|can we|could we|would you|are you free)\b.*\b(meet|talk|chat|call|get together)\b",
    r"\b(schedule|book|set up|arrange)\b.*\b(meeting|call|appointment|time)\b",
)


def detect_meeting_language(text_value: str) -> bool:
    """True when the text looks like it's proposing a meeting or call."""
    lowered = (text_value or "").lower()
    return any(re.search(pattern, lowered) for pattern in MEETING_PATTERNS)


def _looks_like_reply_needed(email) -> bool:
    """Heuristic: does this email seem to expect a reply?"""
    subject = (email.subject or "").lower()
    body = (email.body_text or "").lower()[:300]
    reply_signals = (
        "?", "please let me know", "can you", "could you", "would you",
        "do you", "are you", "reply", "respond", "get back to me", "lmk", "thoughts",
    )
    return any(signal in subject or signal in body for signal in reply_signals)


class AfternoonEmailReviewTask(BaseTask):
    """Triage today's pending emails, summarize them, and queue draft replies."""

    name = "Afternoon Email Review"
    description = "Triages emails received today, generates summaries and draft replies"
    default_schedule = "17:00"
    default_days = "daily"

    async def run(self, db) -> dict:
        from services import draft_service, triage_service

        result = await db.execute(
            text(
                """
                SELECT e.*, ga.email AS account_email
                FROM emails e
                JOIN gmail_accounts ga ON e.account_id = ga.id
                WHERE e.triage_status = 'pending'
                  AND DATE(e.received_at) = CURRENT_DATE
                ORDER BY e.received_at DESC
                """
            )
        )
        pending = result.fetchall()

        if not pending:
            return {
                "status": "success",
                "summary": "No new emails to review today",
                "data": {"count": 0},
            }

        reviewed: list[dict] = []
        for email in pending:
            classification = await triage_service.classify_email(
                {
                    "subject": email.subject,
                    "from_address": email.from_address,
                    "snippet": email.snippet,
                    "body_text": (email.body_text or "")[:500],
                },
                db,
            )

            summary = email.summary or (
                f"Email from {email.from_address} about {email.subject}"
            )

            needs_reply = classification == "keep" and _looks_like_reply_needed(email)

            # Generate a draft for emails that want a reply — queued, not sent.
            draft_id = None
            if needs_reply:
                draft = await draft_service.generate_draft(
                    account_id=email.account_id,
                    to_email=email.from_address,
                    subject=f"Re: {email.subject}",
                    context=f"Reply to this email: {(email.body_text or '')[:500]}",
                    db=db,
                    thread_email_id=email.id,
                )
                draft_id = draft.get("id") if draft else None

            entry = {
                "email_id": email.id,
                "subject": email.subject,
                "from": email.from_address,
                "classification": classification,
                "summary": summary,
                "needs_reply": needs_reply,
                "draft_id": draft_id,
                "received_at": email.received_at.isoformat() if email.received_at else None,
            }

            # Flag emails that read like a meeting proposal so the review panel can
            # offer a one-tap "Add to calendar".
            if detect_meeting_language(email.body_text or email.subject or ""):
                entry["calendar_suggestion"] = {
                    "detected": True,
                    "email_id": email.id,
                    "from": email.from_address,
                    "subject": email.subject,
                }

            reviewed.append(entry)

        await db.execute(
            text(
                """
                INSERT INTO afternoon_reviews (review_date, emails_json, status)
                VALUES (CURRENT_DATE, :emails, 'pending')
                ON CONFLICT (review_date) DO UPDATE SET
                    emails_json = EXCLUDED.emails_json,
                    status = 'pending',
                    updated_at = NOW()
                """
            ),
            {"emails": json.dumps(reviewed)},
        )
        await db.commit()

        keep = sum(1 for e in reviewed if e["classification"] == "keep")
        trash = sum(1 for e in reviewed if e["classification"] == "trash")
        archive = sum(1 for e in reviewed if e["classification"] == "archive")
        drafts = sum(1 for e in reviewed if e["draft_id"])

        return {
            "status": "success",
            "summary": (
                f"Reviewed {len(reviewed)} emails: {keep} keep, {archive} archive, "
                f"{trash} trash, {drafts} drafts ready"
            ),
            "data": {
                "reviewed": len(reviewed),
                "keep": keep,
                "archive": archive,
                "trash": trash,
                "drafts": drafts,
            },
        }
