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

3. Start Meridian (FastAPI + Vite, connecting to your host PostgreSQL):

   ```bash
   docker compose up --build
   ```

4. Open http://localhost:5173

5. Connect your Gmail account via the Connections panel (hamburger menu), or from the CLI:

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

Only the `api` and `frontend` services run in Docker; the API container reaches
your host PostgreSQL via `host.docker.internal`.

## License

MIT
