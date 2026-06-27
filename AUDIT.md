# Meridian — Codebase Audit

> Generated on `feat/codebase-audit` branch.  
> Graph: 1,378 nodes · 2,389 edges · 89 communities (graphify `--update`).  
> No code was changed during this audit.

---

## SAFE TO DELETE

Items confirmed dead: no caller in the frontend, no backend reference beyond their own declaration.

### 1. `backend/routers/obsidian.py` — entire file

**Single route:** `POST /obsidian/append`  
**Caller count:** 0 — `api/client.ts` has no method for this endpoint; no `fetch` call in the frontend matches it.  
**Why it exists:** Created in Phase 1 as a public entry point for vault writes. In practice, `obsidian_service.append_exchange()` is called directly inside `chat.py` on every exchange. The router is a dead stub.  
**Action:** Delete the file; remove `app.include_router(obsidian.router)` from `main.py`.

---

### 2. `GET /calendar/today/{account_id}` — `backend/routers/calendar.py`

**Caller count:** 0 — `api/client.ts` only calls `GET /calendar/today` (all accounts, no path param).  
**Why it exists:** Per-account variant predates the all-accounts aggregate endpoint added in Phase 5.  
**Action:** Delete the route. `GET /calendar/today` supersedes it.

---

### 3. `GET /calendar/upcoming/{account_id}` — `backend/routers/calendar.py`

**Caller count:** 0 — not in `api/client.ts` or any `fetch` call in the frontend.  
**Why it exists:** Added early but the frontend was never wired up; `getCalendarToday()` covers the use case.  
**Action:** Delete the route.

---

### 4. Duplicate `contacts.router` registration — `backend/main.py`

```python
# main.py — contacts.router is included twice
app.include_router(contacts.router)  # first registration
# ... other routers ...
app.include_router(contacts.router)  # second registration (duplicate)
```

FastAPI silently registers every `/contacts/*` route twice. The second registration wins for route resolution, but OpenAPI schema lists each route twice and middleware runs twice per request.  
**Action:** Delete one `app.include_router(contacts.router)` line.

---

## INCOMPLETE

Features that exist but are partially wired, unrouted, or silently bypassed.

### 1. `POST /calendar/events` — reachable only via chat action protocol

`backend/routers/calendar.py` has `POST /calendar/events` but `api/client.ts` has no method for it. Event creation is triggered only when `chat.py` parses a `CALENDAR_CREATE:` action token from Claude's response — the route itself is an internal relay, not a user-facing API.  
**Risk:** Any UI flow that needs direct calendar event creation (e.g., a calendar panel) must go through chat. There is no `api.createCalendarEvent()` shortcut.  
**Recommendation:** Either expose it in `client.ts` explicitly or add a code comment noting the intentional design.

---

### 2. `elevenlabs_service.py` — listed in CLAUDE.md, does not exist

CLAUDE.md's file tree lists `backend/services/elevenlabs_service.py`. The file does not exist. TTS is handled inline in `backend/routers/voice.py` using `aiohttp` directly.  
**Risk:** Any contributor following the documented architecture will look for a non-existent module.  
**Recommendation:** Either create the service file and move the TTS logic there, or remove the entry from CLAUDE.md.

---

### 3. `digest_service.py` bypasses provider routing

`digest_service.py` calls `claude_service.chat()` directly (the low-level Anthropic-SDK wrapper) instead of `provider_service.call_chat()`. This means the morning digest is hardcoded to Anthropic/Claude regardless of the provider the user has configured in Settings.

```python
# digest_service.py — direct Claude call, not routed through provider_service
reply = await claude_service.chat(db, messages, ...)
```

All other AI calls in the codebase (`triage_service`, `draft_service`, `afternoon_review`) correctly go through `provider_service`.  
**Risk:** Users who switch to OpenAI or Gemini in Settings will still see Anthropic billed for digest generation. Usage is also not logged to `usage_log`.  
**Recommendation:** Replace the `claude_service.chat()` call with `provider_service.call_chat()`.

