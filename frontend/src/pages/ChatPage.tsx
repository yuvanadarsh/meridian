import { useEffect, useState } from 'react'
import { HiOutlineChatBubbleLeft, HiOutlineTrash } from 'react-icons/hi2'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { PersistentChatSummary } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'

/** "5 min ago" / "3 days ago" relative time for a chat's last update. */
function formatRelative(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days > 1 ? 's' : ''} ago`
}

/**
 * Persistent chat list — conversations that survive the daily reset. Each row
 * opens the full conversation at /chat/:id. New chats start empty and get an
 * auto-generated title after the first exchange.
 */
export function ChatPage() {
  const navigate = useNavigate()
  const [chats, setChats] = useState<PersistentChatSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      const { chats: list } = await api.listPersistentChats()
      setChats(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load chats')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const createChat = async () => {
    try {
      const chat = await api.createPersistentChat()
      navigate(`/chat/${chat.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create chat')
    }
  }

  const remove = async (event: React.MouseEvent, id: string) => {
    event.stopPropagation()
    if (!window.confirm('Delete this chat? The Obsidian note stays in your vault.')) return
    try {
      await api.deletePersistentChat(id)
      setChats((prev) => prev.filter((chat) => chat.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete chat')
    }
  }

  return (
    <PageLayout
      title="Chat"
      subtitle="Persistent conversations that never get wiped"
      actions={
        <button
          type="button"
          onClick={() => void createChat()}
          className="rounded-xl bg-white/10 px-4 py-2 text-sm text-white transition-colors hover:bg-white/15"
        >
          + New chat
        </button>
      }
    >
      {error && <p className="mb-4 text-sm text-rose-300/80">{error}</p>}

      {loading ? (
        <p className="text-sm text-white/30">Loading chats…</p>
      ) : chats.length === 0 ? (
        <div className="py-20 text-center text-white/30">
          <HiOutlineChatBubbleLeft className="mx-auto mb-4 h-12 w-12 opacity-30" />
          <p className="text-sm">No persistent chats yet.</p>
          <p className="mt-1 text-xs">Create one to start a conversation that stays.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {chats.map((chat) => (
            <div
              key={chat.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/chat/${chat.id}`)}
              onKeyDown={(event) => event.key === 'Enter' && navigate(`/chat/${chat.id}`)}
              className="group flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 transition-colors hover:bg-white/[0.06]"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-white">
                  {chat.title || 'Untitled conversation'}
                </div>
                <div className="mt-1 text-xs text-white/40">{formatRelative(chat.updated_at)}</div>
              </div>
              <button
                type="button"
                aria-label="Delete chat"
                onClick={(event) => void remove(event, chat.id)}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white/30 opacity-0 transition-all hover:bg-rose-400/10 hover:text-rose-300 group-hover:opacity-100"
              >
                <HiOutlineTrash size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </PageLayout>
  )
}

export default ChatPage
