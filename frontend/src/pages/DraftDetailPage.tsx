import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  HiOutlineArrowLeft,
  HiOutlineCheckCircle,
} from 'react-icons/hi2'

import { api } from '../api/client'
import type { Draft } from '../api/client'

/**
 * Single-draft editor. Loads a draft by id, lets the user edit the body inline,
 * and sends it — which persists the edit, mails it via Gmail, and records the
 * sent email to the Obsidian vault on the backend before returning.
 */
export function DraftDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let active = true
    api
      .getDraft(id)
      .then((result) => {
        if (!active) return
        setDraft(result)
        setBody(result.body ?? '')
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [id])

  const handleSend = async () => {
    if (!id) return
    setSending(true)
    setError(null)
    try {
      await api.sendDraft(id, { body })
      setSent(true)
      window.setTimeout(() => navigate('/drafts'), 2000)
    } catch (err) {
      setError((err as Error).message)
      setSending(false)
    }
  }

  if (error && !draft) {
    return <div className="p-8 text-sm text-red-400/80">{error}</div>
  }

  if (!draft) {
    return <div className="p-8 text-sm text-white/30">Loading…</div>
  }

  if (sent) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <HiOutlineCheckCircle className="mx-auto mb-3 h-12 w-12 text-green-400" />
          <div className="font-medium text-white">Sent and saved to memory</div>
          <div className="mt-1 text-sm text-white/40">Redirecting to drafts…</div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-white/5 px-8 py-4">
        <button
          type="button"
          onClick={() => navigate('/drafts')}
          className="text-white/40 transition-colors hover:text-white"
        >
          <HiOutlineArrowLeft className="h-5 w-5" />
        </button>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-white">
            {draft.subject || '(no subject)'}
          </div>
          <div className="truncate text-xs text-white/40">
            To: {draft.to_email || '(no recipient)'}
          </div>
        </div>
      </div>

      {/* Editable body */}
      <div className="flex-1 px-8 py-6">
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          className="h-full w-full resize-none bg-transparent text-sm leading-relaxed text-white/80 outline-none"
        />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-white/5 px-8 py-4">
        {error ? (
          <span className="text-xs text-red-400/80">{error}</span>
        ) : (
          <button
            type="button"
            onClick={() => navigate('/drafts')}
            className="text-sm text-white/40 transition-colors hover:text-white/60"
          >
            Discard
          </button>
        )}
        <button
          type="button"
          onClick={handleSend}
          disabled={sending}
          className="rounded-xl bg-white px-6 py-2 text-sm font-medium text-black transition-colors hover:bg-white/90 disabled:opacity-50"
        >
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}

export default DraftDetailPage
