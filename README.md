# Meridian

A local-first personal AI operating system. Meridian manages your email accounts,
calendars, and daily information — and lets you interact with all of it through
a voice-enabled animated interface. All data is stored locally; the only outbound
calls are to Claude, VoyageAI, ElevenLabs, and Google APIs.

## Features (Phase 1)

- Animated orb UI with idle, listening, thinking, and speaking states
- Gmail OAuth for multiple accounts with email sweep and triage
  - Correct MIME tree body parsing (multipart, nested parts, base64url)
  - Case-insensitive header extraction
  - Rate limiting with exponential backoff on 429s
  - Resumable sweep (progress tracked in the database)
- Claude-powered email triage (trash / archive / keep) with user approval before any Gmail mutation
- Google Calendar sync with today and upcoming event queries
- Text chat and push-to-talk voice via Claude + ElevenLabs
- Live token usage counter (polls the database)
- All data stored locally — nothing leaves your machine except API calls

## Features (Phase 2)

- **Dot-sphere orb** — a canvas-rendered rotating sphere of dots replaces the
  CSS blob, with distinct idle / listening / thinking / speaking motion
- **Chat modal** — full-screen blurred overlay with markdown-rendered replies, a
  textarea that grows with its content, and conversation history pre-loaded from
  the database on page load (the last reply shows as a subtitle under the orb)
- **Onboarding flow** — connect an account, then: choose how much to sweep
  (all / last N / since a date) → watch live progress → review the AI triage →
  approve → build memory (vectorize)
  - Sweep, triage classification, and a one-sentence summary per email happen in
    a single pass (25 emails per Claude call)
  - Per-category review with individual checkboxes and recategorization; only
    your changes are sent on approval
  - Keep + Archive emails are embedded with VoyageAI right after approval
- **Unlimited accounts** — add and remove any number of Google accounts; no fixed
  role slots
- **Obsidian memory layer** — conversations are written to daily notes with
  auto-extracted `[[wikilinks]]`, the vault is ingested into PostgreSQL, and
  relevant notes are retrieved (RAG) into the chat context
- Fixes: the assistant knows the calendar is read-only (no hallucinated
  scheduling), the `?connected=` OAuth param is stripped after sign-in, and chat
  history survives a refresh

## Prerequisites

- macOS or Linux
- Docker and Docker Compose
- Node.js 18+
- Python 3.11+
- PostgreSQL (local install) with the [pgvector](https://github.com/pgvector/pgvector) extension available

## Setup

1. Clone the repo and configure environment:

   ```bash
   git clone https://github.com/YOUR_USERNAME/meridian.git
   cd meridian
   cp .env.example .env
   # Edit .env with your API keys and local postgres credentials
   ```

2. Create the local database and schema:

   ```bash
   psql -U your_user -c "CREATE DATABASE meridian;"
   psql -U your_user -d meridian -f backend/db/init.sql
   ```

   On an existing database created before Phase 2, apply the migrations instead
   of (or in addition to) re-running `init.sql`:

   ```bash
   psql -U your_user -d meridian -f backend/db/migrations/002_obsidian_notes.sql
   psql -U your_user -d meridian -f backend/db/migrations/003_email_summary.sql
   ```

3. (Optional) Point Meridian at your Obsidian vault for the memory layer by
   setting `OBSIDIAN_VAULT_PATH` in `.env` to the vault's **absolute path**
   (e.g. `/Users/you/Documents/MyVault`). Docker Compose mounts this path
   directly into the API container so daily-note writes and RAG reads go to
   your real vault on disk — a relative path will silently write inside the
   container instead. When unset, the daily-note writer and RAG retrieval
   simply no-op.

4. Start Meridian (FastAPI + Vite, connecting to your host PostgreSQL):

   ```bash
   docker compose up --build
   ```

5. Open http://localhost:5173 (use **Chrome** — push-to-talk voice relies on the
   Web Speech API, which other browsers don't fully support)

6. Connect your Gmail account via the Connections panel (hamburger menu), which
   drops you straight into the onboarding flow. You can also connect from the CLI:

   ```bash
   python scripts/setup_oauth.py --label personal
   ```

- Frontend: http://localhost:5173
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### Running the backend without Docker

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## API Keys Required

See `.env.example` for all required keys:

- **Anthropic** (Claude API) — reasoning, drafting, and triage
- **ElevenLabs** (TTS) — voice responses
- **VoyageAI** (embeddings) — used from Phase 2
- **Google OAuth** credentials (from the Google Cloud Console) — Gmail + Calendar

OAuth tokens are stored in the database after first authentication, never in `.env`.

## Architecture

- **Frontend:** React + Vite + TypeScript + Tailwind + Framer Motion
- **Backend:** FastAPI (Python), async SQLAlchemy
- **Database:** PostgreSQL + pgvector (runs on the host, not containerized)
- **AI:** Claude (`claude-sonnet-4-6`) for reasoning, VoyageAI for embeddings, ElevenLabs for TTS
- **Memory:** an Obsidian vault (set via `OBSIDIAN_VAULT_PATH`) — daily notes are
  written after each exchange, ingested back into pgvector, and retrieved into
  chat context. A background watcher in the FastAPI lifespan polls the vault.

Only the `api` and `frontend` services run in Docker; the API container reaches
your host PostgreSQL via `host.docker.internal`.

## License

MIT
