# Meridian Architecture

> Verified against source files. Last updated: 2026-06-29

## System Overview

Meridian is a local-first personal AI OS. The FastAPI backend runs in Docker and
communicates with a host-machine PostgreSQL instance and four external APIs
(Anthropic, VoyageAI, ElevenLabs, Google). The React frontend is served by a Vite
dev server in a second container and reaches the backend over HTTP. All long-term
memory lives in PostgreSQL — `memory_service` writes notes to the `notes` table and
embeds them on write, and chat queries them via a tiered RAG pipeline.

## Architecture Diagram

### System Overview

```mermaid
flowchart LR
    FE["Frontend\nReact + Vite\n11 pages"]
    BE["Backend\nFastAPI\n14 routers"]
    DB[("PostgreSQL\n+ pgvector\nnotes + ops tables")]
    EXT["External APIs\nAnthropic · VoyageAI\nElevenLabs · Google"]

    FE -->|"HTTP"| BE
    BE -->|"SQLAlchemy async\n(notes = memory layer)"| DB
    BE -->|"API calls"| EXT
```

### Pipeline 1 — Chat & RAG

```mermaid
flowchart LR
    User["User\ntype or voice"]
    ChatR["chat.py router"]
    ClaudeSvc["claude_service\nbuild_system_prompt()"]
    ProvSvc["provider_service\ncall_chat()"]
    ClaudeAPI["Anthropic\nClaude API"]
    MemSvc["memory_service\nTier 1 RAG search"]
    VecSvc["vector_service\nfallback search"]
    GmailSvc["gmail_service\nTier 2 full thread"]
    GmailAPI["Gmail API"]
    CalSvc["calendar_service\nCREATE action token"]
    CalAPI["Google Calendar API"]
    VoiceR["voice.py"]
    ElevenLabs["ElevenLabs TTS"]
    DailyNote[("notes table\ndaily note")]

    User -->|"POST /chat/message"| ChatR
    ChatR -->|"assemble context"| ClaudeSvc
    ClaudeSvc --> ProvSvc
    ProvSvc --> ClaudeAPI
    ChatR -->|"tier 1: memory notes"| MemSvc
    ChatR -->|"fallback: email vectors"| VecSvc
    ChatR -->|"tier 2: tell me more"| GmailSvc
    GmailSvc --> GmailAPI
    ChatR -->|"CALENDAR_CREATE token"| CalSvc
    CalSvc --> CalAPI
    ChatR -->|"write_daily_note"| DailyNote
    User -->|"push-to-talk"| VoiceR
    VoiceR --> ElevenLabs
```

### Pipeline 2 — Email Sweep

```mermaid
flowchart LR
    UI["Connections Page"]
    GmailR["gmail.py router"]
    GmailSvc["gmail_service\nbatch fetch · MIME parser"]
    GmailAPI["Gmail API"]
    TriageSvc["triage_service\nbatch 25 emails/call"]
    Haiku["Claude Haiku\nclassify"]
    User2["User approval\nReview page"]
    VecSvc["vector_service\nembed keep + archive"]
    VoyageAPI["VoyageAI"]
    ThreadSvc["thread_service\ngroup by thread_id"]
    MemSvc["memory_service\nexport threads + contacts"]
    NotesDB[("notes table\nemail · contact notes")]
    DB[("emails\nemail_threads\ncontacts")]

    UI -->|"POST /gmail/sweep"| GmailR
    GmailR --> GmailSvc
    GmailSvc -->|"messages.list/get"| GmailAPI
    GmailR --> TriageSvc
    TriageSvc --> Haiku
    GmailR -->|"show results"| User2
    User2 -->|"POST /gmail/triage/approve"| GmailR
    GmailR --> VecSvc
    VecSvc --> VoyageAPI
    VecSvc --> DB
    GmailR --> ThreadSvc
    ThreadSvc --> DB
    GmailR --> MemSvc
    MemSvc -->|"write + embed notes"| NotesDB
```

### Pipeline 3 — Scheduled Tasks

```mermaid
flowchart LR
    Scheduler["run_task_scheduler\nmain.py · wakes every 60s\nreads scheduled_tasks table"]
    EmailPoll["email_poll\nevery 15 min · fetch + triage"]
    CSTask["calendar_sync\n07:00 local time"]
    GmailSvc["gmail_service"]
    GmailAPI["Gmail API"]
    TriageSvc["triage_service\n4-category classify"]
    ProvSvc["provider_service"]
    CalAPI["Google Calendar API"]
    DB[("email_queue\ncalendar_events")]

    Scheduler -->|"every 15 min"| EmailPoll
    Scheduler -->|"07:00"| CSTask
    EmailPoll --> GmailSvc
    GmailSvc --> GmailAPI
    EmailPoll --> TriageSvc
    TriageSvc --> ProvSvc
    EmailPoll -->|"insert classified mail"| DB
    CSTask -->|"events.list"| CalAPI
    CSTask --> DB
```

### Pipeline 4 — PostgreSQL Memory