---

### 4. `contact_service._extract_topics()` bypasses provider routing

`contact_service.py` calls `claude_service.get_client()` and uses the raw Anthropic Python SDK directly to extract contact topics. Same bypass pattern as the digest — no usage logging, no provider selection.  
**Recommendation:** Route through `provider_service.call_classify()`.

---

### 5. `init.sql` is Phase 1 only — 10 tables missing

`backend/db/init.sql` is the "run once" schema referenced in CLAUDE.md and the README, but it only contains the 8 Phase 1 tables. A fresh install that runs only `init.sql` will be missing every table added in migrations 006–019 and will fail at runtime. See **SCHEMA DRIFT** section for the full list.  
**Recommendation:** Consolidate all migrations into `init.sql` (see Migration Consolidation below).

---

### 6. Dual token-tracking tables — `token_usage` vs `usage_log`

Two tables track token consumption:

| Table | Added | Scope | Written by |
|-------|-------|-------|------------|
| `token_usage` | Phase 1 | Anthropic only, daily total | `chat.py` `_persist_exchange()` |
| `usage_log` | Phase 4 (mig. 018) | Multi-provider, per-call itemized | `usage_service.log_usage()` |

`TokenCounter` now calls `GET /usage/today` (the `usage_log`-backed endpoint). The legacy `GET /chat/tokens/today` endpoint still exists and `api.getTokensToday()` still exists in `client.ts`, but no frontend component currently calls it.  
**Risk:** `token_usage` silently accumulates stale data for Anthropic calls while `usage_log` is the source of truth for the UI. Contributors may add to `token_usage` thinking it feeds the counter.  
**Recommendation:** Deprecate `token_usage`. Add a comment in `chat.py` noting it is legacy. Route the `GET /chat/tokens/today` endpoint to `usage_service.get_usage_today()` or remove it.

---

## GOD MODULES

Files that have grown beyond a single responsibility.

### 1. `backend/services/obsidian_service.py`

Responsibilities currently bundled into one file:

- **Vault I/O** — reading and writing `.md` files to the configured vault path
- **Vault watcher** — `watchdog` file-system listener that auto-ingests new notes
- **Note ingestion** — parsing frontmatter, chunking, writing to `obsidian_notes` table
- **Vectorization** — calling VoyageAI and storing embeddings in `obsidian_notes.embedding`
- **RAG retrieval** — tiered vector + keyword search across `obsidian_notes`
- **Thread export** — `export_threads_to_obsidian_background()` and progress tracking
- **Contact export** — `export_contacts_to_obsidian_background()` and progress tracking
- **Daily note writing** — `append_exchange()` for conversation logs
- **Review summary writing** — `append_review_summaries()` for afternoon review results

**Why this matters:** Every feature that touches memory goes through a single file. A bug or refactor here affects the watcher, the export pipelines, and real-time RAG simultaneously.  
**Recommendation:** Split into `obsidian_io.py` (file read/write), `obsidian_watcher.py` (filesystem events), and `obsidian_rag.py` (retrieval). The export pipelines could move to `thread_service.py` and `contact_service.py` respectively.

---

### 2. `backend/routers/chat.py`

A router file that has accumulated service-level logic:

- **Chat history** — persist and retrieve messages from `chat_messages`
- **Calendar conflict state** — module-level `_pending_event` dict
- **Action token parsing** — regex extraction of `CALENDAR_CREATE:`, `DRAFT_EMAIL:`, `SEARCH_EMAIL:` etc.
- **Tiered RAG retrieval** — `_get_context_tiered()` with Obsidian → pgvector fallback → Tier 2 Gmail fetch
- **Draft intent detection** — pattern matching to auto-open draft flow
- **Obsidian mirroring** — calls `obsidian_service.append_exchange()` after every message
- **Token accumulation** — writes to both `chat_messages` and `token_usage`

