import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import {
  HiOutlineArrowLeft,
  HiOutlinePaperAirplane,
} from 'react-icons/hi2'
import { useNavigate, useParams } from 'react-router-dom'
import remarkGfm from 'remark-gfm'

import { api } from '../api/client'
import type { PersistentChatMessage } from '../api/client'

// Assistant markdown styling (mirrors the daily chat's renderer).
const MARKDOWN_COMPONENTS: Components = {
  p: (props) => <p className="my-1.5 first:mt-0 last:mb-0 leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold text-white" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  ul: (props) => <ul className="my-1.5 list-disc space-y-0.5 pl-5" {...props} />,
  ol: (props) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5" {...props} />,
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
 * Full conversation view for one persistent chat. Message history with an
 * editable title at the top and a composer at the bottom. Each send hits the
 * backend, which appends the exchange to the Obsidian note and (on the first
 * message) auto-generates the title.
 */
export function ChatDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [title, setTitle] = useState<string | null>(null)
  const [messages, setMessages] = useState<PersistentChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Load the conversation on mount / id change.
  useEffect(() => {
    if (!id) return
    let cancelled = false
    api
      .getPersistentChat(id)
      .then((data) => {
        if (cancelled) return
        setTitle(data.title)
        setMessages(data.messages)
      })
      .catch(() => {
        // A missing chat falls back to the list.
        if (!cancelled) navigate('/chat')
      })
    return () => {
      cancelled = true
    }
  }, [id, navigate])

  // Auto-scroll to the newest message.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async () => {
    const userMsg = input.trim()
    if (!userMsg || loading || !id) return
    setInput('')
    setLoading(true)
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }])

    try {
      const response = await api.sendPersistentChatMessage(id, userMsg)
      setMessages((prev) => [...prev, { role: 'assistant', content: response.content }])
      if (response.title) setTitle(response.title)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: err instanceof Error ? `Error: ${err.message}` : 'Something went wrong.',
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const renameChat = async (newTitle: string) => {
    const trimmed = newTitle.trim()
    setEditingTitle(false)
    if (!trimmed || !id || trimmed === title) return
    try {
      await api.renamePersistentChat(id, trimmed)
      setTitle(trimmed)
    } catch {
      // Keep the old title on failure.
    }
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header with editable title */}
      <div className="flex items-center gap-3 border-b border-white/5 px-8 py-4">
        <button
          type="button"
          aria-label="Back to chats"
          onClick={() => navigate('/chat')}
          className="text-white/40 transition-colors hover:text-white"
        >
          <HiOutlineArrowLeft className="h-5 w-5" />
        </button>
        {editingTitle ? (
          <input
            autoFocus
            defaultValue={title ?? ''}
            onBlur={(event) => void renameChat(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void renameChat(event.currentTarget.value)
              if (event.key === 'Escape') setEditingTitle(false)
            }}
            className="border-b border-white/20 bg-transparent text-lg font-semibold text-white outline-none"
            aria-label="Chat title"
          />
        ) : (
          <h1
            onClick={() => setEditingTitle(true)}
            className="cursor-pointer text-lg font-semibold text-white transition-colors hover:text-white/80"
            title="Click to rename"
          >
            {title || 'Untitled conversation'}
          </h1>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-6 overflow-y-auto px-8 py-6">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm ${
                message.role === 'user'
                  ? 'bg-white/10 text-white'
                  : 'bg-transparent text-white/80'
              }`}
            >
              {message.role === 'assistant' ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                  {message.content}
                </ReactMarkdown>
              ) : (
                message.content
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="animate-pulse text-sm text-white/40">Thinking…</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <div className="border-t border-white/5 px-8 py-4">
        <div className="flex items-end gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void sendMessage()
              }
            }}
            placeholder="Message this conversation..."
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm text-white outline-none placeholder:text-white/30"
          />
          <button
            type="button"
            aria-label="Send message"
            onClick={() => void sendMessage()}
            disabled={!input.trim() || loading}
            className="text-white/40 transition-colors hover:text-white disabled:opacity-30"
          >
            <HiOutlinePaperAirplane className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default ChatDetailPage
