import { useEffect, useMemo, useState } from 'react'
import { FiCheck, FiChevronDown, FiChevronRight, FiLoader } from 'react-icons/fi'
import { HiOutlineInbox } from 'react-icons/hi2'

import { api, type DailyReview, type ReviewEmail, type TriageStatus } from '../../api/client'

const CATEGORIES: { status: TriageStatus; title: string; note: string }[] = [
  { status: 'trash', title: 'Trash', note: 'Trashed in Gmail, deleted locally' },
  { status: 'archive', title: 'Archive', note: 'Removed from inbox, kept in memory' },
  { status: 'keep', title: 'Keep', note: 'No action — stays in inbox' },
]

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

/**
 * Daily Review panel — mirrors the TriageReview layout used after email sweep.
 *
 * Emails are grouped into three collapsible sections (Trash / Archive / Keep).
 * The user can reclassify individual emails via the dropdown on each row; those
 * changes are applied locally and sent as overrides when the review is approved.
 * Nothing reaches Gmail until the user clicks "Apply & approve".
 */
export function DailyReviewPanel() {
  const [review, setReview] = useState<DailyReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Local classification choices, keyed by email_id.
  const [decisions, setDecisions] = useState<Record<number, TriageStatus>>({})
  const [expanded, setExpanded] = useState<TriageStatus | null>('trash')
  // Set after a successful approval to show the success state.
  const [applied, setApplied] = useState<{ trashed: number; archived: number } | null>(null)

  const seedDecisions = (emails: ReviewEmail[]) => {
    const d: Record<number, TriageStatus> = {}
    for (const e of emails) {
      d[e.email_id] = e.classification as TriageStatus
    }
    setDecisions(d)
  }

  const load = async () => {
    try {
      const { review: result } = await api.getReview()
      setReview(result)
      if (result) seedDecisions(result.emails)
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
    try {
      const { review: result } = await api.triggerReview()
      setReview(result)
      if (result) {
        seedDecisions(result.emails)
        // Default-expand the first non-empty category.
        const first = CATEGORIES.find(
          ({ status }) => result.emails.some((e) => e.classification === status),
        )
        if (first) setExpanded(first.status)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not run review')
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    setBusy(true)
    setError(null)
    try {
      // Send the full decisions map as overrides so the backend uses the
      // user's final classifications, not just the auto-triage result.
      const overrides: Record<string, string> = {}
      for (const [id, status] of Object.entries(decisions)) {
        overrides[id] = status
      }
      const result = await api.approveReview(overrides)
      setReview(result.review)
      setApplied(result.applied)
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

  // Group emails by their current (possibly user-changed) classification.
  const groups = useMemo(() => {
    const result: Record<TriageStatus, ReviewEmail[]> = { trash: [], archive: [], keep: [] }
    for (const email of review?.emails ?? []) {
      const decision = decisions[email.email_id] ?? (email.classification as TriageStatus)
      result[decision].push(email)
    }
    return result
  }, [review, decisions])

  const counts = useMemo(
    () => ({
      trash: groups.trash.length,
      archive: groups.archive.length,
      keep: groups.keep.length,
    }),
    [groups],
  )

  const total = counts.trash + counts.archive + counts.keep

  // --- Loading state ---
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-white/40">
        <FiLoader className="animate-spin" size={16} />
        <span className="text-sm">Loading review…</span>
      </div>
    )
  }

  // --- Post-approval success state ---
  if (applied) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 text-center">
        <FiCheck size={32} className="text-green-400" />
        <div>
          <p className="text-sm font-medium text-white">Review complete</p>
          <p className="mt-1 text-xs text-white/50">
            {applied.trashed} trashed · {applied.archived} archived in Gmail
          </p>
        </div>
        <button
          type="button"
          onClick={() => setApplied(null)}
          className="rounded-full bg-white px-4 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90"
        >
          Done
        </button>
      </div>
    )
  }

  // --- Empty state: no review today ---
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

  return (
    <div className="flex flex-col gap-4">
      {/* Sticky metadata header */}
      <div className="sticky top-0 z-20 bg-[#0d0d0f]/95 pb-3 backdrop-blur">
        <div className="text-sm font-semibold text-white">
          Today&apos;s Review — {formatDate(review.review_date)}
        </div>
        <div className="mt-0.5 text-xs text-white/50">
          {total.toLocaleString()} emails analyzed · {counts.trash.toLocaleString()} trash ·{' '}
          {counts.archive.toLocaleString()} archive · {counts.keep.toLocaleString()} keep
        </div>

        {error && <p className="mt-2 text-xs text-rose-300/80">{error}</p>}

        {review.status === 'approved' && (
          <div className="mt-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/50">
            Approved — triage applied and summaries saved.
          </div>
        )}
        {review.status === 'dismissed' && (
          <div className="mt-2 flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2">
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
      </div>

      {/* Category sections */}
      <div className="flex flex-col gap-2">
        {CATEGORIES.map(({ status, title, note }) => {
          const isOpen = expanded === status
          const rows = groups[status]

          return (
            <div key={status} className="rounded-xl border border-white/10 bg-white/[0.03]">
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : status)}
                className="flex w-full items-center justify-between rounded-xl bg-[#0f1117]/95 px-4 py-3 text-left transition-colors hover:bg-white/[0.06]"
              >
                <div className="flex items-center gap-2">
                  {isOpen ? <FiChevronDown size={16} /> : <FiChevronRight size={16} />}
                  <span className="font-medium capitalize">{title}</span>
                  <span className="text-sm text-white/40">{counts[status].toLocaleString()}</span>
                </div>
                <span className="text-xs text-white/40">{note}</span>
              </button>

              {isOpen && rows.length === 0 && (
                <div className="border-t border-white/[0.06] px-4 py-4 text-sm text-white/40">
                  Nothing here.
                </div>
              )}

              {isOpen && rows.length > 0 && (
                <ul className="divide-y divide-white/[0.04] border-t border-white/[0.06]">
                  {rows.map((email) => (
                    <ReviewRow
                      key={email.email_id}
                      email={email}
                      category={status}
                      decision={decisions[email.email_id] ?? (email.classification as TriageStatus)}
                      isPending={isPending}
                      onDecision={(next) =>
                        setDecisions((prev) => ({ ...prev, [email.email_id]: next }))
                      }
                    />
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>

      {review.emails.length === 0 && (
        <p className="py-4 text-center text-sm text-white/40">
          No emails were reviewed today.
        </p>
      )}

      {/* Sticky approve/discard footer — only when the review is still pending */}
      {isPending && (
        <div className="sticky bottom-0 -mx-6 border-t border-white/10 bg-[#0d0d0f]/95 px-6 py-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void approve()}
              disabled={busy}
              className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy ? 'Applying…' : 'Apply & approve'}
            </button>
            <button
              type="button"
              onClick={() => void dismiss()}
              disabled={busy}
              className="text-sm text-white/40 transition-colors hover:text-white/70 disabled:opacity-40"
            >
              Discard
            </button>
            <span className="ml-auto text-xs text-white/40">
              Trashes {counts.trash.toLocaleString()}, archives{' '}
              {counts.archive.toLocaleString()} in Gmail.
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

interface ReviewRowProps {
  email: ReviewEmail
  category: TriageStatus
  decision: TriageStatus
  isPending: boolean
  onDecision: (status: TriageStatus) => void
}

/** One reviewable email: checkbox (for trash/archive), summary, sender · date, dropdown. */
function ReviewRow({ email, category, decision, isPending, onDecision }: ReviewRowProps) {
  const when = email.received_at ? new Date(email.received_at).toLocaleDateString() : ''
  const sender = email.from || 'Unknown sender'
  const summary = email.summary || email.subject || '(no summary)'

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-start gap-3">
        {/* Checkbox only shown for trash/archive; toggling moves the email to Keep */}
        {category !== 'keep' && (
          <input
            type="checkbox"
            checked={decision !== 'keep'}
            onChange={(event) => onDecision(event.target.checked ? category : 'keep')}
            disabled={!isPending}
            aria-label="Include in this action"
            className="mt-1 h-4 w-4 shrink-0 accent-white disabled:opacity-40"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-white">{summary}</div>
          <div className="mt-0.5 truncate text-xs text-white/40">
            {sender}
            {when && ` · ${when}`}
          </div>
        </div>
        {/* Dropdown when pending; read-only badge when approved/dismissed */}
        {isPending ? (
          <select
            value={decision}
            onChange={(event) => onDecision(event.target.value as TriageStatus)}
            aria-label="Move to category"
            className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/80 focus:border-white/30 focus:outline-none"
          >
            <option value="keep">Keep</option>
            <option value="archive">Archive</option>
            <option value="trash">Trash</option>
          </select>
        ) : (
          <span className="shrink-0 rounded-lg border border-white/10 px-2 py-1 text-xs capitalize text-white/40">
            {decision}
          </span>
        )}
      </div>
    </li>
  )
}

export default DailyReviewPanel
