import { useEffect, useState } from 'react'

import { api } from '../../api/client'
import { AIProvidersSection } from './AIProvidersSection'

type Tone = 'concise' | 'moderate' | 'conversational'

const TONES: { value: Tone; label: string }[] = [
  { value: 'concise', label: 'Concise' },
  { value: 'moderate', label: 'Moderate' },
  { value: 'conversational', label: 'Conversational' },
]

// Half-hour options for the daily digest time picker.
const DIGEST_TIMES = Array.from({ length: 48 }, (_, i) => {
  const hour = String(Math.floor(i / 2)).padStart(2, '0')
  const minute = i % 2 === 0 ? '00' : '30'
  return `${hour}:${minute}`
})

const TIMEZONES: { value: string; label: string }[] = [
  { value: 'America/New_York', label: 'Eastern (ET)' },
  { value: 'America/Chicago', label: 'Central (CT)' },
  { value: 'America/Denver', label: 'Mountain (MT)' },
  { value: 'America/Los_Angeles', label: 'Pacific (PT)' },
  { value: 'America/Toronto', label: 'Toronto (ET)' },
  { value: 'Europe/London', label: 'London (GMT/BST)' },
  { value: 'Asia/Kolkata', label: 'India (IST)' },
]

/**
 * Settings: response tone, daily digest time, agent name, and a voice toggle.
 * Every value is loaded from and persisted to the backend (user_settings).
 */
export function SettingsPanel() {
  const [tone, setTone] = useState<Tone>('concise')
  const [digestTime, setDigestTime] = useState('08:00')
  const [timezone, setTimezone] = useState('America/New_York')
  const [agentName, setAgentName] = useState('Meridian')
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    api
      .getSettings()
      .then((settings) => {
        if (!active) return
        if (settings.response_tone) setTone(settings.response_tone as Tone)
        if (settings.digest_schedule) setDigestTime(settings.digest_schedule)
        if (settings.timezone) setTimezone(settings.timezone)
        if (settings.agent_name) setAgentName(settings.agent_name)
        if (settings.voice_enabled) setVoiceEnabled(settings.voice_enabled === 'true')
      })
      .catch(() => {
        // Keep defaults on failure — the panel stays usable.
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

  if (loading) {
    return <p className="py-10 text-center text-sm text-white/40">Loading settings…</p>
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Response tone */}
      <div className="flex flex-col gap-2">
        <span className="text-sm text-white/70">Response tone</span>
        <div className="grid grid-cols-3 gap-1 rounded-xl border border-white/10 bg-white/5 p-1">
          {TONES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                setTone(option.value)
                persist('response_tone', option.value)
              }}
              className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${
                tone === option.value
                  ? 'bg-white/15 text-white'
                  : 'text-white/50 hover:text-white/80'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {/* Daily digest time */}
      <label className="flex flex-col gap-2">
        <span className="text-sm text-white/70">Daily digest time</span>
        <select
          value={digestTime}
          onChange={(event) => {
            setDigestTime(event.target.value)
            persist('digest_schedule', event.target.value)
          }}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
        >
          {DIGEST_TIMES.map((time) => (
            <option key={time} value={time} className="bg-[#0d0d0f]">
              {time}
            </option>
          ))}
        </select>
      </label>

      {/* Timezone */}
      <label className="flex flex-col gap-2">
        <span className="text-sm text-white/70">Timezone</span>
        <select
          value={timezone}
          onChange={(event) => {
            setTimezone(event.target.value)
            persist('timezone', event.target.value)
          }}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
        >
          {TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value} className="bg-[#0d0d0f]">
              {tz.label}
            </option>
          ))}
        </select>
      </label>

      {/* Agent name */}
      <label className="flex flex-col gap-2">
        <span className="text-sm text-white/70">Agent name</span>
        <input
          value={agentName}
          onChange={(event) => setAgentName(event.target.value)}
          onBlur={() => persist('agent_name', agentName)}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
        />
      </label>

      {/* Voice responses */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">Voice responses</span>
        <button
          type="button"
          role="switch"
          aria-checked={voiceEnabled}
          onClick={() => {
            const next = !voiceEnabled
            setVoiceEnabled(next)
            persist('voice_enabled', String(next))
          }}
          className={`relative h-6 w-11 rounded-full transition-colors ${
            voiceEnabled ? 'bg-green-500' : 'bg-white/20'
          }`}
        >
          <span
            className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              voiceEnabled ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* AI providers */}
      <div className="border-t border-white/[0.06] pt-5">
        <AIProvidersSection />
      </div>
    </div>
  )
}

export default SettingsPanel
