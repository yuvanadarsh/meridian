/**
 * Shared text-to-speech playback. Sends text to the backend ElevenLabs proxy,
 * plays the returned audio, and drives the orb's `speaking` → `idle` state so
 * every caller (voice replies, the daily brief) animates consistently.
 */
import { api } from './client'
import { useMeridianStore } from '../store/meridianStore'

export async function speak(text: string): Promise<void> {
  const setOrbState = useMeridianStore.getState().setOrbState
  try {
    const response = await fetch(`${api.baseUrl}/voice/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!response.ok) {
      throw new Error('TTS request failed')
    }
    const blob = await response.blob()
    const audio = new Audio(URL.createObjectURL(blob))
    setOrbState('speaking')
    audio.onended = () => {
      setOrbState('idle')
      URL.revokeObjectURL(audio.src)
    }
    await audio.play()
  } catch {
    // Voice is best-effort; callers still show the text.
    setOrbState('idle')
  }
}
