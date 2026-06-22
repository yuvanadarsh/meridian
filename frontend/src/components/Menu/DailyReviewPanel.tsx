import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { FiCalendar, FiCheck, FiChevronDown, FiMail, FiX } from 'react-icons/fi'
import { HiOutlineInbox } from 'react-icons/hi2'

import { api, type DailyReview, type ReviewEmail } from '../../api/client'
import { useMeridianStore } from '../../store/meridianStore'

function formatDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`)
  return date.toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatReceived(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function suggestedAction(email: ReviewEmail): string {
  if (email.classification === 'trash') return 'Trash — no action needed'
  if (email.draft_id !== null) return 'Keep — draft reply queued'
  if (email.needs_reply) return 'Keep — reply needed'
  if (email.calendar_suggestion?.detected) return 'Keep — schedule a meeting'
  if (email.classification === 'archive') return 'Archive — no reply needed'
  return 'Keep'
}

/**
 * Daily Review panel: a newspaper-style digest of the afternoon email review.
 * Emails are grouped into Action Required (need a reply / have a queued draft),
 * FYI (archived automatically), and Cleaned Up (trashed). The user approves all
 * to push triage to Gmail, or dismisses without action.
 *
 * Cards expand on click to show full detail. Dismissed reviews remain viewable
 * (read-only) with a Reopen button and a fresh "Run review now" option.
 */
export function DailyReviewPanel() {
  const [review, setReview] = useState<DailyReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const setActivePanel = useMeridianStore((state) => state.setActivePanel)
  const setMenuOpen = useMeridianStore((state) => state.setMenuOpen)
  const setChatOpen = useMeridianStore((state) => state.setChatOpen)
  const setChatPrefill = useMeridianStore((state) => state.setChatPrefill)

  const addToCalendar = (email: ReviewEmail) => {
    const who = email.from || 'them'
    const about = email.subject ? ` about "${email.subject}"` : ''
    setChatPrefill(`Schedule a meeting with ${who}${about}.`)
    setActivePanel(null)
    setMenuOpen(false)
    setChatOpen(true)
  }

  const load = async () => {
    try {
      const { review: result } = await api.getReview()
      setReview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load review')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const runNow = async () => {
    setBusy(true)
    setError(null)
    setExpandedId(null)
    try {
      const { review: result } = await api.triggerReview()
      setReview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run review')
    } finally {
      setBusy(false)
    }
  }

  const approveAll = async () => {
    setBusy(true)
    setError(null)
    try {
      const { review: result } = await api.approveReview()
      setReview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not approve review')
    } finally {
      setBusy(false)
    }
  }

  const dismiss = async () => {
    setBusy(true)
    setError(null)
    try {
      const { review: result } = await api.dismissReview()
      setReview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not dismiss review')
    } finally {
      setBusy(false)
    }
  }

  const reopen = async () => {
    setBusy(true)
    setError(null)
    try {
      const { review: result } = await api.reopenReview()
      setReview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reopen review')
    } finally {
      setBusy(false)
    }
  }

  const toggleCard = (id: number) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  const groups = useMemo(() => {
    const emails = review?.emails ?? []
    const actionRequired = emails.filter(
      (email) =>
        email.needs_reply ||
        email.draft_id !== null ||
        email.calendar_suggestion?.detected,
    )
    const actionIds = new Set(actionRequired.map((email) => email.email_id))
    const fyi = emails.filter(
      (email) => email.classification === 'archive' && !actionIds.has(email.email_id),
    )
    const trashed = emails.filter((email) => email.classification === 'trash')
    const archivedCount = emails.filter((email) => email.classification === 'archive').length
    return { actionRequired, fyi, trashed, archivedCount }
  }, [review])

  if (loading) {
    return <p className="py-10 text-center text-sm text-white/40">Loading review…</p>
  }

  // Empty state — review hasn't run yet today.
  if (!review) {
    return (
      <div className="flex flex-col items-center gap-3 py-12 text-center">
        <HiOutlineInbox size={32} className="text-white/30" />
        <div>
          <p className="text-sm text-white/70">No review ready yet.</p>
          <p className="mt-0.5 text-xs text-white/40">Your afternoon brief runs at 5:00 PM.</p>
        </div>
        {error && <p className="text-xs text-rose-300/80">{error}</p>}
        <button
          type="button"
          onClick={() => void runNow()}
          disabled={busy}
          className="mt-1 rounded-full bg-white px-4 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? 'Running…' : 'Run review now'}
        </button>
      </div>
    )
  }

  const isPending = review.status === 'pending'
  const isDismissed = review.status === 'dismissed'
  const draftCount = review.emails.filter((email) => email.draft_id !== null).length

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col gap-4"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">
            Today&apos;s Review — {formatDate(review.review_date)}
          </h3>
          <p className="mt-0.5 text-xs text-white/40">
            {groups.actionRequired.length} need attention · {draftCount} drafts ready ·{' '}
            {groups.archivedCount} archived · {groups.trashed.length} trashed
          </p>
        </div>
        {isPending && (
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void approveAll()}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg bg-green-500/20 px-3 py-1.5 text-xs text-green-300 transition-colors hover:bg-green-500/30 disabled:opacity-40"
            >
              <FiCheck size={14} /> Approve all
            </button>
            <button
              type="button"
              onClick={() => void dismiss()}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-white/50 transition-colors hover:bg-white/10 hover:text-white/80 disabled:opacity-40"
            >
              <FiX size={14} /> Dismiss
            </button>
          </div>
        )}
      </div>

      {error && <p className="text-xs text-rose-300/80">{error}</p>}

      {/* Status banner for approved / dismissed */}
      {review.status === 'approved' && (
        <p className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/50">
          Approved — triage applied and summaries saved.
        </p>
      )}

      {isDismissed && (
        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2">
          <p className="text-xs text-white/50">Dismissed — no action taken.</p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void runNow()}
              disabled={busy}
              className="text-xs text-white/40 hover:text-white disabled:opacity-40"
            >
              {busy ? 'Running…' : 'Run again'}
            </button>
            <button
              type="button"
              onClick={() => void reopen()}
              disabled={busy}
              className="rounded-lg bg-white/10 px-2.5 py-1 text-xs text-white/70 transition-colors hover:bg-white/20 hover:text-white disabled:opacity-40"
            >
              Reopen
            </button>
          </div>
        </div>
      )}

      {/* Action Required section */}
      {groups.actionRequired.length > 0 && (
        <Section title="Action Required">
          {groups.actionRequired.map((email) => (
            <ReviewCard
              key={email.email_id}
              email={email}
              isExpanded={expandedId === email.email_id}
              onToggle={() => toggleCard(email.email_id)}
            >
              {/* Action buttons only shown when review is pending */}
              {isPending && (
                <>
                  {email.draft_id !== null && (
                    <button
                      type="button"
                      onClick={() => setActivePanel('drafts')}
                      className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white/80 transition-colors hover:bg-white/15"
                    >
                      View draft reply
                    </button>
                  )}
                  {email.calendar_suggestion?.detected && (
                    <button
                      type="button"
                      onClick={() => addToCalendar(email)}
                      className="flex items-center gap-1.5 rounded-lg bg-sky-500/20 px-3 py-1.5 text-xs text-sky-200 transition-colors hover:bg-sky-500/30"
                    >
                      <FiCalendar size={13} /> Add to calendar
                    </button>
                  )}
                </>
              )}
            </ReviewCard>
          ))}
        </Section>
      )}

      {/* FYI section */}
      {groups.fyi.length > 0 && (
        <Section title="FYI">
          {groups.fyi.map((email) => (
            <ReviewCard
              key={email.email_id}
              email={email}
              isExpanded={expandedId === email.email_id}
              onToggle={() => toggleCard(email.email_id)}
            >
              {isPending && (
                <span className="text-xs text-white/30">Archived automatically.</span>
              )}
            </ReviewCard>
          ))}
        </Section>
      )}

      {/* Cleaned Up section */}
      {(groups.trashed.length > 0 || groups.archivedCount > 0) && (
        <Section title="Cleaned Up">
          <p className="px-1 text-xs text-white/40">
            {groups.trashed.length} email{groups.trashed.length === 1 ? '' : 's'} trashed ·{' '}
            {groups.archivedCount} archived
          </p>
        </Section>
      )}

      {review.emails.length === 0 && (
        <p className="py-6 text-center text-sm text-white/40">
          No new emails were reviewed today.
        </p>
      )}
    </motion.div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h4 className="sticky top-0 z-10 bg-[#0d0d0f]/95 py-1 text-xs font-semibold uppercase tracking-wide text-white/40 backdrop-blur">
        {title}
      </h4>
      {children}
    </div>
  )
}

function ReviewCard({
  email,
  isExpanded,
  onToggle,
  children,
}: {
  email: ReviewEmail
  isExpanded: boolean
  onToggle: () => void
  children?: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/5">
      {/* Collapsed header — always visible, click to expand */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-2 px-4 py-3 text-left"
      >
        <FiMail size={14} className="mt-0.5 shrink-0 text-white/40" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-white">
            {email.subject || '(no subject)'}
          </p>
          <p className="truncate text-xs text-white/40">{email.from || 'Unknown sender'}</p>
          {!isExpanded && email.summary && (
            <p className="mt-1 line-clamp-2 text-xs text-white/60">{email.summary}</p>
          )}
        </div>
        <FiChevronDown
          size={14}
          className={`mt-0.5 shrink-0 text-white/30 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            key="detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-2 border-t border-white/[0.06] px-4 pb-3 pt-2">
              <div className="flex flex-col gap-0.5 text-xs text-white/40">
                {email.from && (
                  <p>
                    <span className="text-white/30">From </span>
                    {email.from}
                  </p>
                )}
                {email.received_at && (
                  <p>
                    <span className="text-white/30">Received </span>
                    {formatReceived(email.received_at)}
                  </p>
                )}
              </div>
              {email.summary && (
                <p className="text-xs leading-relaxed text-white/60">{email.summary}</p>
              )}
              <p className="text-xs text-white/40">
                Suggested action:{' '}
                <span className="text-white/60">{suggestedAction(email)}</span>
              </p>
              {children && (
                <div className="mt-1 flex flex-wrap items-center gap-2">{children}</div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default DailyReviewPanel
