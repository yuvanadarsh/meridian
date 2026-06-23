import { useEffect, useState } from 'react'

import { api } from '../../api/client'

interface UsageToday {
  total_tokens_today: number
  total_cost_today: number
  total_cost_month: number
  by_provider: Record<
    string,
    {
      model: string
      types: Record<string, { units: number; cost_usd: number }>
      total_cost: number
    }
  >
}

const USAGE_TYPE_LABELS: Record<string, string> = {
  input_tokens: 'Input',
  output_tokens: 'Output',
  characters: 'Characters',
  embed_tokens: 'Embedded',
}

/**
 * Top-right usage display. Default view shows tokens + daily + monthly cost.
 * Hover reveals a per-provider breakdown with input/output split and line-item costs.
 * Refreshes every 30s from /usage/today; falls back gracefully when the API is down.
 */
export function TokenCounter() {
  const [usage, setUsage] = useState<UsageToday | null>(null)
  const [hovered, setHovered] = useState(false)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await api.getUsageToday()
        if (active) setUsage(data)
      } catch {
        // Backend may be offline — leave the last known values in place.
      }
    }
    void load()
    const interval = window.setInterval(load, 30_000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  if (!usage) return null

  const providers = Object.entries(usage.by_provider)

  return (
    <div
      className="fixed right-4 top-4 z-10 select-none font-mono"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Default display */}
      <div className="cursor-default text-right text-xs text-white/30">
        <span>Tokens: {usage.total_tokens_today.toLocaleString()}</span>
        <span className="mx-1 text-white/15">·</span>
        <span>Today: ${usage.total_cost_today.toFixed(3)}</span>
        <span className="mx-1 text-white/15">·</span>
        <span>Month: ${usage.total_cost_month.toFixed(2)}</span>
      </div>

      {/* Hover breakdown */}
      {hovered && providers.length > 0 && (
        <div className="absolute right-0 top-full mt-1 w-72 rounded-xl border border-white/10 bg-[#111] p-4 shadow-xl">
          <div className="mb-3 text-xs font-medium text-white/60">Today's Usage</div>

          {providers.map(([provider, data]) => (
            <div key={provider} className="mb-3">
              <div className="mb-1 text-xs capitalize text-white/50">
                {provider}
                {data.model ? (
                  <span className="ml-1 text-white/30">({data.model})</span>
                ) : null}
              </div>
              {Object.entries(data.types).map(([type, info]) => (
                <div key={type} className="flex justify-between pl-2 text-xs text-white/40">
                  <span>
                    {USAGE_TYPE_LABELS[type] ?? type}: {info.units.toLocaleString()}
                  </span>
                  <span>${info.cost_usd.toFixed(4)}</span>
                </div>
              ))}
            </div>
          ))}

          <div className="mt-2 border-t border-white/10 pt-2">
            <div className="flex justify-between text-xs text-white/60">
              <span>Today total</span>
              <span>${usage.total_cost_today.toFixed(4)}</span>
            </div>
            <div className="flex justify-between text-xs text-white/40">
              <span>This month</span>
              <span>${usage.total_cost_month.toFixed(2)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default TokenCounter
