import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import { useMeridianStore } from '../store/meridianStore'
import { useChat } from './useChat'

function getRecognitionCtor(): SpeechRecognitionConstructor | null {
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null
}

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable)
  )
}

/**
 * Push-to-talk voice. Hold space (or click the mic) to capture speech via the
 * Web Speech API, send it to Claude, then speak the reply via ElevenLabs.
 * Orb state flows: listening → thinking → speaking → idle.
 */
export function useVoice() {
  const { send } = useChat()
  const setOrbState = useMeridianStore((state) => state.setOrbState)
  const [recording, setRecording] = useState(false)
  const [supported] = useState(() => getRecognitionCtor() !== null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  const speak = useCallback(
    async (text: string) => {
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
        // Voice is best-effort; fall back to the (already shown) text reply.
        setOrbState('idle')
      }
    },
    [setOrbState],
  )

  const handleTranscript = useCallback(
    async (transcript: string) => {
      const reply = await send(transcript) // animates thinking → idle
      if (reply) {
        await speak(reply) // animates speaking → idle
      }
    },
    [send, speak],
  )

  const startRecording = useCallback(() => {
    const Recognition = getRecognitionCtor()
    if (!Recognition || recognitionRef.current) {
      return
    }
    const recognition = new Recognition()
    recognition.lang = 'en-US'
    recognition.continuous = false
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onresult = (event) => {
      const last = event.results[event.results.length - 1]
      const transcript = last[0].transcript.trim()
      if (transcript) {
        void handleTranscript(transcript)
      }
    }
    recognition.onerror = () => {
      setOrbState('idle')
    }
    recognition.onend = () => {
      recognitionRef.current = null
      setRecording(false)
    }

    recognitionRef.current = recognition
    recognition.start()
    setRecording(true)
    setOrbState('listening')
  }, [handleTranscript, setOrbState])

  const stopRecording = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const toggleRecording = useCallback(() => {
    if (recognitionRef.current) {
      stopRecording()
    } else {
      startRecording()
    }
  }, [startRecording, stopRecording])

  // Spacebar push-to-talk (ignored while typing in the prompt).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code === 'Space' && !event.repeat && !isTypingTarget(event.target)) {
        event.preventDefault()
        startRecording()
      }
    }
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space' && !isTypingTarget(event.target)) {
        event.preventDefault()
        stopRecording()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [startRecording, stopRecording])

  return { recording, supported, toggleRecording }
}
