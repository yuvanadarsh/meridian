# Meridian — CLAUDE.md

> Personal AI operating system. Local-first, voice-enabled, multi-account email and calendar management.
> Read this entire file before writing any code.

---

## What Meridian Is

Meridian is a local personal AI OS. It manages multiple Gmail accounts and Google Calendars, surfaces daily briefs (news, stocks, calendar digest), drafts emails in the user's voice using RAG over their email history, and supports voice interaction via push-to-talk (graduating to always-on wake word). All data is stored locally. The only external calls are Claude API, VoyageAI, ElevenLabs, and Google APIs.

---

## Memory Architecture

Meridian uses a unified memory model:

**OBSIDIAN VAULT (knowledge layer)**
- `Daily/YYYY-MM-DD.md` — conversation logs, written after every chat exchange
- `Emails/{Contact}/{Subject}.md` — email thread notes with AI summaries and wikilinks
- `Contacts/{Name}.md` — contact profiles with relationship history and topic links
- `AI Conversations/` — Supercharge imports

**POSTGRESQL (operations layer)**
- `emails`, `email_threads`, `contacts` tables — raw data and metadata
- `obsidian_notes` table — vault file index with pgvector embeddings (512 dims, voyage-3-lite)
- `gmail_accounts`, `calendar_events`, `drafts`, `user_settings` — operational state
- All vector embeddings for RAG are generated FROM Obsidian note content

**RETRIEVAL PIPELINE (tiered)**
1. Search `obsidian_notes` WHERE `file_path LIKE 'Emails/%' OR 'Contacts/%'` (AI-summarized, wikilinked)
2. Fall back to raw `email_threads` vector search if Obsidian has nothing relevant
3. Tier 2 (triggered by "tell me more" / "go deeper" / "full details"): fetch complete thread from Gmail API, write enriched note to Obsidian, return full content

**INGEST PIPELINE (per new account)**
1. Sweep emails → PostgreSQL `emails` table
2. Triage → user approves in UI
3. Vectorize keep/archive emails → pgvector embeddings on `emails`
4. Build threads → `email_threads` table populated
5. Export to Obsidian → `Emails/` and `Contacts/` notes written
6. Vault watcher ingests new notes → `obsidian_notes` table populated + vectorized

**This is an open source project. Code must be clean, well-commented, and readable by strangers on GitHub. No personal details, usernames, local paths, or machine-specific references anywhere in the codebase.**

---

## Tech Stack

### Backend

- **FastAPI** (Python 3.11+) — central API server, runs in Docker
- **PostgreSQL** (local install, not containerized) — all structured data + embeddings via pgvector
- **pgvector** — vector similarity search on email/note embeddings
- **VoyageAI** — email and note embeddings (`voyage-3-lite`, 512 dimensions)
- **Claude API** (`claude-sonnet-4-6`) — reasoning, drafting, triage classification
- **ElevenLabs API** — TTS for voice responses
- **Google APIs** — Gmail + Google Calendar (OAuth 2.0, multiple accounts)
- **Python venv** — always use `.venv` inside `backend/`, never install to global Python

### Frontend

- **React** with **Vite** (not Next.js — this is a local desktop-style app)
- **TypeScript** (strict mode, no `any`)
- **Tailwind CSS**
- **Framer Motion** — orb animations and panel transitions
- **react-icons** — every icon in the app, no custom SVGs unless unavoidable
- **Zustand** — global state (orb state, chat messages, token count, menu)

### Infrastructure

- **Docker Compose** runs: `api` (FastAPI) and `frontend` (Vite dev server) only
- **PostgreSQL** runs locally on the host machine (default port 5432)
- The API container connects to the host DB via `host.docker.internal:5432`
- **Obsidian vault** path configured via `OBSIDIAN_VAULT_PATH` env var — never hardcoded
- All secrets in `.env` — never committed, never hardcoded

---

## File Structure

