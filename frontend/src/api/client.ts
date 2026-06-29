/**
 * Thin typed wrapper around the Meridian API. All backend calls go through
 * `request`, which normalizes the `{ error, detail }` error shape the API
 * returns on failure.
 */

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

interface ApiError {
  error?: string
  detail?: string
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    ...options,
  })

  if (!response.ok) {
    let message = response.statusText
    try {
      const body = (await response.json()) as ApiError
      message = body.detail ?? body.error ?? message
    } catch {
      // Response body was not JSON — keep the status text.
    }
    throw new Error(message)
  }

  return (await response.json()) as T
}

export interface GmailAccount {
  id: number
  email: string
  label: string | null
  last_synced_at: string | null
  sweep_status: string // idle | running | classifying | triage_complete | completed | error
  auth_status: 'ok' | 'expired' // 'expired' when the stored token has been revoked
}

export interface ChatResponse {
  response: string
  tokens: { input: number; output: number; total: number }
}

export interface TokensToday {
  total: number
  input: number
  output: number
}

export interface StoredMessage {
  role: 'user' | 'assistant'
  content: string
  created_at: string | null
}

export type SweepMode = 'all' | 'count' | 'since'

export interface SweepOptions {
  mode: SweepMode
  count?: number | null
  since_date?: string | null
}

export interface SweepProgress {
  status: string // idle | running | classifying | triage_complete | completed | error
  fetched: number
  total_estimated: number
  stored: number
  skipped: number
  error?: string | null
}

export interface TriageCounts {
  trash: number
  archive: number
  keep: number
  pending: number
}

export type TriageStatus = 'trash' | 'archive' | 'keep'

export interface TriageEmail {
  id: number
  from_address: string | null
  subject: string | null
  summary: string | null
  received_at: string | null
}

export interface TriageOverride {
  id: number
  status: TriageStatus
}

export interface TriageBulkChange {
  email_id: number
  triage_status: TriageStatus
}

export interface Draft {
  id: number
  account_id: number | null
  to_email: string | null
  subject: string | null
  body: string | null
  thread_email_id: number | null
  status: string
  created_at: string
  updated_at: string
}

export type QueueClassification = 'trash' | 'archive' | 'keep' | 'draft'

export type DraftStatus = 'generating' | 'ready' | 'sent' | null

export interface QueueItem {
  id: number
  email_id: number
  classification: QueueClassification
  ai_summary: string | null
  needs_draft: boolean
  draft_id: number | null
  draft_status: DraftStatus
  created_at: string
  subject: string | null
  from_address: string | null
  received_at: string | null
  snippet: string | null
}

export interface QueueSummary {
  trash: number
  archive: number
  keep: number
  draft: number
  total: number
}

export interface SuperchargeUpload {
  import_id: number
  provider: string
  total_conversations: number
}

export interface SuperchargeImport {
  id: number
  provider: string
  filename: string | null
  total_conversations: number
  processed_conversations: number
  status: string
  created_at: string
}

export interface AIProvider {
  provider: string
  has_key: boolean
  // 'configured' = stored in DB, 'env' = supplied via .env, null = not set.
  key_source?: 'configured' | 'env' | null
  base_url: string | null
  is_active: boolean
  model_chat: string | null
  model_classify: string | null
  model_draft: string | null
}

export interface ProviderPatch {
  api_key?: string
  base_url?: string
  model_chat?: string
  model_classify?: string
  model_draft?: string
  activate?: boolean
}

export interface Contact {
  email_address: string
  display_name: string | null
  email_count: number
  sent_count: number
  received_count: number
  first_contacted: string | null
  last_contacted: string | null
  topics: string[] | null
}

export interface CalendarEvent {
  id: number
  title: string | null
  start_time: string | null
  end_time: string | null
  meet_link: string | null
  // Local YYYY-MM-DD bucket key, set by GET /calendar/range for the week view.
  day?: string | null
}

export interface PersistentChatSummary {
  id: string
  title: string | null
  auto_titled: boolean
  created_at: string
  updated_at: string
}

export interface PersistentChatMessage {
  role: 'user' | 'assistant'
  content: string
  created_at?: string | null
}

