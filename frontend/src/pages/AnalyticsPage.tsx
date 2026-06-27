import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '../api/client'
import type { UsageHistory, UsageTimeframe } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'

const PROVIDER_COLORS = {
  anthropic: '#f97316', // orange
  voyageai: '#3b82f6', // blue
  elevenlabs: '#8b5cf6', // purple
}

const TIMEFRAMES: { value: UsageTimeframe; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

type Metric = 'cost' | 'input' | 'output' | 'total'

const METRICS: { value: Metric; label: string }[] = [
  { value: 'cost', label: 'Cost' },
  { value: 'input', label: 'Input tokens' },
  { value: 'output', label: 'Output tokens' },
  { value: 'total', label: 'Total tokens' },
]

interface Series {
  dataKey: string
  name: string
  color: string
}

// Which bar series to render for each metric. Cost spans all three providers;
// input/output are Anthropic-specific; total compares total tokens per provider.
const METRIC_SERIES: Record<Metric, Series[]> = {
  cost: [
    { dataKey: 'anthropic_cost', name: 'Anthropic', color: PROVIDER_COLORS.anthropic },
    { dataKey: 'voyageai_cost', name: 'VoyageAI', color: PROVIDER_COLORS.voyageai },
    { dataKey: 'elevenlabs_cost', name: 'ElevenLabs', color: PROVIDER_COLORS.elevenlabs },
  ],
  input: [{ dataKey: 'anthropic_input', name: 'Anthropic', color: PROVIDER_COLORS.anthropic }],
  output: [{ dataKey: 'anthropic_output', name: 'Anthropic', color: PROVIDER_COLORS.anthropic }],
  total: [
    { dataKey: 'anthropic_tokens', name: 'Anthropic', color: PROVIDER_COLORS.anthropic },
    { dataKey: 'voyageai_tokens', name: 'VoyageAI', color: PROVIDER_COLORS.voyageai },
    { dataKey: 'elevenlabs_chars', name: 'ElevenLabs', color: PROVIDER_COLORS.elevenlabs },
  ],
}

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`
const num = (n: number) => n.toLocaleString()

/** Compact styled dropdown used for the timeframe and metric selectors. */
function Dropdown<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as T)}
      className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-white/30 focus:outline-none"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} className="bg-[#111] text-white">
          {option.label}
        </option>
      ))}
    </select>
  )
}

/** Summary stat card. */
function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
      <div className="text-xs text-white/40">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-white/30">{hint}</div>}
    </div>
  )
}

/**
 * Analytics — token usage and cost across all providers. A grouped bar chart
 * over a selectable timeframe and metric, summary cards, and a provider
 * breakdown for the selected period.
 */
export function AnalyticsPage() {
  const [timeframe, setTimeframe] = useState<UsageTimeframe>('weekly')
  const [metric, setMetric] = useState<Metric>('cost')
  const [history, setHistory] = useState<UsageHistory | null>(null)
  const [today, setToday] = useState<{ total_cost_today: number; total_cost_month: number } | null>(
    null,
  )
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([api.getUsageHistory(timeframe), api.getUsageToday()])
      .then(([hist, todayData]) => {
        if (cancelled) return
        setHistory(hist)
        setToday({
          total_cost_today: todayData.total_cost_today,
          total_cost_month: todayData.total_cost_month,
        })
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load analytics')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [timeframe])

  // Derive chart rows with the extra computed token fields the metrics need.
  const chartData = useMemo(
    () =>
      (history?.data ?? []).map((point) => ({
        ...point,
        anthropic_tokens: point.anthropic_input + point.anthropic_output,
      })),
    [history],
  )

  // Sum the timeframe into a provider breakdown (tokens + cost).
  const breakdown = useMemo(() => {
    const acc = {
      anthropic_input: 0,
      anthropic_output: 0,
      anthropic_cost: 0,
      voyageai_tokens: 0,
      voyageai_cost: 0,
      elevenlabs_chars: 0,
      elevenlabs_cost: 0,
    }
    for (const point of history?.data ?? []) {
      acc.anthropic_input += point.anthropic_input
      acc.anthropic_output += point.anthropic_output
      acc.anthropic_cost += point.anthropic_cost
      acc.voyageai_tokens += point.voyageai_tokens
      acc.voyageai_cost += point.voyageai_cost
      acc.elevenlabs_chars += point.elevenlabs_chars
      acc.elevenlabs_cost += point.elevenlabs_cost
    }
    return acc
  }, [history])

  const series = METRIC_SERIES[metric]
  const isCost = metric === 'cost'
  const periodLabel = TIMEFRAMES.find((t) => t.value === timeframe)?.label ?? ''

  return (
    <PageLayout
      title="Analytics"
      subtitle="Token usage and cost across all providers."
      actions={
        <>
          <Dropdown value={timeframe} options={TIMEFRAMES} onChange={setTimeframe} />
          <Dropdown value={metric} options={METRICS} onChange={setMetric} />
        </>
      }
    >
      {error && <p className="mb-4 text-sm text-rose-300/80">{error}</p>}

      {/* Usage overview chart */}
      <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
        <div className="mb-4 text-sm font-medium text-white">Usage Overview</div>
        {loading ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-white/30">
            Loading…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="label" stroke="rgba(255,255,255,0.3)" tick={{ fontSize: 12 }} />
              <YAxis
                stroke="rgba(255,255,255,0.3)"
                tick={{ fontSize: 12 }}
                tickFormatter={(value: number) => (isCost ? usd(value) : num(value))}
                width={isCost ? 56 : 64}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#111',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: '8px',
                }}
                labelStyle={{ color: 'rgba(255,255,255,0.6)' }}
                formatter={(value) => (isCost ? usd(Number(value)) : num(Number(value)))}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {series.map((s) => (
                <Bar
                  key={s.dataKey}
                  dataKey={s.dataKey}
                  name={s.name}
                  fill={s.color}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Summary cards */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Today" value={usd(today?.total_cost_today ?? 0)} />
        <StatCard label="This month" value={usd(today?.total_cost_month ?? 0)} />
        <StatCard
          label={`This ${periodLabel.toLowerCase()}`}
          value={usd(history?.totals.total_cost ?? 0)}
        />
      </div>

      {/* Provider breakdown */}
      <div className="mt-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
        <div className="mb-4 text-sm font-medium text-white">
          Provider Breakdown <span className="text-white/30">· {periodLabel}</span>
        </div>
        <div className="space-y-5 text-sm">
          <div>
            <div className="mb-1 font-medium text-white/80">Anthropic</div>
            <div className="flex justify-between text-white/50">
              <span>Input: {num(breakdown.anthropic_input)} tokens</span>
              <span className="text-white/70">{usd(breakdown.anthropic_cost)}</span>
            </div>
            <div className="text-white/50">Output: {num(breakdown.anthropic_output)} tokens</div>
          </div>
          <div>
            <div className="mb-1 font-medium text-white/80">VoyageAI</div>
            <div className="flex justify-between text-white/50">
              <span>Embedded: {num(breakdown.voyageai_tokens)} tokens</span>
              <span className="text-white/70">{usd(breakdown.voyageai_cost)}</span>
            </div>
          </div>
          <div>
            <div className="mb-1 font-medium text-white/80">ElevenLabs</div>
            <div className="flex justify-between text-white/50">
              <span>Characters: {num(breakdown.elevenlabs_chars)}</span>
              <span className="text-white/70">{usd(breakdown.elevenlabs_cost)}</span>
            </div>
          </div>
        </div>
      </div>
    </PageLayout>
  )
}

export default AnalyticsPage