```
meridian/
├── docker-compose.yml
├── .env.example                  # committed — all required keys, no values
├── .env                          # never committed
├── CLAUDE.md
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .venv/                    # never committed
│   ├── main.py                   # FastAPI app entry
│   ├── routers/
│   │   ├── health.py
│   │   ├── gmail.py
│   │   ├── calendar.py
│   │   ├── chat.py
│   │   ├── voice.py
│   │   └── brief.py
│   ├── services/
│   │   ├── gmail_service.py      # Gmail API + sweep logic
│   │   ├── calendar_service.py
│   │   ├── claude_service.py
│   │   ├── elevenlabs_service.py   # TTS is currently handled inline in voice.py; this file is planned but not yet created
│   │   ├── vector_service.py     # VoyageAI + pgvector
│   │   └── triage_service.py     # Email triage classification
│   ├── models/
│   │   ├── email.py
│   │   ├── calendar.py
│   │   └── chat.py
│   └── db/
│       ├── database.py           # SQLAlchemy async setup
│       ├── init.sql              # Schema — run once manually
│       └── migrations/           # Manual .sql migration files
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── Orb/
│       │   │   └── Orb.tsx
│       │   ├── Chat/
│       │   │   ├── ChatInput.tsx
│       │   │   └── ChatHistory.tsx
│       │   ├── Menu/
│       │   │   ├── HamburgerMenu.tsx
│       │   │   ├── SettingsPanel.tsx
│       │   │   ├── DraftsPanel.tsx
│       │   │   └── ConnectionsPanel.tsx
│       │   ├── Brief/
│       │   │   └── DailyBrief.tsx
│       │   └── TokenUsage/
│       │       └── TokenCounter.tsx
│       ├── hooks/
│       │   ├── useVoice.ts
│       │   └── useChat.ts
│       ├── store/
│       │   └── meridianStore.ts
│       └── api/
│           └── client.ts
│
└── scripts/
    └── setup_oauth.py            # CLI helper: generate OAuth token per account
```

---

## Environment Variables

Every secret and machine-specific value goes in `.env`. `.env.example` is the committed reference.

```bash
# Claude API
ANTHROPIC_API_KEY=

# ElevenLabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=

# VoyageAI
VOYAGE_API_KEY=

# PostgreSQL (local install)
POSTGRES_DB=meridian
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
# OAuth tokens are stored in the database after first auth — not in .env

# Obsidian
OBSIDIAN_VAULT_PATH=           # absolute path to vault on this machine

# App
FRONTEND_URL=http://localhost:5173
API_URL=http://localhost:8000
```

---

## Database Schema

