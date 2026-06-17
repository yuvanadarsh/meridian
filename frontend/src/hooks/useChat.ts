import { useState } from 'react'

import { api } from '../api/client'
import { useMeridianStore } from '../store/meridianStore'

/**
 * Drives a chat turn: appends the user message, animates the orb to `thinking`,
 * calls Claude, appends the reply, and refreshes today's token count. Returns
 * the reply text (or null on failure) so callers like voice can speak it.
 */
export function useChat() {
  const addMessage = useMeridianStore((state) => state.addMessage)
  const setOrbState = useMeridianStore((state) => state.setOrbState)
  const setTokensToday = useMeridianStore((state) => state.setTokensToday)
  const [sending, setSending] = useState(false)

  const send = async (input: string): Promise<string | null> => {
    const text = input.trim()
    if (!text || sending) {
      return null
    }

    addMessage({ role: 'user', content: text, timestamp: new Date() })
    setOrbState('thinking')
    setSending(true)

    try {
      const result = await api.sendMessage(text)
      addMessage({ role: 'assistant', content: result.response, timestamp: new Date() })
      try {
        const tokens = await api.getTokensToday()
        setTokensToday(tokens.total)
      } catch {
        // Non-fatal — the polling token counter will catch up.
      }
      return result.response
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Something went wrong'
      addMessage({
        role: 'assistant',
        content: `Sorry — I couldn't reach Meridian. (${message})`,
        timestamp: new Date(),
      })
      return null
    } finally {
      setOrbState('idle')
      setSending(false)
    }
  }

  return { send, sending }
}