The file is ~600 lines. Routers should dispatch to services; they should not contain retrieval pipelines.  
**Recommendation:** Extract `_get_context_tiered()` into a `retrieval_service.py`, action token parsing into a `action_parser.py`, and calendar conflict tracking into `calendar_service.py`.

---

### 3. `backend/services/gmail_service.py`

- **OAuth 2.0 + PKCE** — `generate_pkce_pair()`, `build_auth_url()`, `exchange_code()`
- **Credential management** — `credentials_to_dict()`, `get_credentials()`, `get_account_email()`
- **Account CRUD** — `upsert_account()`, `list_accounts()`, `update_account_label()`, `delete_account()`
- **Sweep pipeline** — `run_sweep_background()`, `get_sweep_progress()`, batch fetching with rate limiting
- **Body parsing** — `extract_body()`, `extract_header()` (MIME BFS traversal)
- **Thread fetching** — `fetch_full_thread()`
- **Email sending** — `send_email()`
- **Mailbox estimation** — `estimate_count()`

Everything Gmail-related lives here. The OAuth helpers and the sweep pipeline are independent enough to split without cross-cutting dependencies.  
**Recommendation:** Move OAuth helpers to `gmail_auth.py` and keep `gmail_service.py` for mailbox operations.

---

## SCHEMA DRIFT

`backend/db/init.sql` is out of sync with the application's actual schema. A fresh install that runs only `init.sql` will fail.

### Tables missing from `init.sql` (added by migrations)

| Table | Migration | Used by |
|-------|-----------|---------|
| `drafts` | 006 | `draft_service.py`, `drafts.py` router |
| `user_settings` | 007 | `settings_service.py`, `settings.py` router |
| `digest_cache` | 009 | `digest_service.py` |
| `email_threads` | 010 | `thread_service.py` |
| `ai_providers` | 013 | `provider_service.py`, `settings.py` router |
| `supercharge_imports` | 014 | `supercharge_service.py` |
| `scheduled_tasks` | 016 | `tasks.py` router, `main.py` task scheduler |
| `afternoon_reviews` | 017 | `review.py` router, `afternoon_review.py` task |
| `usage_log` | 018 | `usage_service.py`, `usage.py` router |
| `oauth_state` | 019 | `gmail.py` router (PKCE state storage) |

### Columns missing from `init.sql` on existing tables

| Table | Column | Migration | Notes |
|-------|--------|-----------|-------|
| `emails` | `summary TEXT` | 003 | AI-generated summary for triage UI |
| `sweep_progress` | `sweep_completed_at TIMESTAMP` | 004 | Records when sweep finished |
| `emails` | `embedding vector(512)` | 005 | Resized from 1024 in init.sql |
| `obsidian_notes` | `embedding vector(512)` | 005 | Resized from 1024 in init.sql |
| `emails` | `thread_db_id INTEGER` | 010 | FK to `email_threads` |
| `emails` | `search_vector tsvector GENERATED ALWAYS` | 011 | Full-text search column |
| `email_threads` | `search_vector tsvector` (trigger-based) | 011b | Full-text search column |
| `contacts` | `sent_count`, `received_count`, `first_contacted`, `topics` | 012 | Extended contact profile |
| `gmail_accounts` | `auth_status VARCHAR(20)` | 019 | `'ok'` or `'expired'` |

### Migration consolidation recommendation

Replace the current "run `init.sql`, then run all 19 migrations" install path with a single `init.sql` that includes the complete current schema. Keep the individual migration files in `db/migrations/` for reference and for existing installs that need to upgrade incrementally, but update the README to clarify that `init.sql` is the canonical fresh-install path.

---

## RECOMMEND KEEP

Items that look unusual but are intentional and load-bearing.

### 1. `GET /gmail/threads/count/{account_id}` — intentional alias