export interface PersistentChat extends PersistentChatSummary {
  obsidian_note_path: string | null
  messages: PersistentChatMessage[]
}

export interface UsageHistoryPoint {
  label: string
  anthropic_input: number
  anthropic_output: number
  anthropic_cost: number
  voyageai_tokens: number
  voyageai_cost: number
  elevenlabs_chars: number
  elevenlabs_cost: number
  total_cost: number
}

export interface UsageHistory {
  timeframe: string
  data: UsageHistoryPoint[]
  totals: {
    total_cost: number
    anthropic_cost: number
    voyageai_cost: number
    elevenlabs_cost: number
  }
}

export type UsageTimeframe = 'daily' | 'weekly' | 'monthly' | 'yearly'

export interface ScheduledTask {
  id: number
  task_key: string
  display_name: string | null
  schedule_time: string
  schedule_days: string
  enabled: boolean
  last_run_at: string | null
  last_run_status: string | null
  last_run_summary: string | null
}

export interface AvailableTask {
  key: string
  name: string
  description: string
  default_schedule: string
  default_days: string
}

export interface TaskCreate {
  task_key: string
  display_name?: string
  schedule_time?: string
  schedule_days?: string
}

export interface TaskPatch {
  display_name?: string
  schedule_time?: string
  schedule_days?: string
  enabled?: boolean
}

