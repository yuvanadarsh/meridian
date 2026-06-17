import { useState } from 'react'

/**
 * Settings placeholder for Phase 1: agent name and a voice-responses toggle.
 * Values are local for now; persistence arrives in a later phase.
 */
export function SettingsPanel() {
  const [agentName, setAgentName] = useState('Meridian')
  const [voiceEnabled, setVoiceEnabled] = useState(true)

  return (
    <div className="flex flex-col gap-5">
      <label className="flex flex-col gap-2">
        <span className="text-sm text-white/70">Agent name</span>
        <input
          value={agentName}
          onChange={(event) => setAgentName(event.target.value)}
          className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white focus:border-white/20 focus:outline-none"
        />
      </label>

      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">Voice responses</span>
        <button
          type="button"
          role="switch"
          aria-checked={voiceEnabled}
          onClick={() => setVoiceEnabled((value) => !value)}
          className={`relative h-6 w-11 rounded-full transition-colors ${
            voiceEnabled ? 'bg-emerald-400/70' : 'bg-white/15'
          }`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              voiceEnabled ? 'translate-x-[22px]' : 'translate-x-0.5'
            }`}
          />
        </button>
      </div>

      <p className="text-xs text-white/30">
        Settings are stored locally for now; persistence arrives in a later phase.
      </p>
    </div>
  )
}

export default SettingsPanel
