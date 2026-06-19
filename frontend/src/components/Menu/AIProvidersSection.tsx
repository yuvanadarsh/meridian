import { useEffect, useState } from 'react'
import { FiCheck, FiChevronDown } from 'react-icons/fi'

import { api } from '../../api/client'
import type { AIProvider } from '../../api/client'

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Gemini',
  deepseek: 'DeepSeek',
  ollama: 'Ollama (local)',
}

// The order/shape of providers we always show, even before any row is created.
const PROVIDER_ORDER = ['anthropic', 'openai', 'gemini', 'deepseek', 'ollama']

function byOrder(a: AIProvider, b: AIProvider) {
  return PROVIDER_ORDER.indexOf(a.provider) - PROVIDER_ORDER.indexOf(b.provider)
}

/**
 * AI Providers settings: list each provider, add/edit its API key (or base URL
 * for Ollama), activate one at a time, and expand per-task model configuration.
 * Keys are write-only — the backend only ever reports whether a key is set.
 */
export function AIProvidersSection() {
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [modelsOpen, setModelsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      const { providers: list } = await api.getProviders()
      // Merge backend rows with the full known list so unconfigured ones show.
      const byName = new Map(list.map((p) => [p.provider, p]))
      const merged = PROVIDER_ORDER.map(
        (name): AIProvider =>
          byName.get(name) ?? {
            provider: name,
            has_key: false,
            base_url: null,
            is_active: false,
            model_chat: null,
            model_classify: null,
            model_draft: null,
          },
      )
      setProviders(merged.sort(byOrder))
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
      // Ollama stores a base URL rather than an API key.
      const patch = provider === 'ollama' ? { base_url: trimmed } : { api_key: trimmed }
      const { providers: list } = await api.updateProvider(provider, patch)
      setProviders(
        PROVIDER_ORDER.map(
          (name): AIProvider =>
            list.find((p) => p.provider === name) ?? {
              provider: name,
              has_key: false,
              base_url: null,
              is_active: false,
              model_chat: null,
              model_classify: null,
              model_draft: null,
            },
        ).sort(byOrder),
      )
      setEditing(null)
      setKeyInput('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save key')
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
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={!configured || provider.is_active}
                    onClick={() => void activate(provider.provider)}
                    title={configured ? 'Make active' : 'Add a key first'}
                    className="flex items-center gap-1.5 text-sm text-white disabled:cursor-default"
                  >
                    {provider.is_active ? (
                      <FiCheck size={14} className="text-green-400" />
                    ) : (
                      <span className="h-3.5 w-3.5 rounded-full border border-white/20" />
                    )}
                    {PROVIDER_LABELS[provider.provider]}
                  </button>
                </div>
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

              <div className="mt-0.5 text-xs text-white/30">
                {isOllama
                  ? provider.base_url || 'URL not set'
                  : configured
                    ? 'key: ••••••••••••'
                    : 'key: not set'}
              </div>

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
                    aria-label={`${PROVIDER_LABELS[provider.provider]} ${isOllama ? 'URL' : 'API key'}`}
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
      </div>

      {/* Per-task model configuration for the active provider */}
      {active && (
        <div className="rounded-xl border border-white/10 bg-white/5">
          <button
            type="button"
            onClick={() => setModelsOpen((open) => !open)}
            className="flex w-full items-center justify-between px-3 py-2 text-xs text-white/60 hover:text-white"
          >
            <span>Model configuration · {PROVIDER_LABELS[active.provider]}</span>
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
