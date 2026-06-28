# Meridian Architecture

> Verified against source files. Last updated: 2026-06-27

## System Overview

Meridian is a local-first personal AI OS. The FastAPI backend runs in Docker and
communicates with a host-machine PostgreSQL instance, an Obsidian vault on the
filesystem, and four external APIs (Anthropic, VoyageAI, ElevenLabs, Google). The
React frontend is served by a Vite dev server in a second container and reaches the
backend over HTTP. All long-term memory flows through the Obsidian vault, which is
indexed into pgvector and queried via a tiered RAG pipeline.

## Architecture Diagram

### System Overview

```mermaid
flowchart LR
    FE["Frontend\nReact + Vite\n11 pages"]
    BE["Backend\nFastAPI\n14 routers"]
    DB[("PostgreSQL\n+ pgvector\n19 tables")]
    OBS[("Obsidian Vault\nfilesystem")]
    EXT["External APIs\nAnthropic · VoyageAI\nElevenLabs · Google"]

    FE -->|"HTTP"| BE
    BE -->|"SQLAlchemy async"| DB
    BE -->|"aiofiles"| OBS
    OBS -->|"vault watcher"| BE
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
    ObsSvc["obsidian_service\nTier 1 RAG search"]
    VecSvc["vector_service\nfallback search"]
    GmailSvc["gmail_service\nTier 2 full thread"]
    GmailAPI["Gmail API"]
    CalSvc["calendar_service\nCREATE action token"]
    CalAPI["Google Calendar API"]
    VoiceR["voice.py"]
    ElevenLabs["ElevenLabs TTS"]
    ObsDaily["Obsidian\nDaily note"]

    User -->|"POST /chat/message"| ChatR
    ChatR -->|"assemble context"| ClaudeSvc
    ClaudeSvc --> ProvSvc
    ProvSvc --> ClaudeAPI
    ChatR -->|"tier 1: Obsidian notes"| ObsSvc
    ChatR -->|"fallback: email vectors"| VecSvc
    ChatR -->|"tier 2: tell me more"| GmailSvc
    GmailSvc --> GmailAPI
    ChatR -->|"CALENDAR_CREATE token"| CalSvc
    CalSvc --> CalAPI
    ChatR -->|"append exchange"| ObsDaily
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
    ObsSvc["obsidian_service\nexport threads + contacts"]
    ObsVault["Obsidian Vault\nEmails/ · Contacts/"]
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
    GmailR --> ObsSvc
    ObsSvc -->|"write notes"| ObsVault
```

### Pipeline 3 — Scheduled Tasks

```mermaid
flowchart LR
    Scheduler["run_task_scheduler\nmain.py · wakes every 60s\nreads scheduled_tasks table"]
    EmailPoll["email_poll\nevery 15 min · no AI calls"]
    MBTask["morning_brief\n08:00 local time"]
    ARTask["afternoon_review\n17:00 local time"]
    CSTask["calendar_sync\n07:00 local time"]
    GmailSvc["gmail_service"]
    GmailAPI["Gmail API"]
    DigestSvc["digest_service\ncalendar + email + news + stocks"]
    ProvSvc["provider_service"]
    CalAPI["Google Calendar API"]
    TriageSvc["triage_service"]
    DraftSvc["draft_service"]
    DB[("afternoon_reviews\ndigest_cache\ncalendar_events")]

    Scheduler -->|"every 15 min"| EmailPoll
    Scheduler -->|"08:00"| MBTask
    Scheduler -->|"17:00"| ARTask
    Scheduler -->|"07:00"| CSTask
    EmailPoll --> GmailSvc
    GmailSvc --> GmailAPI
    MBTask --> DigestSvc
    DigestSvc --> ProvSvc
    DigestSvc --> DB
    CSTask -->|"events.list"| CalAPI
    CSTask --> DB
    ARTask --> TriageSvc
    ARTask --> DraftSvc
    TriageSvc --> ProvSvc
    DraftSvc --> ProvSvc
    ARTask --> DB
```

### Pipeline 4 — Obsidian Memory

```mermaid
flowchart LR
    ObsVault["Obsidian Vault\nfilesystem"]
    ObsSvc["obsidian_service\nwatch_vault every 30s\nvectorize_notes_loop every 5min"]
    ObsNotesDB[("obsidian_notes\nvector 512 dims")]
    VecSvc["vector_service\nembed + cosine search"]
    VoyageAPI["VoyageAI\nvoyage-3-lite"]
    ChatR["chat.py\nRAG retrieval"]
    PChatsR["persistent_chats.py\nappend to Chats/ note"]

    ObsVault -->|"scan + watch"| ObsSvc
    ObsSvc -->|"index .md files"| ObsNotesDB
    ObsSvc -->|"batch embed 128 notes"| VecSvc
    VecSvc -->|"voyage-3-lite"| VoyageAPI
    VecSvc -->|"store embeddings"| ObsNotesDB
    ObsNotesDB -->|"pgvector similarity"| VecSvc
    VecSvc -->|"top 5 notes"| ChatR
    PChatsR -->|"mirror exchange"| ObsVault
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
Tier 1 searches Obsidian note embeddings first, falls back to raw email thread
vectors if nothing relevant is found; Tier 2 — triggered by follow-up phrases
like "tell me more" or "full details" — fetches the complete thread directly from
the Gmail API, enriches the Obsidian note in place, and injects full message
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
`obsidian_service` exports each thread and contact to the vault.

### Pipeline 3 — Scheduled Tasks

A generic scheduler (`run_task_scheduler` in `main.py`) wakes every 60 seconds and
reads the `scheduled_tasks` table. Email poll runs on a fixed 15-minute interval and
makes no AI calls — it stores new messages as `pending` for the afternoon review.
The three clock-based tasks (morning brief, afternoon review, calendar sync) fire
when the user's local time matches their configured `schedule_time` and they have not
already run today (checked against the user's local date, not UTC). The afternoon
review task triages the day's pending emails with Claude Haiku, queues draft replies
where a response seems expected, and writes the results to `afternoon_reviews`; the
user approves in the Daily Review panel before anything is sent. Task run status and
summaries are written back to the `scheduled_tasks` row so the Settings UI can show
when each task last ran.

### Pipeline 4 — Obsidian Memory

On startup, `obsidian_service` scans the vault for existing `.md` files and indexes
them into the `obsidian_notes` table. A background `watch_vault` coroutine then polls
for changes every 30 seconds; a separate `vectorize_notes_loop` coroutine embeds
unvectorized notes via VoyageAI in batches of 128, every 5 minutes. RAG retrieval
during chat searches `obsidian_notes` using pgvector cosine similarity, prioritising
`Emails/` and `Contacts/` paths. Persistent chat threads are mirrored to `Chats/`
vault notes after every message so the Obsidian graph grows over time.

### Pipeline 5 — OAuth Flow

When a user connects a new Gmail account, the frontend hits `GET /gmail/auth?label=`.
The router generates a PKCE (code_verifier / code_challenge) pair, stores the
verifier in the `oauth_state` table keyed by a random state token, and redirects the
user to the Google consent screen. On callback, the router retrieves the verifier from
the database, exchanges the authorization code for tokens, and stores the token JSON
in `gmail_accounts.oauth_token`. The `oauth_state` row is deleted immediately after
the exchange completes. Re-authentication for an expired token follows the same flow
via `GET /gmail/reauth/{account_id}`.