export const api = {
  baseUrl: API_URL,
  getAccounts: () => request<GmailAccount[]>('/gmail/accounts'),
  getAuthUrl: (label: string) =>
    request<{ url: string }>(`/gmail/auth?label=${encodeURIComponent(label)}`),
  reauthAccount: (accountId: number) => {
    // Navigate directly — the endpoint returns a redirect to Google.
    window.location.assign(`${API_URL}/gmail/reauth/${accountId}`)
  },
  updateAccount: (accountId: number, label: string) =>
    request<GmailAccount>(`/gmail/accounts/${accountId}`, {
      method: 'PATCH',
      body: JSON.stringify({ label }),
    }),
  deleteAccount: (accountId: number) =>
    request<{ deleted: boolean }>(`/gmail/accounts/${accountId}`, { method: 'DELETE' }),
  sendMessage: (message: string, accountId?: number) =>
    request<ChatResponse>('/chat/message', {
      method: 'POST',
      body: JSON.stringify({ message, account_id: accountId ?? null }),
    }),
  getMessages: (limit = 50) =>
    request<StoredMessage[]>(`/chat/messages?limit=${limit}`),
  /** @deprecated Use getUsageToday() instead. */
  getTokensToday: () => request<TokensToday>('/chat/tokens/today'),

  // Onboarding — sweep
  getEstimate: (accountId: number) =>
    request<{ estimated_count: number }>(`/gmail/estimate/${accountId}`),
  startSweep: (accountId: number, options: SweepOptions) =>
    request<{ status: string; account_id: number }>(`/gmail/sweep/${accountId}`, {
      method: 'POST',
      body: JSON.stringify(options),
    }),
  getSweepProgress: (accountId: number) =>
    request<SweepProgress>(`/gmail/sweep/progress/${accountId}`),
  getTriageResults: (accountId: number) =>
    request<{ counts: TriageCounts }>(`/gmail/triage/results/${accountId}`),
  getTriageEmails: (accountId: number, status: TriageStatus, limit = 50, offset = 0) =>
    request<{ emails: TriageEmail[] }>(
      `/gmail/triage/emails/${accountId}?status=${status}&limit=${limit}&offset=${offset}`,
    ),
  approveTriage: (accountId: number, overrides: TriageOverride[]) =>
    request<{ trashed: number; archived: number }>(`/gmail/triage/approve/${accountId}`, {
      method: 'POST',
      body: JSON.stringify({ overrides }),
    }),
  discardSweep: (accountId: number) =>
    request<{ discarded: number }>(`/gmail/triage/discard/${accountId}`, { method: 'POST' }),
  bulkUpdateTriage: (changes: TriageBulkChange[]) =>
    request<{ updated: number }>('/gmail/emails/triage/bulk', {
      method: 'PATCH',
      body: JSON.stringify({ changes }),
    }),
  getTriageReport: async (accountId: number): Promise<string> => {
    const response = await fetch(`${API_URL}/gmail/triage/report/${accountId}`)
    if (!response.ok) throw new Error('Could not generate the report')
    return response.text()
  },

  // Calendar
  syncCalendar: (accountId: number) =>
    request<{ synced: number }>(`/calendar/sync/${accountId}`, { method: 'POST' }),

  // Onboarding — vectorization
  startVectorize: (accountId: number) =>
    request<{ status: string; account_id: number }>(`/gmail/vectorize/${accountId}`, {
      method: 'POST',
    }),
  getVectorizeProgress: (accountId: number) =>
    request<{ vectorized: number; total: number }>(`/gmail/vectorize/progress/${accountId}`),

  // Drafts
  getDrafts: () => request<Draft[]>('/drafts'),
  getDraft: (draftId: number | string) => request<Draft>(`/drafts/${draftId}`),
  editDraft: (draftId: number | string, body: string) =>
    request<Draft>(`/drafts/${draftId}`, {
      method: 'PATCH',
      body: JSON.stringify({ body }),
    }),
  // Sends a draft. When `body` is given, the edit is persisted first so the
  // sent email reflects any inline changes from the detail page.
  sendDraft: async (
    draftId: number | string,
    opts?: { body?: string },
  ): Promise<Draft> => {
    if (opts?.body !== undefined) {
      await request<Draft>(`/drafts/${draftId}`, {
        method: 'PATCH',
        body: JSON.stringify({ body: opts.body }),
      })
    }
    return request<Draft>(`/drafts/${draftId}/send`, { method: 'POST' })
  },
  discardDraft: (draftId: number | string) =>
    request<{ status: string; id: number }>(`/drafts/${draftId}`, { method: 'DELETE' }),

  // Inbox queue
  getInboxQueue: () => request<QueueItem[]>('/inbox/queue'),
  getInboxSummary: () => request<QueueSummary>('/inbox/queue/summary'),
  triggerInbox: () =>
    request<{ result: { status: string; summary: string }; queue: QueueItem[] }>(
      '/inbox/trigger',
    ),
  approveInbox: (ids: number[], overrides: Record<string, string> = {}) =>
    request<{ approved: number; trashed: number; archived: number }>('/inbox/approve', {
      method: 'POST',
      body: JSON.stringify({ ids, overrides }),
    }),
  generateDraftFromQueue: (id: number) =>
    request<{ draft_id: number; status: string }>(
      `/inbox/queue/${id}/generate-draft`,
      { method: 'POST' },
    ),
  dismissQueueItem: (id: number) =>
    request<{ dismissed: boolean; id: number }>(`/inbox/queue/${id}`, {
      method: 'DELETE',
    }),

  // Threads
  buildThreads: (accountId: number) =>
    request<{ status: string; account_id: number }>(`/gmail/threads/build/${accountId}`, {
      method: 'POST',
    }),
  getThreadsProgress: (accountId: number) =>
    request<{ processed: number; total: number }>(`/gmail/threads/build/progress/${accountId}`),
  getThreadsCount: (accountId: number) =>
    request<{ processed: number; total: number }>(`/gmail/threads/count/${accountId}`),

  // Contacts
  buildContactGraph: (accountId: number) =>
    request<{ status: string; account_id: number }>(`/contacts/build/${accountId}`, {
      method: 'POST',
    }),
  getContacts: (limit = 500) =>
    request<{ contacts: Contact[] }>(`/contacts?limit=${limit}`),
  searchContacts: (query: string) =>
    request<{ contacts: Contact[] }>(`/contacts/search?q=${encodeURIComponent(query)}`),

  // Settings
  getSettings: () => request<Record<string, string>>('/settings'),
  updateSetting: (key: string, value: string) =>
    request<Record<string, string>>('/settings', {
      method: 'PATCH',
      body: JSON.stringify({ key, value }),
    }),

  // AI providers
  getProviders: () => request<{ providers: AIProvider[] }>('/settings/providers'),
  updateProvider: (provider: string, patch: ProviderPatch) =>
    request<{ providers: AIProvider[] }>(`/settings/providers/${provider}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteProviderKey: (provider: string) =>
    request<{ providers: AIProvider[] }>(`/settings/providers/${provider}/key`, {
      method: 'DELETE',
    }),

  // Embeddings
  getEmbeddingModels: () =>
    request<{ models: { model: string; dim: number; provider: string }[] }>(
      '/settings/embedding-models',
    ),
  revectorize: (model: string) =>
    request<{ queued: boolean }>('/settings/revectorize', {
      method: 'POST',
      body: JSON.stringify({ model }),
    }),
  getRevectorizeProgress: () =>
    request<{ total: number; done: number; status: string }>('/settings/revectorize/progress'),

  // Supercharge
  uploadSupercharge: async (file: File): Promise<SuperchargeUpload> => {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${API_URL}/supercharge/upload`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      let message = response.statusText
      try {
        const body = (await response.json()) as ApiError
        message = body.detail ?? body.error ?? message
      } catch {
        // keep status text
      }
      throw new Error(message)
    }
    return (await response.json()) as SuperchargeUpload
  },
  getSuperchargeProgress: (importId: number) =>
    request<SuperchargeImport>(`/supercharge/progress/${importId}`),
  getSuperchargeImports: () =>
    request<{ imports: SuperchargeImport[] }>('/supercharge'),

  // Obsidian export
  exportThreadsToObsidian: (accountId: number) =>
    request<{ status: string; account_id: number }>(
      `/gmail/threads/export-to-obsidian/${accountId}`,
      { method: 'POST' },
    ),
  getObsidianExportProgress: (accountId: number) =>
    request<{ processed: number; total: number; done?: boolean }>(
      `/gmail/threads/obsidian-export/progress/${accountId}`,
    ),
  exportContactsToObsidian: () =>
    request<{ status: string }>('/contacts/export-to-obsidian', { method: 'POST' }),
  getContactsObsidianExportProgress: () =>
    request<{ processed: number; total: number; done?: boolean }>(
      '/contacts/obsidian-export/progress',
    ),

  // Usage tracking
  getUsageToday: () =>
    request<{
      total_tokens_today: number
      total_cost_today: number
      total_cost_month: number
      by_provider: Record<
        string,
        {
          model: string
          types: Record<string, { units: number; cost_usd: number }>
          total_cost: number
        }
      >
    }>('/usage/today'),

  // Calendar — all accounts
  getCalendarToday: () => request<{ events: CalendarEvent[] }>('/calendar/today'),
  getCalendarRange: (start: string, end: string) =>
    request<{ events: CalendarEvent[] }>(
      `/calendar/range?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    ),

  // Usage history (analytics charts)
  getUsageHistory: (timeframe: UsageTimeframe) =>
    request<UsageHistory>(`/usage/history?timeframe=${timeframe}`),

  // Persistent chats
  createPersistentChat: () =>
    request<PersistentChatSummary>('/persistent-chats', { method: 'POST' }),
  listPersistentChats: () =>
    request<{ chats: PersistentChatSummary[] }>('/persistent-chats'),
  getPersistentChat: (id: string) =>
    request<PersistentChat>(`/persistent-chats/${id}`),
  deletePersistentChat: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/persistent-chats/${id}`, {
      method: 'DELETE',
    }),
  renamePersistentChat: (id: string, title: string) =>
    request<{ id: string; title: string }>(`/persistent-chats/${id}/title`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
  sendPersistentChatMessage: (id: string, content: string) =>
    request<{ content: string; title: string | null }>(
      `/persistent-chats/${id}/messages`,
      { method: 'POST', body: JSON.stringify({ content }) },
    ),

  // Scheduled tasks
  getTasks: () => request<{ tasks: ScheduledTask[] }>('/tasks'),
  getAvailableTasks: () => request<{ tasks: AvailableTask[] }>('/tasks/available'),
  createTask: (payload: TaskCreate) =>
    request<ScheduledTask>('/tasks', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateTask: (id: number, patch: TaskPatch) =>
    request<ScheduledTask>(`/tasks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteTask: (id: number) =>
    request<{ deleted: boolean; id: number }>(`/tasks/${id}`, { method: 'DELETE' }),
}
