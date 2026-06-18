import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BsMicFill, BsMicMuteFill } from 'react-icons/bs'
import { IoArrowUp, IoClose } from 'react-icons/io5'

import type { ChatMessage } from '../../store/meridianStore'
import ChatHistory from './ChatHistory'

interface ChatModalProps {
  open: boolean
  onClose: () => void
  messages: ChatMessage[]
  onSend: (text: string) => void
  sending: boolean
  /** Whether speech recognition is available (Chrome) — hides the mic if not. */
  voiceSupported: boolean
  recording: boolean
  onToggleMic: () => void
}

// Textarea growth bounds: one row minimum, six rows maximum before scrolling.
const LINE_HEIGHT = 24
const MAX_ROWS = 6

/**
 * Full-screen chat overlay. The orb stays visible (blurred) behind a dimmed,
 * blurred backdrop. The panel holds the scrollable markdown history and a
 * textarea that grows with its content. Enter sends; Shift+Enter inserts a
 * newline; clicking the backdrop closes.
 */
export function ChatModal({
  open,
  onClose,
  messages,
  onSend,
  sending,
  voiceSupported,
  recording,
  onToggleMic,
}: ChatModalProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Autofocus the input shortly after the open animation begins.
  useEffect(() => {
    if (!open) return
    const id = window.setTimeout(() => textareaRef.current?.focus(), 60)
    return () => window.clearTimeout(id)
  }, [open])

  // Close on Escape.
  useEffect(() => {
    if (!open) return
    const handler = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const resize = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS * LINE_HEIGHT)}px`
  }

  const submit = () => {
    const text = value.trim()
    if (!text || sending) return
    onSend(text)
    setValue('')
    requestAnimationFrame(() => {
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
    })
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={onClose}
        >
          <motion.div
            className="flex max-h-[80vh] w-[720px] max-w-full flex-col overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0a0a0a]/85 shadow-2xl"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            // Clicks inside the panel must not bubble up to the backdrop.
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3">
              <span className="text-sm font-medium text-white/70">Meridian</span>
              <button
                type="button"
                aria-label="Close chat"
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-full text-white/50 transition-colors hover:bg-white/10 hover:text-white"
              >
                <IoClose size={20} />
              </button>
            </div>

            <ChatHistory messages={messages} />

            <div className="border-t border-white/[0.06] p-3">
              <div className="flex items-end gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-2.5 transition-colors focus-within:border-white/20">
                <textarea
                  ref={textareaRef}
                  value={value}
                  onChange={(event) => {
                    setValue(event.target.value)
                    resize()
                  }}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Talk to Meridian"
                  disabled={sending}
                  aria-label="Message Meridian"
                  className="flex-1 resize-none bg-transparent text-sm leading-6 text-white placeholder:text-white/30 focus:outline-none disabled:opacity-50"
                />
                {voiceSupported && (
                  <button
                    type="button"
                    onClick={onToggleMic}
                    aria-label={recording ? 'Stop recording' : 'Start recording'}
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors ${
                      recording
                        ? 'bg-white/15 text-white'
                        : 'text-white/40 hover:bg-white/10 hover:text-white/80'
                    }`}
                  >
                    {recording ? <BsMicFill size={16} /> : <BsMicMuteFill size={16} />}
                  </button>
                )}
                <button
                  type="button"
                  onClick={submit}
                  disabled={!value.trim() || sending}
                  aria-label="Send message"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 disabled:opacity-30"
                >
                  <IoArrowUp size={16} />
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default ChatModal
