import { useEffect, useRef, useState } from 'react'
import { FiCheck, FiChevronDown, FiChevronRight, FiDownload, FiLoader, FiTrash2 } from 'react-icons/fi'

import { api } from '../../api/client'
import type { TriageCounts, TriageEmail, TriageOverride, TriageStatus } from '../../api/client'

const CATEGORIES: { status: TriageStatus; title: string; note: string }[] = [
  { status: 'trash', title: 'Trash', note: 'Trashed in Gmail, deleted locally' },
  { status: 'archive', title: 'Archive', note: 'Removed from inbox, kept in memory' },
  { status: 'keep', title: 'Keep', note: 'No action — stays in inbox' },
]

type CategoryMap<T> = Record<TriageStatus, T>

interface TriageReviewProps {
  accountId: number
  email: string
  counts: TriageCounts
  applying: boolean
  onApply: (overrides: TriageOverride[]) => void
  onDiscard: () => void
}

/**
 * Full-screen triage review: shows sweep classification results before
 * anything is applied to Gmail. Categories are expandable with independent
 * scroll; emails can be individually re-categorized. Only changed decisions
 * are sent as overrides on approval — the rest apply as classified.
 */
export function TriageReview({
  accountId,
  email,
  counts,
  applying,
  onApply,
  onDiscard,
}: TriageReviewProps) {
  const [expanded, setExpanded] = useState<TriageStatus | null>('trash')
  const [emails, setEmails] = useState<CategoryMap<TriageEmail[]>>({ trash: [], archive: [], keep: [] })
  const [loaded, setLoaded] = useState<CategoryMap<boolean>>({ trash: false, archive: false, keep: false })
  const [fetching, setFetching] = useState<CategoryMap<boolean>>({ trash: false, archive: false, keep: false })
  const [openEmailId, setOpenEmailId] = useState<number | null>(null)
  // decisions: current UI state. savedDecisions: last persisted state. originals: what Claude assigned.
  const [decisions, setDecisions] = useState<Record<number, TriageStatus>>({})
  const [savedDecisions, setSavedDecisions] = useState<Record<number, TriageStatus>>({})
  const [originals, setOriginals] = useState<Record<number, TriageStatus>>({})
  // Live counts that update after each save (prop counts are read-only).
  const [liveCounts, setLiveCounts] = useState<TriageCounts>(counts)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadCategory = async (status: TriageStatus) => {
    setFetching((prev) => ({ ...prev, [status]: true }))
    try {
      // Fetch every email in one request; backend limit raised to 10000.
      const total = Math.max(liveCounts[status], 1)
      const result = await api.getTriageEmails(accountId, status, total, 0)
      setEmails((prev) => ({ ...prev, [status]: result.emails }))
      setLoaded((prev) => ({ ...prev, [status]: true }))
      setOriginals((prev) => {
        const next = { ...prev }
        result.emails.forEach((item) => { next[item.id] = status })
        return next
      })
      const seed = (prev: Record<number, TriageStatus>) => {
        const next = { ...prev }
        result.emails.forEach((item) => {
          if (!(item.id in next)) next[item.id] = status
        })
        return next
      }
      setDecisions(seed)
      setSavedDecisions(seed)
    } finally {
      setFetching((prev) => ({ ...prev, [status]: false }))
    }
  }

  useEffect(() => {
    if (expanded && !loaded[expanded]) void loadCategory(expanded)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded])

  const setDecision = (id: number, status: TriageStatus) =>
    setDecisions((prev) => ({ ...prev, [id]: status }))

  // Emails whose current decision differs from what's saved in the database.
  const unsavedChanges = Object.entries(decisions).filter(
    ([id, status]) => savedDecisions[Number(id)] !== undefined && savedDecisions[Number(id)] !== status,
  )

  const saveChanges = async () => {
    if (unsavedChanges.length === 0) return
    setSaving(true)
    setSaveError(null)
    try {
      await api.bulkUpdateTriage(
        unsavedChanges.map(([id, status]) => ({
          email_id: Number(id),
          triage_status: status as TriageStatus,
        })),
      )

      // Move each email to its new category in the local UI state.
      setEmails((prev) => {
        const next: CategoryMap<TriageEmail[]> = { trash: [...prev.trash], archive: [...prev.archive], keep: [...prev.keep] }
        for (const [rawId, newStatus] of unsavedChanges) {
          const id = Number(rawId)
          const oldStatus = savedDecisions[id]
          if (!oldStatus || oldStatus === newStatus) continue
          const emailObj = next[oldStatus].find((e) => e.id === id)
          if (!emailObj) continue
          next[oldStatus] = next[oldStatus].filter((e) => e.id !== id)
          next[newStatus] = [emailObj, ...next[newStatus]]
        }
        return next
      })

      // Recompute live counts from the moves.
      setLiveCounts((prev) => {
        const delta: Record<TriageStatus, number> = { trash: 0, archive: 0, keep: 0 }
        for (const [rawId, newStatus] of unsavedChanges) {
          const oldStatus = savedDecisions[Number(rawId)]
          if (!oldStatus || oldStatus === newStatus) continue
          delta[oldStatus] -= 1
          delta[newStatus as TriageStatus] += 1
        }
        return {
          ...prev,
          trash: prev.trash + delta.trash,
          archive: prev.archive + delta.archive,
          keep: prev.keep + delta.keep,
        }
      })

      // Advance saved state to match decisions.
      setSavedDecisions((prev) => {
        const next = { ...prev }
        for (const [id, status] of unsavedChanges) next[Number(id)] = status as TriageStatus
        return next
      })

      // Brief success flash.
      setSavedFlash(true)
      if (flashTimer.current) clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setSavedFlash(false), 2500)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Could not save changes.')
    } finally {
      setSaving(false)
    }
  }

  const undoAll = () => {
    setDecisions((prev) => ({ ...prev, ...savedDecisions }))
    setSaveError(null)
  }

  const overrides = (): TriageOverride[] =>
    Object.entries(decisions)
      .filter(([id, status]) => originals[Number(id)] !== status)
      .map(([id, status]) => ({ id: Number(id), status }))

  const downloadReport = async () => {
    try {
      const text = await api.getTriageReport(accountId)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `meridian-triage-${accountId}.txt`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      // Report is best-effort.
    }
  }

  const analyzed = liveCounts.trash + liveCounts.archive + liveCounts.keep

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Fixed header: account info + action buttons */}
      <div className="shrink-0 border-b border-white/10 px-6 py-5">
        <div className="text-xl font-semibold">Inbox sweep — {email}</div>
        <div className="mt-1 text-sm text-white/50">
          {analyzed.toLocaleString()} emails analyzed · {liveCounts.trash.toLocaleString()} trash ·{' '}
          {liveCounts.archive.toLocaleString()} archive · {liveCounts.keep.toLocaleString()} keep
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => void downloadReport()}
            className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-xs text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            <FiDownload size={14} /> Download Report
          </button>
          <button
            type="button"
            onClick={onDiscard}
            className="flex items-center gap-2 rounded-full border border-rose-400/20 px-3 py-1.5 text-xs text-rose-300/80 transition-colors hover:bg-rose-400/10"
          >
            <FiTrash2 size={14} /> Discard Sweep
          </button>
        </div>
      </div>

      {/* Scrollable category list */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="flex flex-col gap-2">
          {CATEGORIES.map(({ status, title, note }) => {
            const isOpen = expanded === status
            const rows = emails[status]
            return (
              <div
                key={status}
                className="rounded-xl border border-white/10 bg-white/[0.03]"
              >
                {/* Sticky category header — stays at top of the scroll area */}
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : status)}
                  className="sticky top-0 z-10 flex w-full items-center justify-between rounded-xl bg-[#0f1117]/95 px-4 py-3 text-left backdrop-blur-sm transition-colors hover:bg-white/[0.06]"
                >
                  <div className="flex items-center gap-2">
                    {isOpen ? <FiChevronDown size={16} /> : <FiChevronRight size={16} />}
                    <span className="font-medium capitalize">{title}</span>
                    <span className="text-sm text-white/40">{liveCounts[status].toLocaleString()}</span>
                  </div>
                  <span className="text-xs text-white/40">{note}</span>
                </button>

                {isOpen && (
                  <div className="border-t border-white/[0.06]">
                    {fetching[status] && (
                      <div className="flex items-center gap-2 px-4 py-4 text-sm text-white/40">
                        <FiLoader className="animate-spin" size={14} />
                        Loading {counts[status].toLocaleString()} emails…
                      </div>
                    )}
                    {loaded[status] && rows.length === 0 && (
                      <div className="px-4 py-4 text-sm text-white/40">Nothing here.</div>
                    )}
                    {rows.length > 0 && (
                      <ul className="divide-y divide-white/[0.04]">
                        {rows.map((item) => (
                          <TriageRow
                            key={item.id}
                            item={item}
                            category={status}
                            decision={decisions[item.id] ?? status}
                            hasUnsavedChange={
                              savedDecisions[item.id] !== undefined &&
                              savedDecisions[item.id] !== (decisions[item.id] ?? status)
                            }
                            open={openEmailId === item.id}
                            onToggleOpen={() =>
                              setOpenEmailId(openEmailId === item.id ? null : item.id)
                            }
                            onDecision={(next) => setDecision(item.id, next)}
                          />
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Sticky save bar — appears when there are unsaved dropdown changes */}
      {(unsavedChanges.length > 0 || savedFlash || saveError) && (
        <div className="shrink-0 border-t border-amber-400/20 bg-amber-400/5 px-6 py-3">
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-amber-300/80">
              {savedFlash ? (
                <span className="flex items-center gap-1.5 text-emerald-300/80">
                  <FiCheck size={14} /> Changes saved
                </span>
              ) : saveError ? (
                <span className="text-rose-300/80">{saveError}</span>
              ) : (
                <>
                  {unsavedChanges.length} email{unsavedChanges.length !== 1 ? 's' : ''} reclassified
                </>
              )}
            </span>
            {!savedFlash && (
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={undoAll}
                  disabled={saving}
                  className="text-sm text-white/40 transition-colors hover:text-white/70 disabled:opacity-40"
                >
                  Undo all
                </button>
                <button
                  type="button"
                  onClick={() => void saveChanges()}
                  disabled={saving || unsavedChanges.length === 0}
                  className="flex items-center gap-1.5 rounded-full bg-amber-400/90 px-4 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {saving ? <FiLoader className="animate-spin" size={12} /> : null}
                  Save changes
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Fixed footer: apply button */}
      <div className="shrink-0 border-t border-white/10 px-6 py-5">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onApply(overrides())}
            disabled={applying}
            className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {applying ? 'Applying…' : 'Apply & build memory'}
          </button>
          <span className="text-xs text-white/40">
            Trashes {counts.trash.toLocaleString()}, archives {counts.archive.toLocaleString()} in
            Gmail.
          </span>
        </div>
      </div>
    </div>
  )
}

interface TriageRowProps {
  item: TriageEmail
  category: TriageStatus
  decision: TriageStatus
  hasUnsavedChange: boolean
  open: boolean
  onToggleOpen: () => void
  onDecision: (status: TriageStatus) => void
}

/** One reviewable email: checkbox (trash/archive), summary, sender/date, move dropdown. */
function TriageRow({ item, category, decision, hasUnsavedChange, open, onToggleOpen, onDecision }: TriageRowProps) {
  const when = item.received_at ? new Date(item.received_at).toLocaleDateString() : ''
  const sender = item.from_address || 'Unknown sender'
  const summary = item.summary || item.subject || '(no summary)'

  return (
    <li className={`px-4 py-2.5 ${hasUnsavedChange ? 'border-l-2 border-amber-400/50 pl-3.5' : ''}`}>
      <div className="flex items-start gap-3">
        {hasUnsavedChange && (
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" aria-hidden />
        )}
        {category !== 'keep' && (
          <input
            type="checkbox"
            checked={decision !== 'keep'}
            onChange={(event) => onDecision(event.target.checked ? category : 'keep')}
            aria-label="Include in this action"
            className="mt-1 h-4 w-4 shrink-0 accent-white"
          />
        )}
        <button type="button" onClick={onToggleOpen} className="min-w-0 flex-1 text-left">
          <div className={open ? 'text-sm text-white' : 'truncate text-sm text-white'}>
            {summary}
          </div>
          <div className="mt-0.5 truncate text-xs text-white/40">
            {sender}
            {when && ` · ${when}`}
          </div>
          {open && item.subject && (
            <div className="mt-1 text-xs text-white/50">Subject: {item.subject}</div>
          )}
        </button>
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
      </div>
    </li>
  )
}

export default TriageReview
