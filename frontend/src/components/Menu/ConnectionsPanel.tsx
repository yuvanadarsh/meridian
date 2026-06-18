import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { FiCheck, FiPlus, FiTrash2, FiX } from 'react-icons/fi'
import { HiChevronDown, HiOutlineCalendar } from 'react-icons/hi2'

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
 * Lists every connected Google account with inline label editing, a sweep
 * shortcut into onboarding, and removal. Each account has an expandable
 * calendar-sync accordion. Only one accordion can be open at a time.
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

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setAccounts(await api.getAccounts())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load accounts')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
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

  const syncCalendar = async (accountId: number) => {
    setSyncingId(accountId)
    try {
      await api.syncCalendar(accountId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calendar sync failed')
    } finally {
      setSyncingId(null)
    }
  }

  const toggleAccordion = (accountId: number) => {
    setOpenAccordionId((prev) => (prev === accountId ? null : accountId))
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-white/50">
        Connect any number of Google accounts. One sign-in covers Gmail and Calendar.
      </p>

      {error && <p className="text-sm text-rose-300/80">{error}</p>}

      <div className="flex flex-col gap-2">
        {!loading && accounts.length === 0 && (
          <p className="text-sm text-white/30">No accounts connected yet.</p>
        )}

        {accounts.map((account) => {
          const synced = relativeTime(account.last_synced_at)
          const isOpen = openAccordionId === account.id
          const isSyncing = syncingId === account.id

          return (
            <div
              key={account.id}
              className="overflow-hidden rounded-xl border border-white/10 bg-white/5"
            >
              {/* Account row */}
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  {editingId === account.id ? (
                    <div className="flex items-center gap-1.5">
                      <input
                        autoFocus
                        value={editLabel}
                        onChange={(event) => setEditLabel(event.target.value)}
                        onKeyDown={(event) => event.key === 'Enter' && void saveLabel(account.id)}
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
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  {account.sweep_status === 'triage_complete' && (
                    <button
                      type="button"
                      onClick={() => reviewTriage(account.id)}
                      className="rounded-full border border-amber-400/25 px-3 py-1 text-xs text-amber-300/80 transition-colors hover:bg-amber-400/10 hover:text-amber-200"
                    >
                      Review triage
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => sweep(account.id)}
                    className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white"
                  >
                    {synced ? 'Re-sweep' : 'Sweep'}
                  </button>
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
                    aria-label={isOpen ? 'Collapse calendar section' : 'Expand calendar section'}
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

              {/* Calendar accordion */}
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    key="calendar-accordion"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: 'easeInOut' }}
                    className="overflow-hidden"
                  >
                    <div className="flex items-center justify-between border-t border-white/[0.06] px-4 py-3">
                      <div className="flex items-center gap-2">
                        <HiOutlineCalendar size={14} className="shrink-0 text-white/50" />
                        <div>
                          <div className="text-xs font-medium text-white/70">
                            Calendar Integration
                          </div>
                          <div className="text-xs text-white/30">
                            {synced ? `Last synced: ${synced}` : 'Never synced'}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        disabled={isSyncing}
                        onClick={() => void syncCalendar(account.id)}
                        className="flex items-center gap-1.5 rounded-full border border-white/15 px-3 py-1 text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
                      >
                        {isSyncing ? (
                          <>
                            <span className="h-3 w-3 animate-spin rounded-full border border-white/40 border-t-white/80" />
                            Syncing
                          </>
                        ) : (
                          'Sync now'
                        )}
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </div>

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

export default ConnectionsPanel
