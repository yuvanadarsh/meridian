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

export const api = {
  baseUrl: API_URL,
  getAccounts: () => request<GmailAccount[]>('/gmail/accounts'),
  getAuthUrl: (label: string) =>
    request<{ url: string }>(`/gmail/auth?label=${encodeURIComponent(label)}`),
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
  getTriageReport: async (accountId: number): Promise<string> => {
    const response = await fetch(`${API_URL}/gmail/triage/report/${accountId}`)
    if (!response.ok) throw new Error('Could not generate the report')
    return response.text()
  },

  // Onboarding — vectorization
  startVectorize: (accountId: number) =>
    request<{ status: string; account_id: number }>(`/gmail/vectorize/${accountId}`, {
      method: 'POST',
    }),
  getVectorizeProgress: (accountId: number) =>
    request<{ vectorized: number; total: number }>(`/gmail/vectorize/progress/${accountId}`),
}
