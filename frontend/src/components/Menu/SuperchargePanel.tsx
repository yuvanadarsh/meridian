import { useEffect, useRef, useState } from 'react'
import { HiOutlineBolt } from 'react-icons/hi2'

import { api } from '../../api/client'
import type { SuperchargeImport } from '../../api/client'

/**
 * Supercharge: upload a Claude/ChatGPT/Gemini conversation export so its history
 * is parsed into the Obsidian vault and vectorized into Meridian's memory.
 */
export function SuperchargePanel() {
  const [imports, setImports] = useState<SuperchargeImport[]>([])
  const [active, setActive] = useState<SuperchargeImport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadImports = async () => {
    try {
      const { imports: list } = await api.getSuperchargeImports()
      setImports(list)
    } catch {
      // Non-fatal — the upload affordance still works.
    }
  }

  useEffect(() => {
    void loadImports()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const poll = (importId: number) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const progress = await api.getSuperchargeProgress(importId)
        setActive(progress)
        if (progress.status === 'complete' || progress.status === 'error') {
          if (pollRef.current) clearInterval(pollRef.current)
          void loadImports()
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
      }
    }, 1500)
  }

  const upload = async (file: File) => {
    setError(null)
    try {
      const result = await api.uploadSupercharge(file)
      setActive({
        id: result.import_id,
        provider: result.provider,
        filename: file.name,
        total_conversations: result.total_conversations,
        processed_conversations: 0,
        status: 'processing',
        created_at: new Date().toISOString(),
      })
      poll(result.import_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
  }

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void upload(file)
  }

  const pct =
    active && active.total_conversations > 0
      ? Math.round((active.processed_conversations / active.total_conversations) * 100)
      : 0

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <HiOutlineBolt size={18} className="text-amber-300/80" />
        <span className="text-sm font-medium text-white/80">Supercharge Memory</span>
      </div>
      <p className="text-sm text-white/50">
        Upload your AI conversation history to enrich Meridian's knowledge about you.
        Supported: Claude (conversations.json), ChatGPT (conversations.json), Gemini
        (Google Takeout).
      </p>

      {error && <p className="text-sm text-rose-300/80">{error}</p>}

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-8 text-sm transition-colors ${
          dragging
            ? 'border-amber-300/50 bg-amber-300/5 text-white'
            : 'border-white/15 text-white/60 hover:border-white/30 hover:text-white'
        }`}
      >
        <HiOutlineBolt size={24} className="text-white/40" />
        Drop file here or click to upload
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void upload(file)
          event.target.value = ''
        }}
      />

      {active && active.status !== 'complete' && (
        <div className="flex flex-col gap-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-amber-300 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-white/40">
            {active.status === 'error'
              ? 'Import failed — check the logs.'
              : `Processing ${active.processed_conversations}/${active.total_conversations} conversations…`}
          </span>
        </div>
      )}

      {active && active.status === 'complete' && (
        <p className="text-sm text-green-300/80">
          {active.total_conversations} conversations added to your vault.
        </p>
      )}

      {imports.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-white/40">Past imports</span>
          {imports.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2 text-xs"
            >
              <span className="text-white/70">
                {item.status === 'complete' ? '✓ ' : ''}
                {item.provider} export — {item.total_conversations} conversations
              </span>
              <span className="text-white/30">
                {new Date(item.created_at).toLocaleDateString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default SuperchargePanel
