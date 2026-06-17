import { useState } from 'react'
import type { KeyboardEvent } from 'react'

interface ChatInputProps {
  /** Called with the trimmed text when the user submits a non-empty message. */
  onSubmit: (text: string) => void
  /** Disables input while a response is in flight. */
  disabled?: boolean
}

/**
 * The pill-shaped, glassmorphic prompt below the orb. Enter submits;
 * Shift+Enter inserts a newline.
 */
export function ChatInput({ onSubmit, disabled = false }: ChatInputProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    const text = value.trim()
    if (!text || disabled) return
    onSubmit(text)
    setValue('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="w-[600px] max-w-[90vw]">
      <div className="flex items-end rounded-[28px] border border-white/10 bg-white/5 px-5 py-3 backdrop-blur transition-colors focus-within:border-white/20">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder="Talk to Meridian"
          disabled={disabled}
          aria-label="Message Meridian"
          className="max-h-32 flex-1 resize-none bg-transparent text-sm leading-6 text-white placeholder:text-white/30 focus:outline-none disabled:opacity-50"
        />
      </div>
    </div>
  )
}

export default ChatInput
