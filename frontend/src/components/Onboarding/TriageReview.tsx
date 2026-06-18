import { useEffect, useState } from 'react'
import { FiChevronDown, FiChevronRight, FiDownload, FiTrash2 } from 'react-icons/fi'

import { api } from '../../api/client'
import type { TriageCounts, TriageEmail, TriageOverride, TriageStatus } from '../../api/client'

const CATEGORIES: { status: TriageStatus; title: string; note: string }[] = [
  { status: 'trash', title: 'Trash', note: 'Trashed in Gmail, deleted locally' },
  { status: 'archive', title: 'Archive', note: 'Removed from inbox, kept in memory' },
  { status: 'keep', title: 'Keep', note: 'No action — stays in inbox' },
]
const PAGE_SIZE = 50

type EmailsByCategory = Record<TriageStatus, TriageEmail[]>
type LoadedByCategory = Record<TriageStatus, boolean>

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
  const [emails, setEmails] = useState<EmailsByCategory>({ trash: [], archive: [], keep: [] })
  const [loaded, setLoaded] = useState<LoadedByCategory>({
    trash: false,
    archive: false,
    keep: false,
  })
  const [openEmailId, setOpenEmailId] = useState<number | null>(null)
  // Final category per email the user touched, and the category it started in.
  const [decisions, setDecisions] = useState<Record<number, TriageStatus>>({})
  const [originals, setOriginals] = useState<Record<number, TriageStatus>>({})

  const loadCategory = async (status: TriageStatus, offset = 0) => {
    const result = await api.getTriageEmails(accountId, status, PAGE_SIZE, offset)
    setEmails((prev) => ({
      ...prev,
      [status]: offset === 0 ? result.emails : [...prev[status], ...result.emails],
    }))
    setLoaded((prev) => ({ ...prev, [status]: true }))
    setOriginals((prev) => {
      const next = { ...prev }
      result.emails.forEach((item) => {
        next[item.id] = status
      })
      return next
    })
    setDecisions((prev) => {
      const next = { ...prev }
      result.emails.forEach((item) => {
        if (!(item.id in next)) next[item.id] = status
      })
      return next
    })
  }

  useEffect(() => {
    if (expanded && !loaded[expanded]) void loadCategory(expanded)
    // loadCategory is stable enough for this lazy-load on expand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded])

  const setDecision = (id: number, status: TriageStatus) =>
    setDecisions((prev) => ({ ...prev, [id]: status }))

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

  const analyzed = counts.trash + counts.archive + counts.keep

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Fixed header: account info + action buttons */}
      <div className="shrink-0 border-b border-white/10 px-6 py-5">
        <div className="text-xl font-semibold">Inbox sweep — {email}</div>
        <div className="mt-1 text-sm text-white/50">
          {analyzed.toLocaleString()} emails analyzed · {counts.trash.toLocaleString()} trash ·{' '}
          {counts.archive.toLocaleString()} archive · {counts.keep.toLocaleString()} keep
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
                    <span className="text-sm text-white/40">{counts[status].toLocaleString()}</span>
                  </div>
                  <span className="text-xs text-white/40">{note}</span>
                </button>

                {isOpen && (
                  <div className="max-h-[60vh] overflow-y-auto border-t border-white/[0.06]">
                    {!loaded[status] && (
                      <div className="px-4 py-4 text-sm text-white/40">Loading…</div>
                    )}
                    {loaded[status] && rows.length === 0 && (
                      <div className="px-4 py-4 text-sm text-white/40">Nothing here.</div>
                    )}
                    <ul className="divide-y divide-white/[0.04]">
                      {rows.map((item) => (
                        <TriageRow
                          key={item.id}
                          item={item}
                          category={status}
                          decision={decisions[item.id] ?? status}
                          open={openEmailId === item.id}
                          onToggleOpen={() =>
                            setOpenEmailId(openEmailId === item.id ? null : item.id)
                          }
                          onDecision={(next) => setDecision(item.id, next)}
                        />
                      ))}
                    </ul>
                    {rows.length < counts[status] && (
                      <button
                        type="button"
                        onClick={() => void loadCategory(status, rows.length)}
                        className="w-full px-4 py-3 text-sm text-white/50 transition-colors hover:bg-white/[0.04] hover:text-white/80"
                      >
                        Load more ({(counts[status] - rows.length).toLocaleString()} remaining)
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

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
  open: boolean
  onToggleOpen: () => void
  onDecision: (status: TriageStatus) => void
}

/** One reviewable email: checkbox (trash/archive), summary, sender/date, move dropdown. */
function TriageRow({ item, category, decision, open, onToggleOpen, onDecision }: TriageRowProps) {
  const when = item.received_at ? new Date(item.received_at).toLocaleDateString() : ''
  const sender = item.from_address || 'Unknown sender'
  const summary = item.summary || item.subject || '(no summary)'

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-start gap-3">
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
