import { PageLayout } from '../components/Layout/PageLayout'

/** Placeholder — persistent, listable conversations arrive in Session 2. */
export function ChatPage() {
  return (
    <PageLayout title="Chat" subtitle="Persistent conversations">
      <div className="text-sm text-white/30">Persistent chat coming in Session 2</div>
    </PageLayout>
  )
}

export default ChatPage
