import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { FiCheck, FiKey, FiPlus, FiTrash2, FiX } from 'react-icons/fi'
import {
  HiChevronDown,
  HiOutlineCalendar,
  HiOutlineCircleStack,
  HiOutlineDocumentText,
  HiOutlineEnvelope,
  HiOutlineExclamationTriangle,
} from 'react-icons/hi2'

import { api } from '../../api/client'
import type { GmailAccount } from '../../api/client'
import { useMeridianStore } from '../../store/meridianStore'

/** "Synced 5 min ago" style relative time, or null when never swept. */
function relativeTime(iso: string | null): string | null {
  if (!iso) return null
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days > 1 ? 's' : ''} ago`
}

/**
 * Lists every connected Google account. The collapsed row shows only the
 * account label, email, and sync status. Expanding reveals four integration
 * rows (Sweep, Threads, Obsidian, Calendar) each with its own action button
 * and live status. Only one accordion is open at a time.
 */
export function ConnectionsPanel() {
  const setOnboardingAccountId = useMeridianStore((state) => state.setOnboardingAccountId)
  const setTriageReviewAccountId = useMeridianStore((state) => state.setTriageReviewAccountId)
  const setMenuOpen = useMeridianStore((state) => state.setMenuOpen)
  const setActivePanel = useMeridianStore((state) => state.setActivePanel)

  const [accounts, setAccounts] = useState<GmailAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [openAccordionId, setOpenAccordionId] = useState<number | null>(null)

  const [syncingId, setSyncingId] = useState<number | null>(null)
  const [calendarSyncedId, setCalendarSyncedId] = useState<number | null>(null)

  const [exportingObsidianId, setExportingObsidianId] = useState<number | null>(null)
  const [obsidianProgress, setObsidianProgress] = useState<
    Record<number, { processed: number; total: number; done: boolean }>
  >({})

  // Thread build state per account
  const [threadCounts, setThreadCounts] = useState<
    Record<number, { processed: number; total: number }>
  >({})
  const [buildingThreadsId, setBuildingThreadsId] = useState<number | null>(null)
  const threadPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const loaded = await api.getAccounts()
      setAccounts(loaded)
      const [counts, obsidianProgresses] = await Promise.all([
        Promise.all(
          loaded.map((a) => api.getThreadsCount(a.id).catch(() => ({ processed: 0, total: 0 }))),
        ),
        Promise.all(
          loaded.map((a) =>
            api.getObsidianExportProgress(a.id).catch(() => ({ processed: 0, total: 0, done: false })),
          ),
        ),
      ])
      const countMap: Record<number, { processed: number; total: number }> = {}
      const obsidianMap: Record<number, { processed: number; total: number; done: boolean }> = {}
      loaded.forEach((a, i) => {
        countMap[a.id] = counts[i]
        const op = obsidianProgresses[i]
        obsidianMap[a.id] = { processed: op.processed, total: op.total, done: op.done ?? false }
      })
      setThreadCounts(countMap)
      setObsidianProgress(obsidianMap)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load accounts')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    return () => {
      if (threadPollRef.current) clearInterval(threadPollRef.current)
    }
  }, [])

  const connect = async (label: string) => {
    const trimmed = label.trim()
    if (!trimmed) return
    try {
      const { url } = await api.getAuthUrl(trimmed)
      window.location.assign(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start sign-in')
    }
  }

  const saveLabel = async (accountId: number) => {
    const trimmed = editLabel.trim()
    if (!trimmed) return
    try {
      await api.updateAccount(accountId, trimmed)
      setEditingId(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not rename account')
    }
  }

  const remove = async (account: GmailAccount) => {
    if (
      !window.confirm(
        `Remove ${account.email}? Its swept emails and calendar events are deleted from Meridian.`,
      )
    ) {
      return
    }
    try {
      await api.deleteAccount(account.id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove account')
    }
  }

  const sweep = (accountId: number) => {
    setOnboardingAccountId(accountId)
    setActivePanel(null)
    setMenuOpen(false)
  }

  const reviewTriage = (accountId: number) => {
    setTriageReviewAccountId(accountId)
    setActivePanel(null)
    setMenuOpen(false)
  }

  const buildThreadsForAccount = async (accountId: number) => {
    if (buildingThreadsId !== null) return
    setBuildingThreadsId(accountId)
    try {
      await api.buildThreads(accountId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Thread build failed')
      setBuildingThreadsId(null)
      return
    }
    // Poll progress every 3 seconds until complete.
    threadPollRef.current = setInterval(async () => {
      try {
        const progress = await api.getThreadsProgress(accountId)
        setThreadCounts((prev) => ({ ...prev, [accountId]: progress }))
        if (progress.total > 0 && progress.processed >= progress.total) {
          if (threadPollRef.current) clearInterval(threadPollRef.current)
          setBuildingThreadsId(null)
        }
      } catch {
        if (threadPollRef.current) clearInterval(threadPollRef.current)
        setBuildingThreadsId(null)
      }
    }, 3000)
  }

  const syncCalendar = async (accountId: number) => {
    setSyncingId(accountId)
    try {
      await api.syncCalendar(accountId)
      setCalendarSyncedId(accountId)
      setTimeout(
        () => setCalendarSyncedId((prev) => (prev === accountId ? null : prev)),
        2000,
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calendar sync failed')
    } finally {
      setSyncingId(null)
    }
  }

  const exportToObsidian = async (accountId: number) => {
    setExportingObsidianId(accountId)
    setObsidianProgress((prev) => ({
      ...prev,
      [accountId]: { processed: 0, total: 0, done: false },
    }))
    try {
      await api.exportThreadsToObsidian(accountId)
      const poll = setInterval(async () => {
        try {
          const progress = await api.getObsidianExportProgress(accountId)
          setObsidianProgress((prev) => ({
            ...prev,
            [accountId]: {
              processed: progress.processed,
              total: progress.total,
              done: progress.done ?? false,
            },
          }))
          if (progress.done) {
            clearInterval(poll)
            setExportingObsidianId(null)
          }
        } catch {
          clearInterval(poll)
          setExportingObsidianId(null)
        }
      }, 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Obsidian export failed')
      setExportingObsidianId(null)
    }
  }

  const toggleAccordion = (accountId: number) => {
    setOpenAccordionId((prev) => (prev === accountId ? null : accountId))
  }

  const expiredAccounts = accounts.filter((a) => a.auth_status === 'expired')

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-white/50">
        Connect any number of Google accounts. One sign-in covers Gmail and Calendar.
      </p>

      {expiredAccounts.map((a) => (
        <div
          key={`expired-${a.id}`}
          className="flex items-center justify-between gap-3 rounded-xl border border-amber-400/20 bg-amber-400/5 px-4 py-2.5"
        >
          <div className="flex items-center gap-2 text-sm text-amber-300/80">
            <HiOutlineExclamationTriangle className="h-4 w-4 shrink-0" />
            <span className="capitalize">{a.label || a.email}</span>
            <span className="text-amber-300/50">account needs re-authentication</span>
          </div>
          <button
            type="button"
            onClick={() => api.reauthAccount(a.id)}
            className="shrink-0 rounded-full border border-amber-400/25 px-3 py-1 text-xs text-amber-300/80 transition-all hover:border-amber-400/40 hover:bg-amber-400/10 hover:text-amber-200"
          >
            Re-authenticate
          </button>
        </div>
      ))}

      {error && <p className="text-sm text-rose-300/80">{error}</p>}

      <div className="flex flex-col gap-2">
        {!loading && accounts.length === 0 && (
          <p className="text-sm text-white/30">No accounts connected yet.</p>
        )}

        {accounts.map((account) => {
          const synced = relativeTime(account.last_synced_at)
          const isOpen = openAccordionId === account.id
          const isSyncing = syncingId === account.id
          const threadCount = threadCounts[account.id]
          const isBuilding = buildingThreadsId === account.id
          const threadsBuilt =
            threadCount &&
            threadCount.total > 0 &&
            threadCount.processed >= threadCount.total
          const isExportingObsidian = exportingObsidianId === account.id
          const obsidianProg = obsidianProgress[account.id]

          // Derive integration status strings
          const sweepStatus = synced ? `Last synced: ${synced}` : 'Never synced'
          const threadStatus = isBuilding
            ? threadCount && threadCount.total > 0
              ? `Building… ${threadCount.processed} / ${threadCount.total}`
              : 'Building…'
            : threadCount && threadCount.processed > 0
              ? `${threadCount.processed} threads built`
              : 'No threads built'
          const isExported = (obsidianProg?.processed ?? 0) > 0 || (obsidianProg?.total ?? 0) > 0
          const obsidianStatus = isExportingObsidian && obsidianProg
            ? `Writing… ${obsidianProg.processed} / ${obsidianProg.total}`
            : isExported
              ? `${obsidianProg!.total} notes in vault`
              : 'Not exported'
          const calendarStatus = calendarSyncedId === account.id
            ? 'Synced just now'
            : synced
              ? `Last synced: ${synced}`
              : 'Never synced'

          return (
            <div
              key={account.id}
              className="overflow-hidden rounded-xl border border-white/10 bg-white/5"
            >
              {/* Collapsed header — label, email, sync status, trash, chevron */}
              <div className="flex items-center gap-3 px-4 py-3">
                {/* Account info (left, grows) */}
                <div className="min-w-0 flex-1">
                  {editingId === account.id ? (
                    <div className="flex items-center gap-1.5">
                      <input
                        autoFocus
                        value={editLabel}
                        onChange={(event) => setEditLabel(event.target.value)}
                        onKeyDown={(event) =>
                          event.key === 'Enter' && void saveLabel(account.id)
                        }
                        className="w-28 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-sm text-white focus:border-white/30 focus:outline-none"
                        aria-label="Account label"
                      />
                      <button
                        type="button"
                        aria-label="Save label"
                        onClick={() => void saveLabel(account.id)}
                        className="text-white/60 hover:text-white"
                      >
                        <FiCheck size={16} />
                      </button>
                      <button
                        type="button"
                        aria-label="Cancel"
                        onClick={() => setEditingId(null)}
                        className="text-white/40 hover:text-white"
                      >
                        <FiX size={16} />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(account.id)
                        setEditLabel(account.label ?? '')
                      }}
                      className="text-sm font-medium capitalize text-white hover:underline"
                      title="Rename"
                    >
                      {account.label || 'unlabeled'}
                    </button>
                  )}
                  <div className="truncate text-xs text-white/40">{account.email}</div>
                  <div className="text-xs text-white/30">
                    {synced ? `Synced ${synced}` : 'Not swept yet'}
                    {threadCount && threadCount.processed > 0 && (
                      <span className="ml-2 text-white/20">
                        · {threadCount.processed} threads
                      </span>
                    )}
                  </div>
                </div>

                {/* Right controls — re-auth (when expired), trash, expand */}
                <div className="flex shrink-0 items-center gap-1">
                  {account.auth_status === 'expired' && (
                    <button
                      type="button"
                      aria-label={`Re-authenticate ${account.email}`}
                      title="Token expired — click to re-authenticate"
                      onClick={() => api.reauthAccount(account.id)}
                      className="flex h-7 w-7 items-center justify-center rounded-full text-amber-400/60 transition-colors hover:bg-amber-400/10 hover:text-amber-300"
                    >
                      <FiKey size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label={`Remove ${account.email}`}
                    onClick={() => void remove(account)}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-white/40 transition-colors hover:bg-rose-400/10 hover:text-rose-300"
                  >
                    <FiTrash2 size={14} />
                  </button>
                  <button
                    type="button"
                    aria-label={isOpen ? 'Collapse integrations' : 'Expand integrations'}
                    onClick={() => toggleAccordion(account.id)}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-white/40 transition-colors hover:bg-white/10 hover:text-white"
                  >
                    <motion.span
                      animate={{ rotate: isOpen ? 180 : 0 }}
                      transition={{ duration: 0.2 }}
                      className="flex"
                    >
                      <HiChevronDown size={14} />
                    </motion.span>
                  </button>
                </div>
              </div>

              {/* Expanded integrations accordion */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    key="integrations"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: 'easeInOut' }}
                    className="overflow-hidden"
                  >
                    <div className="px-4 pb-3">
                      {/* 1 — Sweep */}
                      <IntegrationRow
                        icon={<HiOutlineEnvelope className="h-4 w-4 text-white/40" />}
                        name="Sweep"
                        status={sweepStatus}
                      >
                        {account.sweep_status === 'triage_complete' ? (
                          <ActionButton
                            amber
                            onClick={() => reviewTriage(account.id)}
                          >
                            Review triage
                          </ActionButton>
                        ) : (
                          <ActionButton onClick={() => sweep(account.id)}>
                            {synced ? 'Re-sweep' : 'Sweep'}
                          </ActionButton>
                        )}
                      </IntegrationRow>

                      {/* 2 — Threads */}
                      <IntegrationRow
                        icon={<HiOutlineCircleStack className="h-4 w-4 text-white/40" />}
                        name="Threads"
                        status={threadStatus}
                      >
                        <ActionButton
                          disabled={isBuilding || !synced}
                          onClick={() => void buildThreadsForAccount(account.id)}
                        >
                          {isBuilding ? (
                            <>
                              <span className="h-2.5 w-2.5 animate-spin rounded-full border border-white/40 border-t-white/70" />
                              Building…
                            </>
                          ) : threadsBuilt ? (
                            'Threads built ✓'
                          ) : (
                            'Build threads'
                          )}
                        </ActionButton>
                      </IntegrationRow>

                      {/* 3 — Obsidian */}
                      <IntegrationRow
                        icon={<HiOutlineDocumentText className="h-4 w-4 text-white/40" />}
                        name="Obsidian"
                        status={obsidianStatus}
                      >
                        <ActionButton
                          disabled={isExportingObsidian || !synced}
                          onClick={() => void exportToObsidian(account.id)}
                        >
                          {isExportingObsidian ? (
                            <>
                              <span className="h-2.5 w-2.5 animate-spin rounded-full border border-white/40 border-t-white/70" />
                              Exporting…
                            </>
                          ) : isExported ? (
                            'Re-export'
                          ) : (
                            'Export to Obsidian'
                          )}
                        </ActionButton>
                      </IntegrationRow>

                      {/* 4 — Calendar */}
                      <IntegrationRow
                        icon={<HiOutlineCalendar className="h-4 w-4 text-white/40" />}
                        name="Calendar"
                        status={calendarStatus}
                        last
                      >
                        <ActionButton
                          disabled={isSyncing}
                          onClick={() => void syncCalendar(account.id)}
                        >
                          {isSyncing ? (
                            <>
                              <span className="h-2.5 w-2.5 animate-spin rounded-full border border-white/40 border-t-white/70" />
                              Syncing…
                            </>
                          ) : calendarSyncedId === account.id ? (
                            'Synced ✓'
                          ) : (
                            'Sync now'
                          )}
                        </ActionButton>
                      </IntegrationRow>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </div>

      {/* Add account */}
      {adding ? (
        <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3">
          <input
            autoFocus
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && void connect(newLabel)}
            placeholder="Label (e.g. personal, work)"
            aria-label="New account label"
            className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-sm text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => void connect(newLabel)}
            disabled={!newLabel.trim()}
            className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            Connect
          </button>
          <button
            type="button"
            aria-label="Cancel"
            onClick={() => {
              setAdding(false)
              setNewLabel('')
            }}
            className="text-white/40 hover:text-white"
          >
            <FiX size={16} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-white/15 px-4 py-3 text-sm text-white/60 transition-colors hover:border-white/30 hover:text-white"
        >
          <FiPlus size={16} /> Add account
        </button>
      )}
    </div>
  )
}

/** One row in the integrations accordion. */
function IntegrationRow({
  icon,
  name,
  status,
  last = false,
  children,
}: {
  icon: React.ReactNode
  name: string
  status: string
  last?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={`flex items-center justify-between py-2 ${last ? '' : 'border-b border-white/[0.05]'}`}
    >
      <div className="flex items-center gap-3">
        {icon}
        <div>
          <div className="text-sm text-white/80">{name}</div>
          <div className="text-xs text-white/40">{status}</div>
        </div>
      </div>
      {children}
    </div>
  )
}

/** Consistent pill button for integration row actions. */
function ActionButton({
  children,
  disabled = false,
  amber = false,
  onClick,
}: {
  children: React.ReactNode
  disabled?: boolean
  amber?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-all disabled:opacity-40 ${
        amber
          ? 'border-amber-400/25 text-amber-300/80 hover:border-amber-400/40 hover:bg-amber-400/10 hover:text-amber-200'
          : 'border-white/15 text-white/60 hover:border-white/30 hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

export default ConnectionsPanel
