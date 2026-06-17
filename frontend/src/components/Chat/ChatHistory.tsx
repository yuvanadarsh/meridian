import { useEffect, useRef } from 'react'

import type { ChatMessage } from '../../store/meridianStore'

interface ChatHistoryProps {
  messages: ChatMessage[]
}

/**
 * Scrollable conversation log shown above the input. Renders nothing until the
 * first message exists, keeping the idle screen focused on the orb.
 */
export function ChatHistory({ messages }: ChatHistoryProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return null
  }

  return (
    <div className="flex max-h-[40vh] w-[600px] max-w-[90vw] flex-col gap-3 overflow-y-auto px-1">
      {messages.map((message, index) => (
        <div
          key={index}
          className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
        >
          <div
            className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
              message.role === 'user'
                ? 'bg-white/10 text-white'
                : 'bg-white/5 text-white/90'
            }`}
          >
            {message.content}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}

export default ChatHistory