```mermaid
flowchart LR
    Writers["memory_service writers\nwrite_daily/email/contact/\npersistent_chat/sent_note"]
    VoyageAPI["VoyageAI\nvoyage-3-lite"]
    NotesDB[("notes table\nvector 512 dims")]
    Search["memory_service.search_notes\npgvector cosine"]
    ChatR["chat.py\nRAG retrieval"]
    PChatsR["persistent_chats.py\nappend to Chats/ note"]

    Writers -->|"embed on write"| VoyageAPI
    Writers -->|"INSERT/UPDATE + embedding"| NotesDB
    PChatsR --> Writers
    NotesDB -->|"pgvector similarity"| Search
    Search -->|"top N notes"| ChatR
```

### Pipeline 5 — OAuth Flow

```mermaid
flowchart LR
    UI["Connections Page\nor re-auth banner"]
    GmailR["gmail.py router\nGET /gmail/auth\nGET /gmail/reauth/:id"]
    PKCE["generate_pkce_pair()\ncode_verifier + code_challenge"]
    OAuthState[("oauth_state table\nstate → verifier")]
    Google["Google OAuth\nconsent screen"]
    Callback["GET /gmail/callback\ncode + state"]
    TokenStore[("gmail_accounts\noauth_token\nauth_status")]

    UI -->|"connect / reauth"| GmailR
    GmailR --> PKCE
    PKCE -->|"save verifier"| OAuthState
    GmailR -->|"redirect"| Google
    Google -->|"authorization code"| Callback
    Callback -->|"retrieve verifier"| OAuthState
    Callback -->|"exchange code → tokens"| TokenStore
    OAuthState -->|"delete row"| OAuthState
```

## Pipeline Descriptions

### Pipeline 1 — Chat & RAG

The daily chat and all persistent chat threads share the same chat router.
For each message, the router assembles a system prompt (calendar context, tone,
action protocol) via `claude_service`, then performs tiered RAG retrieval:
Tier 1 searches `email`/`contact` note embeddings first, falls back to raw email
thread vectors if nothing relevant is found; Tier 2 — triggered by follow-up phrases
like "tell me more" or "full details" — fetches the complete thread directly from
the Gmail API, writes an enriched note to the `notes` table, and injects full message
bodies into the same Claude request. Responses that contain a `CREATE_CALENDAR_EVENT`
action token are intercepted by the router and forwarded to `calendar_service`.
Voice responses are synthesized via ElevenLabs at the end of the turn.

### Pipeline 2 — Email Sweep

Triggered from the Connections page, the sweep processes one Gmail account at a
time. `gmail_service` fetches messages in batches of 25 with a 0.1 s inter-call
delay and exponential backoff on 429 responses; each message body is extracted via
a BFS traversal of the MIME part tree. `triage_service` classifies batches of 25
emails per Claude Haiku call into keep / archive / trash / unreadable. Triage
results are shown to the user for approval — nothing is written to Gmail without
explicit confirmation. After approval, `vector_service` embeds the keep and archive
emails via VoyageAI; `thread_service` groups them into `email_threads` rows; and
`memory_service` writes an `email` note per thread and a `contact` note per contact
(embedded on write) to the `notes` table.

### Pipeline 3 — Scheduled Tasks

A generic scheduler (`run_task_scheduler` in `main.py`) wakes every 60 seconds and
reads the `scheduled_tasks` table. Email poll runs on a fixed 15-minute interval: it
fetches new mail via `gmail_service`, then immediately classifies each message with
`triage_service` into one of `trash`/`archive`/`keep`/`draft` and inserts a row into
`email_queue` (continuous triage on arrival). The clock-based `calendar_sync` task
fires when the user's local time matches its configured `schedule_time` and it has not
already run today (checked against the user's local date, not UTC). Nothing is applied
to Gmail by the scheduler — the queue accumulates until the user approves it on the
Inbox page. Task run status and summaries are written back to the `scheduled_tasks`
row so the Settings UI can show when each task last ran.

### Pipeline 4 — PostgreSQL Memory

Memory lives entirely in the `notes` table. `memory_service.write_note` upserts a
note by title (appending on a title collision) and embeds it immediately via the
configured model — there is no filesystem vault and no background watcher. Typed
writers cover each source: daily chat exchanges, email-thread summaries, contact
profiles, persistent-chat threads (mirrored to a `Chats/` note), and sent mail. RAG
retrieval during chat calls `memory_service.search_notes`, which runs pgvector cosine
similarity over the `notes` table and can filter by `note_type`. If embedding fails on
write, the note is still stored with a NULL embedding and a warning is logged.

### Pipeline 5 — OAuth Flow

When a user connects a new Gmail account, the frontend hits `GET /gmail/auth?label=`.
The router generates a PKCE (code_verifier / code_challenge) pair, stores the
verifier in the `oauth_state` table keyed by a random state token, and redirects the
user to the Google consent screen. On callback, the router retrieves the verifier from
the database, exchanges the authorization code for tokens, and stores the token JSON
in `gmail_accounts.oauth_token`. The `oauth_state` row is deleted immediately after
the exchange completes. Re-authentication for an expired token follows the same flow
via `GET /gmail/reauth/{account_id}`.
