import { useEffect, useState } from 'react'

import { api } from '../../api/client'
import { useMeridianStore } from '../../store/meridianStore'

/**
 * Top-right token usage readout. Polls the backend on mount and every 60s, and
 * stays in sync with the store (which chat updates immediately after a reply).
 * Hover reveals the input/output breakdown.
 */
export function TokenCounter() {
  const tokensToday = useMeridianStore((state) => state.tokensToday)
  const setTokensToday = useMeridianStore((state) => state.setTokensToday)
  const [breakdown, setBreakdown] = useState({ input: 0, output: 0 })

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const tokens = await api.getTokensToday()
        if (!active) return
        setTokensToday(tokens.total)
        setBreakdown({ input: tokens.input, output: tokens.output })
      } catch {
        // Backend may be offline — leave the last known values in place.
      }
    }
    void load()
    const interval = window.setInterval(load, 60_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [setTokensToday])

  return (
    <div className="group fixed right-4 top-4 z-10 select-none font-mono text-xs text-white/40">
      <span>Tokens today: {tokensToday.toLocaleString()}</span>
      <span className="ml-2 hidden text-white/25 group-hover:inline">
        Input: {breakdown.input.toLocaleString()} · Output: {breakdown.output.toLocaleString()}
      </span>
    </div>
  )
}

export default TokenCounter
