import { useEffect, useState } from 'react'
import { FiCheck, FiChevronDown, FiPlus, FiX } from 'react-icons/fi'

import { api } from '../../api/client'
import type { AIProvider } from '../../api/client'

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Gemini',
  deepseek: 'DeepSeek',
  ollama: 'Ollama (local)',
}

function displayName(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1)
}

/**
 * AI Providers settings: lists only configured providers (those with a key set)
 * plus Anthropic (always shown, key comes from .env). Supports adding a new
 * provider, editing keys, activating one at a time, and per-task model config.
 *
 * Keys are write-only — the backend never returns them in plaintext.
 */
export function AIProvidersSection() {
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [modelsOpen, setModelsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // "+ Add provider" inline form state
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKey, setNewKey] = useState('')
  const [newUrl, setNewUrl] = useState('')

  const load = async () => {
    try {
      const { providers: list } = await api.getProviders()
      // Backend already filters to configured + Anthropic-from-env — use as-is.
      setProviders(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load providers')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const active = providers.find((p) => p.is_active)

  const saveKey = async (provider: string) => {
    const trimmed = keyInput.trim()
    if (!trimmed) return
    try {
      const isOllama = provider === 'ollama'
      const patch = isOllama ? { base_url: trimmed } : { api_key: trimmed }
      const { providers: list } = await api.updateProvider(provider, patch)
      setProviders(list)
      setEditing(null)
      setKeyInput('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save key')
    }
  }

  const addProvider = async () => {
    const providerKey = newName.trim().toLowerCase().replace(/\s+/g, '_')
    const key = newKey.trim()
    if (!providerKey || !key) return
    try {
      const patch: { api_key: string; base_url?: string } = { api_key: key }
      if (newUrl.trim()) patch.base_url = newUrl.trim()
      const { providers: list } = await api.updateProvider(providerKey, patch)
      setProviders(list)
      setAdding(false)
      setNewName('')
      setNewKey('')
      setNewUrl('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add provider')
    }
  }

  const activate = async (provider: string) => {
    try {
      await api.updateProvider(provider, { activate: true })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not activate provider')
    }
  }

  const updateModel = async (
    field: 'model_chat' | 'model_classify' | 'model_draft',
    value: string,
  ) => {
    if (!active) return
    try {
      await api.updateProvider(active.provider, { [field]: value })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update model')
    }
  }

  const cancelAdd = () => {
    setAdding(false)
    setNewName('')
    setNewKey('')
    setNewUrl('')
  }

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm text-white/70">AI Providers</span>
      {error && <p className="text-xs text-rose-300/80">{error}</p>}

      <div className="flex flex-col gap-2">
        {providers.map((provider) => {
          const isOllama = provider.provider === 'ollama'
          const configured = isOllama ? Boolean(provider.base_url) : provider.has_key
          const isEditing = editing === provider.provider

          return (
            <div
              key={provider.provider}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                {/* Left: radio indicator + provider name + active badge */}
                <div className="flex items-center gap-2">
                  <span className="flex shrink-0 items-center">
                    {provider.is_active ? (
                      <FiCheck size={14} className="text-green-400" />
                    ) : (
                      <span className="h-3.5 w-3.5 rounded-full border border-white/20" />
                    )}
                  </span>
                  <span className="text-sm text-white">{displayName(provider.provider)}</span>
                  {provider.is_active && (
                    <span className="text-xs text-green-400/70">Active</span>
                  )}
                </div>

                {/* Right: action buttons */}
                <div className="flex items-center gap-2">
                  {!provider.is_active && configured && (
                    <button
                      type="button"
                      onClick={() => void activate(provider.provider)}
                      className="text-xs text-white/40 hover:text-white"
                    >
                      Set active
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(isEditing ? null : provider.provider)
                      setKeyInput('')
                    }}
                    className="text-xs text-white/50 hover:text-white"
                  >
                    {configured ? 'Edit' : isOllama ? 'Configure' : 'Add key'}
                  </button>
                </div>
              </div>

              {/* Key status line */}
              <div
                className={`mt-0.5 text-xs ${
                  provider.key_source === 'env' ? 'text-green-400/80' : 'text-white/30'
                }`}
              >
                {isOllama
                  ? provider.base_url || 'URL not set'
                  : provider.key_source === 'env'
                    ? 'key: set via .env'
                    : configured
                      ? 'key: ••••••••••••'
                      : 'key: not set'}
              </div>

              {/* Inline edit form */}
              {isEditing && (
                <div className="mt-2 flex items-center gap-2">
                  <input
                    autoFocus
                    type={isOllama ? 'text' : 'password'}
                    value={keyInput}
                    onChange={(event) => setKeyInput(event.target.value)}
                    onKeyDown={(event) =>
                      event.key === 'Enter' && void saveKey(provider.provider)
                    }
                    placeholder={isOllama ? 'http://localhost:11434' : 'Paste API key'}
                    aria-label={`${displayName(provider.provider)} ${isOllama ? 'URL' : 'API key'}`}
                    className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => void saveKey(provider.provider)}
                    disabled={!keyInput.trim()}
                    className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
                  >
                    Save
                  </button>
                </div>
              )}
            </div>
          )
        })}

        {/* Add provider — inline form or trigger button */}
        {adding ? (
          <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2.5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-white/60">Add provider</span>
              <button
                type="button"
                onClick={cancelAdd}
                aria-label="Cancel"
                className="text-white/40 hover:text-white"
              >
                <FiX size={14} />
              </button>
            </div>
            <div className="flex flex-col gap-2">
              <input
                autoFocus
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder='Provider name (e.g. "OpenAI", "Gemini")'
                aria-label="Provider name"
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
              />
              <input
                type="password"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="API key"
                aria-label="API key"
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
              />
              <input
                type="text"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                placeholder="Base URL (optional — for Ollama or custom endpoints)"
                aria-label="Base URL"
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void addProvider()}
                  disabled={!newName.trim() || !newKey.trim()}
                  className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={cancelAdd}
                  className="text-xs text-white/40 hover:text-white"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-white/15 px-3 py-2 text-xs text-white/50 transition-colors hover:border-white/30 hover:text-white"
          >
            <FiPlus size={14} /> Add provider
          </button>
        )}
      </div>

      {/* Per-task model configuration for the active provider */}
      {active && (
        <div className="rounded-xl border border-white/10 bg-white/5">
          <button
            type="button"
            onClick={() => setModelsOpen((open) => !open)}
            className="flex w-full items-center justify-between px-3 py-2 text-xs text-white/60 hover:text-white"
          >
            <span>Model configuration · {displayName(active.provider)}</span>
            <FiChevronDown
              size={14}
              className={`transition-transform ${modelsOpen ? 'rotate-180' : ''}`}
            />
          </button>
          {modelsOpen && (
            <div className="flex flex-col gap-2 border-t border-white/[0.06] px-3 py-3">
              {(
                [
                  ['model_chat', 'Chat'],
                  ['model_classify', 'Classification'],
                  ['model_draft', 'Drafting'],
                ] as const
              ).map(([field, label]) => (
                <label key={field} className="flex items-center gap-2 text-xs text-white/60">
                  <span className="w-24 shrink-0">{label}</span>
                  <input
                    defaultValue={active[field] ?? ''}
                    onBlur={(event) => void updateModel(field, event.target.value)}
                    className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white focus:border-white/30 focus:outline-none"
                  />
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default AIProvidersSection