This route calls the same `thread_service.build_progress()` function as `GET /gmail/threads/build/progress/{account_id}`. `client.ts` has both `getThreadsProgress` and `getThreadsCount` calling different endpoints. This is intentional: the Onboarding wizard and the ConnectionsPanel poll the same progress data but the Onboarding component cleans up its polling on unmount while ConnectionsPanel keeps a separate handle. The alias exists to make caller intent explicit in server logs.

### 2. `_pending_event` in `chat.py` — single-user assumption documented

The module-level dict `_pending_event: dict[str, Any] = {}` stores in-progress calendar creation state across chat turns. This is explicitly a single-user assumption (Meridian is a local personal OS). Not a bug — but fragile if Meridian ever moves to multi-user. A comment in the code would help future contributors.

### 3. Two obsidian export triggers for the same account

`POST /gmail/triage/approve/{account_id}` kicks off:
```python
background_tasks.add_task(vector_service.run_vectorize_background, account_id)
background_tasks.add_task(thread_service.run_build_threads_background, account_id)
background_tasks.add_task(obsidian_service.export_threads_to_obsidian_background, account_id)
```
And separately `POST /gmail/threads/export-to-obsidian/{account_id}` exists as a manual re-trigger. Both are valid: auto-trigger after approval, manual re-export from ConnectionsPanel. Intentional duplication, not dead code.

### 4. `claude_service.py` — not a god module

`claude_service.py` contains `build_system_prompt()` (called by `chat.py`) and `get_client()` / `extract_text()` (called by `provider_service.py`). It looks like a dependency between service layers but is actually provider_service's low-level Anthropic adapter. The design is correct — `provider_service` is the router, `claude_service` is the Anthropic driver. The unusual pattern is `contact_service` and `digest_service` reaching past `provider_service` directly into this driver (see INCOMPLETE section).

### 5. All frontend components — no dead UI code

Every component file in `frontend/src/components/` is reachable from `App.tsx` via the import chain. Import tree verified:

```
App.tsx
├── Orb/Orb.tsx
├── GlanceStrip/GlanceStrip.tsx
├── Chat/ChatInput.tsx
├── Chat/ChatModal.tsx
├── Chat/ChatHistory.tsx (via ChatModal)
├── TokenUsage/TokenCounter.tsx
├── Brief/BriefModal.tsx → Brief/DailyBrief.tsx
├── Onboarding/Onboarding.tsx
└── Menu/HamburgerMenu.tsx
    ├── ConnectionsPanel.tsx → ContactsSection
    ├── DailyReviewPanel.tsx
    ├── DraftsPanel.tsx
    ├── SettingsPanel.tsx → AIProvidersSection, EmbeddingsSection, ScheduledTasksSection
    └── SuperchargePanel.tsx
```

No orphaned component files found.

---

## SUMMARY STATS

| Metric | Count |
|--------|-------|
| Total API routes (all routers) | ~67 |
| Routes with no frontend caller | 4 |
| Dead frontend components | 0 |
| Backend routers | 14 (one registered twice) |
| Tables in current schema | 18 |
| Tables missing from `init.sql` | 10 |
| Columns missing from `init.sql` | 9 |
| Services bypassing provider routing | 2 (`digest_service`, `contact_service`) |
| God modules | 3 (`obsidian_service`, `chat.py` router, `gmail_service`) |
| Duplicate router registrations | 1 (`contacts.router`) |
| Non-existent files referenced in CLAUDE.md | 1 (`elevenlabs_service.py`) |

### Routes with no frontend caller (detail)

| Route | File | Status |
|-------|------|--------|
| `POST /obsidian/append` | `routers/obsidian.py` | Safe to delete |
| `GET /calendar/today/{account_id}` | `routers/calendar.py` | Safe to delete |
| `GET /calendar/upcoming/{account_id}` | `routers/calendar.py` | Safe to delete |
| `POST /calendar/events` | `routers/calendar.py` | Keep — internal action protocol only |
