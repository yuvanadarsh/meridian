import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  HiOutlineArrowPath,
  HiOutlineChevronDown,
} from 'react-icons/hi2'

import { api } from '../api/client'
import type { QueueClassification, QueueItem } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'

// Display order and metadata for the four classification sections.
const SECTIONS: { key: QueueClassification; label: string; hint: string }[] = [
  { key: 'draft', label: 'Draft Needed', hint: 'Reply required' },
  { key: 'keep', label: 'Keep', hint: 'Needs your attention' },
  { key: 'archive', label: 'Archive', hint: 'Removing from inbox' },
  { key: 'trash', label: 'Trash', hint: 'Will be deleted' },
]

const CLASSIFICATIONS: QueueClassification[] = ['trash', 'archive', 'keep', 'draft']

const CLASSIFICATION_COLORS: Record<QueueClassification, string> = {
  trash: 'text-red-400 bg-red-400/10',
  archive: 'text-yellow-400 bg-yellow-400/10',
  keep: 'text-blue-400 bg-blue-400/10',
  draft: 'text-green-400 bg-green-400/10',
}

const POLL_INTERVAL_MS = 60_000

/** Short relative time like "5 min ago" / "2 hr ago". */
function formatRelative(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

/** Inline spinner matching the rest of the app. */
function Spinner() {
  return (
    <span className="h-3 w-3 animate-spin rounded-full border border-white/40 border-t-white/80" />
  )
}

/**
 * Inbox: the live email queue. The poll classifies new mail on arrival into
 * trash/archive/keep/draft; this page lets the user reclassify, generate a reply
 * draft, dismiss, and approve — the single point where Gmail is mutated.
 */
export function InboxPage() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [applying, setApplying] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const queue = await api.getInboxQueue()
      setItems(queue)
      setLastUpdated(new Date().toISOString())
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [refresh])

  const setItem = (id: number, patch: Partial<QueueItem>) =>
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)))

  const handleReclassify = (id: number, classification: QueueClassification) =>
    setItem(id, { classification })

  const handleDismiss = async (id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id))
    try {
      await api.dismissQueueItem(id)
    } catch {
      void refresh()
    }
  }

  const handleGenerateDraft = async (id: number) => {
    setItem(id, { draft_status: 'generating' })
    try {
      const result = await api.generateDraftFromQueue(id)
      setItem(id, { draft_status: 'ready', draft_id: result.draft_id })
    } catch (err) {
      setItem(id, { draft_status: null })
      setError((err as Error).message)
    }
  }

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      const { queue } = await api.triggerInbox()
      setItems(queue)
      setLastUpdated(new Date().toISOString())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setTriggering(false)
    }
  }

  const handleApproveAll = async () => {
    if (items.length === 0) return
    setApplying(true)
    const ids = items.map((item) => item.id)
    const overrides: Record<string, string> = {}
    for (const item of items) overrides[String(item.id)] = item.classification
    try {
      await api.approveInbox(ids, overrides)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setApplying(false)
    }
  }

  const counts = CLASSIFICATIONS.reduce<Record<QueueClassification, number>>(
    (acc, key) => {
      acc[key] = items.filter((item) => item.classification === key).length
      return acc
    },
    { trash: 0, archive: 0, keep: 0, draft: 0 },
  )

  const triggerButton = (
    <button
      type="button"
      onClick={handleTrigger}
      disabled={triggering}
      className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 transition-colors hover:bg-white/10 disabled:opacity-50"
    >
      <HiOutlineArrowPath className={triggering ? 'animate-spin' : ''} size={14} />
      {triggering ? 'Running…' : 'Run triage now'}
    </button>
  )

  return (
    <PageLayout
      title="Inbox"
      subtitle="Your email queue — updated every 15 minutes."
      actions={triggerButton}
    >
      {loading ? (
        <p className="py-10 text-center text-sm text-white/40">Loading queue…</p>
      ) : error ? (
        <p className="py-10 text-center text-sm text-red-400/80">{error}</p>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-16 text-center">
          <p className="text-sm text-white/60">Inbox queue is empty</p>
          <p className="text-xs text-white/30">New mail is triaged here every 15 minutes.</p>
        </div>
      ) : (
        <div className="mx-auto max-w-3xl">
          {/* Summary line */}
          <div className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-white/50">
            {lastUpdated && (
              <span className="text-white/40">Last updated {formatRelative(lastUpdated)}</span>
            )}
            <span className="text-white/20">·</span>
            <span className="text-white/70">{items.length} pending</span>
            <span className="text-white/20">·</span>
            <span>{counts.trash} trash</span>
            <span className="text-white/20">·</span>
            <span>{counts.archive} archive</span>
            <span className="text-white/20">·</span>
            <span>{counts.keep} keep</span>
            <span className="text-white/20">·</span>
            <span>{counts.draft} draft needed</span>
          </div>

          {/* Grouped sections */}
          {SECTIONS.map((section) => {
            const sectionItems = items.filter((item) => item.classification === section.key)
            if (sectionItems.length === 0) return null
            return (
              <div key={section.key} className="mb-6">
                <div className="mb-2 flex items-baseline gap-3">
                  <h2 className="text-sm font-medium text-white">
                    {section.label}{' '}
                    <span className="text-white/40">{sectionItems.length}</span>
                  </h2>
                  <span className="text-xs text-white/30">{section.hint}</span>
                </div>
                {sectionItems.map((item) => (
                  <QueueEmailCard
                    key={item.id}
                    item={item}
                    onReclassify={handleReclassify}
                    onGenerateDraft={handleGenerateDraft}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            )
          })}

          {/* Approve all */}
          <div className="sticky bottom-0 mt-8 flex items-center justify-between gap-4 border-t border-white/5 bg-[#080808]/90 py-4 backdrop-blur">
            <span className="text-xs text-white/40">
              Trashes {counts.trash}, archives {counts.archive} in Gmail.
            </span>
            <button
              type="button"
              onClick={handleApproveAll}
              disabled={applying}
              className="flex items-center gap-2 rounded-xl bg-white px-5 py-2 text-sm font-medium text-black transition-colors hover:bg-white/90 disabled:opacity-50"
            >
              {applying && <Spinner />}
              {applying ? 'Applying…' : 'Apply & approve all'}
            </button>
          </div>
        </div>
      )}
    </PageLayout>
  )
}

interface CardProps {
  item: QueueItem
  onReclassify: (id: number, classification: QueueClassification) => void
  onGenerateDraft: (id: number) => void
  onDismiss: (id: number) => void
}

function QueueEmailCard({ item, onReclassify, onGenerateDraft, onDismiss }: CardProps) {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()

  return (
    <div className="mb-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
      <div
        className="flex cursor-pointer items-start justify-between gap-4"
        onClick={() => setExpanded((prev) => !prev)}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-white">
            {item.subject || '(no subject)'}
          </div>
          <div className="mt-0.5 truncate text-xs text-white/40">
            {item.from_address || 'unknown sender'} · {formatRelative(item.received_at)}
          </div>
          {item.ai_summary && (
            <div className="mt-1 text-xs text-white/60">{item.ai_summary}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ClassificationBadge
            value={item.classification}
            onChange={(value) => onReclassify(item.id, value)}
          />
          <HiOutlineChevronDown
            size={16}
            className={`text-white/40 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </div>

      {expanded && (
        <div className="mt-3 border-t border-white/5 pt-3">
          {item.snippet && <p className="text-xs text-white/50">{item.snippet}</p>}

          {item.classification === 'draft' && (
            <div className="mt-3">
              {(item.draft_status === null || item.draft_status === undefined) && (
                <button
                  type="button"
                  onClick={() => onGenerateDraft(item.id)}
                  className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/15"
                >
                  Approve &amp; Generate Draft
                </button>
              )}
              {item.draft_status === 'generating' && (
                <div className="flex items-center gap-2 text-xs text-white/40">
                  <Spinner /> Generating draft…
                </div>
              )}
              {item.draft_status === 'ready' && item.draft_id !== null && (
                <button
                  type="button"
                  onClick={() => navigate(`/drafts/${item.draft_id}`)}
                  className="text-xs text-blue-400 transition-colors hover:text-blue-300"
                >
                  Draft ready → View in Drafts
                </button>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={() => onDismiss(item.id)}
            className="mt-2 block text-xs text-white/30 transition-colors hover:text-white/50"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

interface BadgeProps {
  value: QueueClassification
  onChange: (value: QueueClassification) => void
}

/** Classification pill that doubles as a dropdown to reclassify the email. */
function ClassificationBadge({ value, onChange }: BadgeProps) {
  return (
    <div className="relative" onClick={(event) => event.stopPropagation()}>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as QueueClassification)}
        className={`cursor-pointer appearance-none rounded-full px-2.5 py-1 pr-6 text-xs font-medium capitalize outline-none ${CLASSIFICATION_COLORS[value]}`}
      >
        {CLASSIFICATIONS.map((option) => (
          <option key={option} value={option} className="bg-[#1a1a1a] text-white">
            {option}
          </option>
        ))}
      </select>
      <HiOutlineChevronDown
        size={12}
        className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70"
      />
    </div>
  )
}

export default InboxPage
