import { useEffect, useState } from 'react'

import { api } from '../../api/client'
import type { GmailAccount } from '../../api/client'

/** The four account roles Meridian supports. */
const SLOTS = ['personal', 'school', 'work', 'professional'] as const

/**
 * Lists the Gmail accounts connected per role and offers a Connect button for
 * empty slots. Connecting kicks off the Google OAuth redirect.
 */
export function ConnectionsPanel() {
  const [accounts, setAccounts] = useState<GmailAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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
    try {
      const { url } = await api.getAuthUrl(label)
      window.location.assign(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start sign-in')
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-white/50">
        Connect a Google account per role. One sign-in covers Gmail and Calendar.
      </p>

      {error && <p className="text-sm text-rose-300/80">{error}</p>}

      <div className="flex flex-col gap-2">
        {SLOTS.map((slot) => {
          const account = accounts.find((item) => item.label === slot)
          return (
            <div
              key={slot}
              className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3"
            >
              <div>
                <div className="text-sm font-medium capitalize text-white">{slot}</div>
                <div className="text-xs text-white/40">
                  {account ? account.email : loading ? 'Checking…' : 'Not connected'}
                </div>
              </div>

              {account ? (
                <span className="rounded-full bg-emerald-400/10 px-3 py-1 text-xs text-emerald-300/90">
                  Connected
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => void connect(slot)}
                  className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white"
                >
                  Connect
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ConnectionsPanel
