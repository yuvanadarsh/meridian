import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { FiArrowRight, FiCheck, FiLoader } from 'react-icons/fi'

import { api } from '../../api/client'
import type {
  GmailAccount,
  SweepMode,
  SweepProgress,
  TriageCounts,
} from '../../api/client'

type Step = 'options' | 'progress' | 'done'

interface OnboardingProps {
  accountId: number
  onClose: () => void
}

/**
 * Full-screen account onboarding: choose how much history to sweep, then watch
 * live progress. Triage review and vectorization extend this flow in later
 * steps; the sweep itself is resumable, so closing and reopening is safe.
 */
export function Onboarding({ accountId, onClose }: OnboardingProps) {
  const [account, setAccount] = useState<GmailAccount | null>(null)
  const [estimate, setEstimate] = useState<number | null>(null)
  const [step, setStep] = useState<Step>('options')
  const [mode, setMode] = useState<SweepMode>('all')
  const [count, setCount] = useState(500)
  const [sinceDate, setSinceDate] = useState('')
  const [progress, setProgress] = useState<SweepProgress | null>(null)
  const [counts, setCounts] = useState<TriageCounts | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Load the account label/email and a rough mailbox-size estimate.
  useEffect(() => {
    let cancelled = false
    api
      .getAccounts()
      .then((accounts) => {
        if (!cancelled) setAccount(accounts.find((a) => a.id === accountId) ?? null)
      })
      .catch(() => {})
    api
      .getEstimate(accountId)
      .then((result) => {
        if (!cancelled) setEstimate(result.estimated_count)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [accountId])

  // Poll sweep progress every 2s while the sweep is running.
  useEffect(() => {
    if (step !== 'progress') return
    let cancelled = false
    const tick = async () => {
      try {
        const next = await api.getSweepProgress(accountId)
        if (cancelled) return
        setProgress(next)
        if (next.status === 'completed' || next.status === 'triage_complete') {
          try {
            const results = await api.getTriageResults(accountId)
            if (!cancelled) setCounts(results.counts)
          } catch {
            // Counts are best-effort; the done screen falls back to the tally.
          }
          if (!cancelled) setStep('done')
        } else if (next.status === 'error') {
          setError(next.error || 'The sweep failed.')
        }
      } catch {
        // Transient failure — keep polling.
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 2000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [step, accountId])

  const startSweep = async () => {
    setError(null)
    try {
      await api.startSweep(accountId, {
        mode,
        count: mode === 'count' ? count : null,
        since_date: mode === 'since' ? sinceDate : null,
      })
      setProgress(null)
      setStep('progress')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the sweep.')
    }
  }

  const fetchedPct = useMemo(() => {
    if (!progress || progress.total_estimated <= 0) return 0
    return Math.min(100, Math.round((progress.fetched / progress.total_estimated) * 100))
  }, [progress])

  const email = account?.email ?? 'your account'

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-[#0a0a0a] bg-[radial-gradient(ellipse_at_center,_#111827_0%,_#0a0a0a_70%)] px-4 py-12 text-white"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      <div className="w-full max-w-lg">
        {step === 'options' && (
          <div className="flex flex-col gap-6">
            <div>
              <div className="text-xs uppercase tracking-wide text-emerald-300/80">
                Account connected
              </div>
              <div className="mt-1 text-xl font-semibold">{email}</div>
              {account?.label && (
                <div className="mt-1 text-sm capitalize text-white/40">
                  Label: {account.label}
                </div>
              )}
            </div>

            <div>
              <p className="mb-3 text-sm text-white/70">
                How much email history do you want to sweep?
              </p>
              <div className="flex flex-col gap-2">
                <OptionRow
                  selected={mode === 'all'}
                  onSelect={() => setMode('all')}
                  label="All emails"
                  hint="recommended for first setup"
                />
                <OptionRow
                  selected={mode === 'count'}
                  onSelect={() => setMode('count')}
                  label="Last"
                  control={
                    <input
                      type="number"
                      min={1}
                      value={count}
                      onChange={(event) => setCount(Math.max(1, Number(event.target.value) || 1))}
                      onClick={(event) => event.stopPropagation()}
                      className="w-24 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-white focus:border-white/30 focus:outline-none"
                    />
                  }
                  suffix="emails"
                />
                <OptionRow
                  selected={mode === 'since'}
                  onSelect={() => setMode('since')}
                  label="Emails since"
                  control={
                    <input
                      type="date"
                      value={sinceDate}
                      onChange={(event) => setSinceDate(event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                      className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-white focus:border-white/30 focus:outline-none"
                    />
                  }
                />
              </div>

              {estimate !== null && (
                <p className="mt-3 text-xs text-white/40">
                  ≈ {estimate.toLocaleString()} emails in this mailbox.
                  {mode === 'count' && count > estimate && " We'll sweep all of them."}
                </p>
              )}
            </div>

            {error && <p className="text-sm text-rose-300/80">{error}</p>}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void startSweep()}
                disabled={mode === 'since' && !sinceDate}
                className="flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                Start Sweep <FiArrowRight size={16} />
              </button>
              <button
                type="button"
                onClick={onClose}
                className="text-sm text-white/40 transition-colors hover:text-white/70"
              >
                Skip for now
              </button>
            </div>
          </div>
        )}

        {step === 'progress' && (
          <div className="flex flex-col gap-6">
            <div className="text-xl font-semibold">Sweeping {email}</div>

            <div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <motion.div
                  className="h-full rounded-full bg-white/70"
                  animate={{ width: `${fetchedPct}%` }}
                  transition={{ duration: 0.4 }}
                />
              </div>
              <div className="mt-2 text-sm text-white/60">
                {progress?.fetched.toLocaleString() ?? 0}
                {progress && progress.total_estimated > 0
                  ? ` / ${progress.total_estimated.toLocaleString()}`
                  : ''}{' '}
                emails fetched
              </div>
            </div>

            <div className="flex flex-col gap-2.5">
              <PhaseRow done label="Fetching email metadata" />
              <PhaseRow done label="Parsing message bodies" />
              <PhaseRow done={false} label="Classifying with AI…" />
            </div>

            {error && <p className="text-sm text-rose-300/80">{error}</p>}

            <button
              type="button"
              onClick={onClose}
              className="self-start text-sm text-white/40 transition-colors hover:text-white/70"
            >
              Run in background
            </button>
          </div>
        )}

        {step === 'done' && (
          <div className="flex flex-col items-center gap-5 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300">
              <FiCheck size={24} />
            </div>
            <div className="text-xl font-semibold">
              {counts ? 'Inbox analyzed' : 'Sweep complete'}
            </div>
            <p className="text-sm text-white/60">
              Swept {progress?.stored.toLocaleString() ?? 0} new emails from {email}
              {progress && progress.skipped > 0
                ? ` (${progress.skipped.toLocaleString()} already synced).`
                : '.'}
            </p>

            {counts && (
              <div className="flex gap-3">
                <CountPill label="Trash" value={counts.trash} tone="rose" />
                <CountPill label="Archive" value={counts.archive} tone="sky" />
                <CountPill label="Keep" value={counts.keep} tone="emerald" />
              </div>
            )}

            <button
              type="button"
              onClick={onClose}
              className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </motion.div>
  )
}

interface OptionRowProps {
  selected: boolean
  onSelect: () => void
  label: string
  hint?: string
  control?: React.ReactNode
  suffix?: string
}

/** A single radio-style sweep option, optionally with an inline input. */
function OptionRow({ selected, onSelect, label, hint, control, suffix }: OptionRowProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${
        selected ? 'border-white/30 bg-white/10' : 'border-white/10 bg-white/5 hover:bg-white/[0.07]'
      }`}
    >
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
          selected ? 'border-white' : 'border-white/30'
        }`}
      >
        {selected && <span className="h-2 w-2 rounded-full bg-white" />}
      </span>
      <span className="flex flex-wrap items-center gap-2 text-sm text-white">
        {label}
        {control}
        {suffix && <span className="text-white/60">{suffix}</span>}
        {hint && <span className="text-white/40">({hint})</span>}
      </span>
    </button>
  )
}

/** A pipeline step: a check when finished, a spinner while in progress. */
function PhaseRow({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2.5 text-sm">
      {done ? (
        <FiCheck className="text-emerald-300" size={16} />
      ) : (
        <FiLoader className="animate-spin text-white/50" size={16} />
      )}
      <span className={done ? 'text-white/70' : 'text-white'}>{label}</span>
    </div>
  )
}

const COUNT_TONES = {
  rose: 'text-rose-300',
  sky: 'text-sky-300',
  emerald: 'text-emerald-300',
} as const

/** A single triage-category tally shown after classification. */
function CountPill({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: keyof typeof COUNT_TONES
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
      <div className={`text-lg font-semibold ${COUNT_TONES[tone]}`}>
        {value.toLocaleString()}
      </div>
      <div className="text-xs text-white/40">{label}</div>
    </div>
  )
}

export default Onboarding
