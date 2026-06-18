import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  FiCheck,
  FiChevronDown,
  FiChevronUp,
  FiEdit2,
  FiSend,
  FiTrash2,
} from 'react-icons/fi'

import { api, type Draft } from '../../api/client'

/**
 * Drafts panel: review, edit, send, or discard the emails Meridian drafted in
 * the user's voice. Drafts are generated from chat ("draft a reply to …") and
 * land here as pending until the user acts on them.
 */
export function DraftsPanel() {
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .getDrafts()
      .then((result) => {
        if (active) setDrafts(result)
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const removeDraft = (id: number) =>
    setDrafts((current) => current.filter((draft) => draft.id !== id))

  const updateDraft = (updated: Draft) =>
    setDrafts((current) =>
      current.map((draft) => (draft.id === updated.id ? updated : draft)),
    )

  if (loading) {
    return <p className="py-10 text-center text-sm text-white/40">Loading drafts…</p>
  }

  if (error) {
    return <p className="py-10 text-center text-sm text-red-400/80">{error}</p>
  }

  if (drafts.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <p className="text-sm text-white/60">No pending drafts</p>
        <p className="text-xs text-white/30">Ask Meridian to draft an email.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <AnimatePresence initial={false}>
        {drafts.map((draft) => (
          <DraftRow
            key={draft.id}
            draft={draft}
            onSent={removeDraft}
            onDiscarded={removeDraft}
            onEdited={updateDraft}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}

interface DraftRowProps {
  draft: Draft
  onSent: (id: number) => void
  onDiscarded: (id: number) => void
  onEdited: (draft: Draft) => void
}

function DraftRow({ draft, onSent, onDiscarded, onEdited }: DraftRowProps) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(draft.body ?? '')
  const [busy, setBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)

  const firstLine = (draft.body ?? '').split('\n').find((line) => line.trim()) ?? ''

  const handleSend = async () => {
    setBusy(true)
    setRowError(null)
    try {
      await api.sendDraft(draft.id)
      onSent(draft.id)
    } catch (err) {
      setRowError((err as Error).message)
      setBusy(false)
    }
  }

  const handleDiscard = async () => {
    setBusy(true)
    setRowError(null)
    try {
      await api.discardDraft(draft.id)
      onDiscarded(draft.id)
    } catch (err) {
      setRowError((err as Error).message)
      setBusy(false)
    }
  }

  const handleSaveEdit = async () => {
    setBusy(true)
    setRowError(null)
    try {
      const updated = await api.editDraft(draft.id, body)
      onEdited(updated)
      setEditing(false)
    } catch (err) {
      setRowError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
      className="overflow-hidden rounded-2xl border border-white/10 bg-white/5"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-white/80">
            To: {draft.to_email ?? '(no recipient)'}
          </p>
          <p className="truncate text-sm font-medium text-white">
            {draft.subject || '(no subject)'}
          </p>
          {!expanded && (
            <p className="mt-0.5 truncate text-xs text-white/40">{firstLine}</p>
          )}
        </div>
        <span className="mt-0.5 shrink-0 text-white/40">
          {expanded ? <FiChevronUp size={16} /> : <FiChevronDown size={16} />}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="border-t border-white/10 px-4 py-3">
              {editing ? (
                <textarea
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  rows={8}
                  className="w-full resize-none rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/90 focus:border-white/20 focus:outline-none"
                />
              ) : (
                <p className="whitespace-pre-wrap text-sm text-white/70">
                  {draft.body}
                </p>
              )}

              {rowError && (
                <p className="mt-2 text-xs text-red-400/80">{rowError}</p>
              )}

              <div className="mt-3 flex items-center gap-2">
                {editing ? (
                  <button
                    type="button"
                    onClick={handleSaveEdit}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white/80 transition-colors hover:bg-white/15 disabled:opacity-40"
                  >
                    <FiCheck size={14} /> Save
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white/80 transition-colors hover:bg-white/15 disabled:opacity-40"
                  >
                    <FiEdit2 size={14} /> Edit
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={busy}
                  className="flex items-center gap-1.5 rounded-lg bg-green-500/20 px-3 py-1.5 text-xs text-green-300 transition-colors hover:bg-green-500/30 disabled:opacity-40"
                >
                  <FiSend size={14} /> Send
                </button>
                <button
                  type="button"
                  onClick={handleDiscard}
                  disabled={busy}
                  className="ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-white/50 transition-colors hover:bg-white/10 hover:text-white/80 disabled:opacity-40"
                >
                  <FiTrash2 size={14} /> Discard
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default DraftsPanel
