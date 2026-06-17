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

export const api = {
  baseUrl: API_URL,
  getAccounts: () => request<GmailAccount[]>('/gmail/accounts'),
  getAuthUrl: (label: string) =>
    request<{ url: string }>(`/gmail/auth?label=${encodeURIComponent(label)}`),
  sendMessage: (message: string, accountId?: number) =>
    request<ChatResponse>('/chat/message', {
      method: 'POST',
      body: JSON.stringify({ message, account_id: accountId ?? null }),
    }),
  getMessages: (limit = 50) =>
    request<StoredMessage[]>(`/chat/messages?limit=${limit}`),
  getTokensToday: () => request<TokensToday>('/chat/tokens/today'),
}
