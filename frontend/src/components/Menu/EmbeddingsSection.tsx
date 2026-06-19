import { useEffect, useRef, useState } from 'react'
import { FiAlertTriangle } from 'react-icons/fi'

import { api } from '../../api/client'

interface EmbeddingModel {
  model: string
  dim: number
  provider: string
}

/**
 * Memory & Embeddings settings: pick the embedding model and re-embed all data.
 * Re-embedding is destructive to existing vectors (it resizes columns when the
 * dimension changes), so it sits behind a confirmation step with live progress.
 */
export function EmbeddingsSection() {
  const [models, setModels] = useState<EmbeddingModel[]>([])
  const [selected, setSelected] = useState('voyage-3-lite')
  const [confirming, setConfirming] = useState(false)
  const [progress, setProgress] = useState<{ total: number; done: number; status: string } | null>(
    null,
  )
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api
      .getEmbeddingModels()
      .then(({ models: list }) => setModels(list))
      .catch(() => setModels([]))
    api
      .getSettings()
      .then((settings) => {
        if (settings.embedding_model) setSelected(settings.embedding_model)
      })
      .catch(() => {})
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const poll = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const next = await api.getRevectorizeProgress()
        setProgress(next)
        if (next.status === 'complete' || next.status === 'error') {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }, 2000)
  }

  const reembed = async () => {
    setConfirming(false)
    try {
      await api.revectorize(selected)
      setProgress({ total: 0, done: 0, status: 'running' })
      poll()
    } catch {
      setProgress({ total: 0, done: 0, status: 'error' })
    }
  }

  const current = models.find((m) => m.model === selected)
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm text-white/70">Memory &amp; Embeddings</span>

      <label className="flex flex-col gap-2">
        <span className="text-xs text-white/50">Embedding model</span>
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
        >
          {models.map((model) => (
            <option key={model.model} value={model.model} className="bg-[#0d0d0f]">
              {model.model} ({model.dim} dims · {model.provider})
            </option>
          ))}
        </select>
      </label>

      {confirming ? (
        <div className="flex flex-col gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-amber-200/90">
            <FiAlertTriangle size={14} />
            Re-embed all emails, notes, and contacts with{' '}
            <span className="font-medium">{current?.model}</span>?
          </div>
          <p className="text-xs text-white/40">
            This clears existing vectors and re-processes everything. It can take a while
            and may incur embedding-provider costs.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void reembed()}
              className="rounded-full bg-amber-400/90 px-3 py-1 text-xs font-medium text-black hover:bg-amber-400"
            >
              Confirm re-embed
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/70 hover:bg-white/10"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="flex items-center justify-center gap-2 rounded-xl border border-white/15 px-4 py-2 text-sm text-white/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          <FiAlertTriangle size={14} /> Re-embed all data
        </button>
      )}

      {progress && progress.status !== 'idle' && (
        <div className="flex flex-col gap-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-green-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-white/40">
            {progress.status === 'complete'
              ? 'Re-embed complete.'
              : progress.status === 'error'
                ? 'Re-embed failed — check the logs.'
                : `Re-embedding… ${progress.done}/${progress.total}`}
          </span>
        </div>
      )}
    </div>
  )
}

export default EmbeddingsSection
