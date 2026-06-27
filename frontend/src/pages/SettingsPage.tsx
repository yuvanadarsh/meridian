import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'
import { AIProvidersSection } from '../components/Menu/AIProvidersSection'
import { EmbeddingsSection } from '../components/Menu/EmbeddingsSection'
import { ScheduledTasksSection } from '../components/Settings/ScheduledTasksSection'
import { SettingsCard } from '../components/Settings/SettingsCard'
import { Toggle } from '../components/Settings/Toggle'

type Tone = 'concise' | 'moderate' | 'conversational'
type TriageMode = 'aggressive' | 'normal' | 'safe'

const TONES: { value: Tone; label: string }[] = [
  { value: 'concise', label: 'Concise' },
  { value: 'moderate', label: 'Moderate' },
  { value: 'conversational', label: 'Conversational' },
]

const TRIAGE_MODES: { value: TriageMode; label: string }[] = [
  { value: 'aggressive', label: 'Aggressive' },
  { value: 'normal', label: 'Normal' },
  { value: 'safe', label: 'Safe' },
]

const TIMEZONES: { value: string; label: string }[] = [
  { value: 'America/New_York', label: 'Eastern (ET)' },
  { value: 'America/Chicago', label: 'Central (CT)' },
  { value: 'America/Denver', label: 'Mountain (MT)' },
  { value: 'America/Los_Angeles', label: 'Pacific (PT)' },
  { value: 'America/Toronto', label: 'Toronto (ET)' },
  { value: 'Europe/London', label: 'London (GMT/BST)' },
  { value: 'Asia/Kolkata', label: 'India (IST)' },
]

/** A label on the left, a control on the right — the General card's row layout. */
function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 first:pt-0">
      <span className="text-sm text-white/70">{label}</span>
      {children}
    </div>
  )
}

/** Three-way segmented control used for tone and triage mode. */
function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="flex gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${
            value === option.value ? 'bg-white/15 text-white' : 'text-white/50 hover:text-white/80'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

/**
 * Settings page — full-width forge-style cards: General, Voice, AI Providers,
 * and Memory & Embeddings. Every value loads from and persists to the backend
 * (user_settings); writes are best-effort and fire as the user changes a field.
 */
export function SettingsPage() {
  const [tone, setTone] = useState<Tone>('concise')
  const [timezone, setTimezone] = useState('America/New_York')
  const [agentName, setAgentName] = useState('Meridian')
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [triageMode, setTriageMode] = useState<TriageMode>('normal')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    api
      .getSettings()
      .then((settings) => {
        if (!active) return
        if (settings.response_tone) setTone(settings.response_tone as Tone)
        if (settings.timezone) setTimezone(settings.timezone)
        if (settings.agent_name) setAgentName(settings.agent_name)
        if (settings.voice_enabled) setVoiceEnabled(settings.voice_enabled === 'true')
        if (settings.triage_mode) setTriageMode(settings.triage_mode as TriageMode)
      })
      .catch(() => {
        // Keep defaults on failure — the page stays usable.
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const persist = (key: string, value: string) => {
    void api.updateSetting(key, value).catch(() => {
      // Best-effort; the next change retries.
    })
  }

  return (
    <PageLayout title="Settings" subtitle="Configure your Meridian instance.">
      {loading ? (
        <p className="py-10 text-center text-sm text-white/40">Loading settings…</p>
      ) : (
        <div className="max-w-3xl">
          <SettingsCard title="General">
            <FieldRow label="Agent name">
              <input
                value={agentName}
                onChange={(event) => setAgentName(event.target.value)}
                onBlur={() => persist('agent_name', agentName)}
                className="w-56 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
              />
            </FieldRow>
            <FieldRow label="Response tone">
              <Segmented
                options={TONES}
                value={tone}
                onChange={(value) => {
                  setTone(value)
                  persist('response_tone', value)
                }}
              />
            </FieldRow>
            <FieldRow label="Triage mode">
              <Segmented
                options={TRIAGE_MODES}
                value={triageMode}
                onChange={(value) => {
                  setTriageMode(value)
                  persist('triage_mode', value)
                }}
              />
            </FieldRow>
            <FieldRow label="Timezone">
              <select
                value={timezone}
                onChange={(event) => {
                  setTimezone(event.target.value)
                  persist('timezone', event.target.value)
                }}
                className="w-56 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz.value} value={tz.value} className="bg-[#0d0d0f]">
                    {tz.label}
                  </option>
                ))}
              </select>
            </FieldRow>
          </SettingsCard>

          <SettingsCard title="Voice">
            <FieldRow label="Voice responses">
              <Toggle
                checked={voiceEnabled}
                label="Voice responses"
                onChange={(next) => {
                  setVoiceEnabled(next)
                  persist('voice_enabled', String(next))
                }}
              />
            </FieldRow>
          </SettingsCard>

          <SettingsCard
            title="AI Providers"
            description="Keys are stored encrypted in the database."
          >
            <AIProvidersSection />
          </SettingsCard>

          <SettingsCard
            title="Memory & Embeddings"
            description="Switching models invalidates all vector data and requires a full re-embed."
          >
            <EmbeddingsSection />
          </SettingsCard>

          <SettingsCard
            title="Scheduled Tasks"
            description="Automated tasks that run on a schedule."
          >
            <ScheduledTasksSection />
          </SettingsCard>
        </div>
      )}
    </PageLayout>
  )
}

export default SettingsPage