Run `backend/db/init.sql` once against your local PostgreSQL to create the schema.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS gmail_accounts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    label VARCHAR(50),               -- 'personal', 'school', 'work', 'professional'
    oauth_token JSONB,
    last_synced_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS emails (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES gmail_accounts(id),
    gmail_id VARCHAR(255) UNIQUE NOT NULL,
    thread_id VARCHAR(255),
    from_address VARCHAR(255),
    to_addresses TEXT[],
    subject TEXT,
    body_text TEXT,
    snippet TEXT,
    received_at TIMESTAMP,
    triage_status VARCHAR(20) DEFAULT 'pending',  -- 'keep', 'archive', 'trash', 'pending'
    is_vectorized BOOLEAN DEFAULT FALSE,
    embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emails_triage ON emails(triage_status);
CREATE INDEX IF NOT EXISTS idx_emails_account ON emails(account_id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);

CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES gmail_accounts(id),
    google_event_id VARCHAR(255) UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    attendees TEXT[],
    meet_link VARCHAR(500),
    source_email_id INTEGER REFERENCES emails(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    role VARCHAR(20) NOT NULL,       -- 'user' or 'assistant'
    content TEXT NOT NULL,
    tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- DEPRECATED: token_usage is the Phase 1 Anthropic-only counter.
-- New code reads and writes usage_log instead (multi-provider, see migration 018).
CREATE TABLE IF NOT EXISTS token_usage (
    id SERIAL PRIMARY KEY,
    session_date DATE DEFAULT CURRENT_DATE UNIQUE,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    email_address VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    email_count INTEGER DEFAULT 0,
    last_contacted TIMESTAMP,
    embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Gmail Sweep — Critical Implementation Rules

The previous version of this project had bugs here. Build it correctly from the start.

### Body Parsing (most common failure point)

Gmail returns email bodies as a MIME tree. Never assume `payload.body.data` contains the body — it often doesn't for multipart emails. Always traverse the full parts tree:

```python
import base64

def extract_body(payload: dict) -> str:
    """
    BFS traversal of Gmail MIME payload tree.
    Prefers text/plain, falls back to text/html.
    Returns empty string if nothing found.
    """
    text_body = ""
    html_body = ""

    queue = [payload]
    while queue:
        part = queue.pop(0)
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")

        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                if mime_type == "text/plain" and not text_body:
                    text_body = decoded
                elif mime_type == "text/html" and not html_body:
                    html_body = decoded
            except Exception:
                pass

        # Recurse into sub-parts
        for sub_part in part.get("parts", []):
            queue.append(sub_part)

    return text_body or html_body or ""


def extract_header(headers: list, name: str) -> str:
    """Case-insensitive header lookup — Gmail is inconsistent with casing."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""
```

### Rate Limiting

Gmail API enforces 6,000 quota units per minute per user, with a hidden limit of 50 concurrent requests per mailbox that can trigger a 429 even when under the quota unit ceiling. `messages.get` costs 5 units each.

The sweep must:

- Process in batches of 25 emails maximum
- Add 0.1s delay between each `messages.get` call
- Implement exponential backoff on 429: wait `2^attempt` seconds, max 5 retries
- Store progress in DB so a failed sweep can resume from where it stopped, not restart
- Log every 429 with timestamp and resume point

```python
import asyncio
import logging

async def fetch_with_backoff(service, gmail_id: str, max_retries: int = 5):
    for attempt in range(max_retries):
        try:
            return service.users().messages().get(
                userId='me', id=gmail_id, format='full'
            ).execute()
        except Exception as e:
            if '429' in str(e) or 'rateLimitExceeded' in str(e):
                wait = 2 ** attempt
                logging.warning(f"Rate limited on {gmail_id}, waiting {wait}s (attempt {attempt+1})")
                await asyncio.sleep(wait)
            else:
                raise
    raise Exception(f"Max retries exceeded for message {gmail_id}")
```

### Triage Classification

Claude classifies each email. Triage is always presented to the user for approval before any action is taken on Gmail. Never auto-apply triage results.

**Trash** (delete from DB after user approval, remove from Gmail):

- OTP / verification codes
- Promotional / marketing emails (detected by `List-Unsubscribe` header or `CATEGORY_PROMOTIONS` label)
- Automated system notifications with no actionable content
- Bounce/delivery failure messages
- Unsubscribe confirmations

**Archive** (keep in DB, vectorize, remove from Gmail inbox):

- Past conversations — human-to-human email threads
- Receipts and order confirmations
- Shipping notifications
- GitHub/GitLab notifications
- Newsletters the user has opted into reading
- Any email the user has already replied to

**Keep** (stays in inbox, vectorized, highest priority):

- Emails requiring a response or action
- Contracts, agreements, legal documents
- Calendar invitations
- Direct correspondence from known contacts
- Anything addressed personally (not bulk)

**Vectorize**: Keep + Archive. Never vectorize Trash.

---

## Orb Design Specification

The orb is the visual and interactive core of Meridian.

**States and behavior:**

- `idle` — 300px, slow scale breathing (0.97 → 1.03, 3s loop), dim glow, slow color rotation
- `listening` — expands to 380px, faster pulse (1.5s), brighter glow, mic icon appears
- `thinking` — 340px, border-radius morphs rapidly between asymmetric values (processing feel)
- `speaking` — 360px, scale pulses at short intervals to simulate audio waveform energy

**Visual:**

- Page background: `#0a0a0a`
- Orb core: radial gradient `#1a3a5c` → `#0d1b2a`
- Glow: layered box-shadow in magenta/purple/cyan (`#c026d3`, `#7c3aed`, `#0ea5e9`)
- Shape: CSS `border-radius` morphing via Framer Motion keyframes
- Font: Space Grotesk (import from Google Fonts)
- No Three.js in Phase 1 — pure CSS + Framer Motion

**Layout:**

- "Meridian" — top-left, weight 600, white
- Token counter — top-right, small, subtle (`text-white/40 text-xs font-mono`)
- Orb — centered
- Chat input — below orb, pill shape, glassmorphism (`bg-white/5 backdrop-blur border border-white/10`)
- Hamburger — bottom-left, circular, `bg-white/10`

**Hamburger menu items:** Settings, Drafts, Connections, Brief

---

## Git & GitHub Conventions

### Commit format — one commit per completed subfeature:

```
feat(orb): add idle and listening states with framer motion
feat(db): initialize schema with pgvector and all Phase 1 tables
feat(gmail): implement oauth flow and token storage
feat(gmail): email sweep with rate limiting and exponential backoff
feat(gmail): body parser handles multipart mime trees correctly
feat(triage): claude-powered email classification with user approval flow
feat(calendar): sync upcoming and recent events per account
feat(chat): wire chat input to claude api with token tracking
feat(voice): push-to-talk via web speech api and elevenlabs tts
fix(gmail): case-insensitive header extraction for subject field
chore(docker): configure api container to connect to host postgresql
docs(readme): add setup, oauth, and local development instructions
```

### Pull request titles — describe the user-facing capability:

- ✅ `Animated orb UI with idle, listening, thinking, and speaking states`
- ✅ `Gmail OAuth and email sweep with rate limiting and triage classification`
- ✅ `Voice chat via push-to-talk with ElevenLabs TTS`
- ❌ `phase 1`, `feat-1`, `initial commit`, `done`

### PR description must include:

- What was built
- How to test it locally
- Any new `.env` keys required
- Screenshots if UI changed

### Branch strategy:

- `main` — always working
- `feat/meridian-foundation` — Phase 1 branch
- Commit every completed subfeature before moving to the next
- PR from branch → main once phase is complete and manually tested

---

## Code Standards

- **TypeScript strict mode** — no `any` types, no implicit returns
- **Pydantic models** for all FastAPI request/response shapes
- **No inline styles** on frontend — Tailwind classes or Framer Motion `style` prop for animation values only
- **react-icons for all icons** — prefer `react-icons/fi` (Feather) or `react-icons/hi2` (Heroicons). No custom SVGs.
- **Error handling** — all API routes return `{ error: string, detail?: string }` on failure
- **Logging** — Python `logging` module on backend. No `print()` or `console.log` in committed code.
- **Comments** — explain non-obvious logic. This is open source.
- **No personal paths** — never hardcode `/Users/...` or machine-specific paths. Use env vars.

---

## What NOT To Do

- Do not use Next.js — Vite + React only
- Do not run a PostgreSQL container — connect to the host machine's local install
- Do not hardcode any API key, path, or username
- Do not vectorize emails with `triage_status = 'trash'`
- Do not apply triage results to Gmail without explicit user approval
- Do not commit `.env`, `.venv/`, `__pycache__/`, `node_modules/`, or OAuth token files
- Do not add signoff lines like "Done by Claude Code" to commits
- Do not use Inter as the primary font — use Space Grotesk
- Do not use purple gradients as the primary UI aesthetic (orb glow is fine)
- Do not skip commits — every completed subfeature gets its own commit message

---

## Phase Plan

| Phase                        | Deliverable                                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------- |
| **1 — Foundation**           | Docker + FastAPI + Orb UI + one Gmail sweep + one Calendar + text chat + push-to-talk voice |
| **Onboarding flow**          | Per-account: sweep → triage review → user approval → vectorize → calendar sync              |
| **2 — All accounts**         | Repeat onboarding for accounts 2–4                                                          |
| **3 — Intelligence**         | Email drafting in user's voice, news digest, stock watchlist, web search                    |
| **4 — Memory & intelligence**| Threading, hybrid search, contacts graph, multi-provider AI, scheduled digest               |
| **5A — Memory unification**  | Email threads + contacts written to Obsidian; tiered RAG with Obsidian-first retrieval      |
| **5B — Scheduling & review** | Task registry + dynamic scheduler, 15-min Gmail polling, afternoon email review + Daily Review panel, calendar conflict detection, email-driven event suggestions |
| **5C — Always-on voice**     | Wake word detection (future)                                                                |

**Current phase: 5B complete**

### Task registry (Phase 5B)

Background tasks live in `backend/services/tasks/`, each a `BaseTask` subclass with
`run()`, `name`, `description`, and `default_schedule`. Register a new task by
adding it to `TASK_REGISTRY` in `services/tasks/__init__.py`. The generic
`run_task_scheduler` in `main.py` reads the `scheduled_tasks` table (configured
from Settings) — `email_poll` runs on its own 15-minute interval; clock-based
tasks run at their `schedule_time` in the user's timezone. The afternoon review
never mutates Gmail; the user approves in the Daily Review panel first.

---

## Running Locally

```bash
# Prerequisites: PostgreSQL running locally, Node 18+, Python 3.11+, Docker

# 1. Clone and configure
git clone https://github.com/YOUR_USERNAME/meridian.git
cd meridian
cp .env.example .env
# Edit .env with your API keys and local postgres credentials

# 2. Create the database and schema
psql -U your_user -c "CREATE DATABASE meridian;"
psql -U your_user -d meridian -f backend/db/init.sql

# 3. Start backend and frontend via Docker
docker compose up --build

# 4. Or run backend locally (without Docker)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 5. Run frontend
cd frontend
npm install
npm run dev

# 6. Connect first Gmail account
python scripts/setup_oauth.py --label personal
```

Frontend: http://localhost:5173  
API: http://localhost:8000  
API docs: http://localhost:8000/docs
