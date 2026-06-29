import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { FiChevronRight } from 'react-icons/fi'
import { useNavigate } from 'react-router-dom'

import { api, type Draft } from '../../api/client'

/**
 * Drafts list: every reply Meridian drafted in the user's voice. Drafts are
 * generated from chat ("draft a reply to …") or from the Inbox ("Approve &
 * Generate Draft") and land here as pending. Clicking one opens the detail
 * editor at /drafts/:id where it can be edited and sent.
 */
export function DraftsPanel() {
  const navigate = useNavigate()
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
        {drafts.map((draft) => {
          const firstLine =
            (draft.body ?? '').split('\n').find((line) => line.trim()) ?? ''
          return (
            <motion.button
              key={draft.id}
              layout
              type="button"
              onClick={() => navigate(`/drafts/${draft.id}`)}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              transition={{ duration: 0.2 }}
              className="flex items-center gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-left transition-colors hover:bg-white/[0.08]"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-white/80">
                  To: {draft.to_email ?? '(no recipient)'}
                </p>
                <p className="truncate text-sm font-medium text-white">
                  {draft.subject || '(no subject)'}
                </p>
                <p className="mt-0.5 truncate text-xs text-white/40">{firstLine}</p>
              </div>
              <FiChevronRight size={16} className="shrink-0 text-white/40" />
            </motion.button>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

export default DraftsPanel
