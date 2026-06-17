import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ChatMessage } from '../../store/meridianStore'

interface ChatHistoryProps {
  messages: ChatMessage[]
}

// Tailwind's preflight strips default list/heading styling, so assistant
// markdown is mapped to explicit utility classes here. Inline code gets a
// pill background; fenced blocks are styled on the <pre> wrapper instead.
const MARKDOWN_COMPONENTS: Components = {
  p: (props) => <p className="my-1.5 first:mt-0 last:mb-0 leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold text-white" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  ul: (props) => <ul className="my-1.5 list-disc space-y-0.5 pl-5" {...props} />,
  ol: (props) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5" {...props} />,
  h1: (props) => <h1 className="my-2 text-base font-semibold text-white" {...props} />,
  h2: (props) => <h2 className="my-2 text-sm font-semibold text-white" {...props} />,
  h3: (props) => <h3 className="my-1.5 text-sm font-semibold text-white" {...props} />,
  a: (props) => (
    <a
      className="underline underline-offset-2 hover:text-white"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  pre: (props) => (
    <pre
      className="my-2 overflow-x-auto rounded-lg bg-black/50 p-3 text-xs leading-relaxed"
      {...props}
    />
  ),
  code: ({ className, children, ...props }) => {
    // react-markdown tags fenced blocks with a `language-*` class; inline code
    // has none. Blocks inherit the <pre> background, so only inline code needs
    // its own pill.
    const isBlock = Boolean(className)
    return isBlock ? (
      <code className={`font-mono ${className ?? ''}`} {...props}>
        {children}
      </code>
    ) : (
      <code className="rounded bg-black/50 px-1 py-0.5 font-mono text-[0.85em]" {...props}>
        {children}
      </code>
    )
  },
}

/**
 * Scrollable conversation log shown inside the chat modal. Fills the available
 * height and auto-scrolls to the newest message. Assistant turns render through
 * react-markdown (bold, lists, code, etc.); user turns stay plain text.
 */
export function ChatHistory({ messages }: ChatHistoryProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-10 text-sm text-white/30">
        Ask Meridian anything.
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-4">
      {messages.map((message, index) => (
        <div
          key={index}
          className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
        >
          <div
            className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
              message.role === 'user'
                ? 'whitespace-pre-wrap bg-white/10 text-white'
                : 'bg-white/5 text-white/90'
            }`}
          >
            {message.role === 'user' ? (
              message.content
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                {message.content}
              </ReactMarkdown>
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}

export default ChatHistory
