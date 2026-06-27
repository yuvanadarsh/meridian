import { useParams } from 'react-router-dom'

import { PageLayout } from '../components/Layout/PageLayout'

/** Placeholder — a single conversation thread view arrives in Session 2. */
export function ChatDetailPage() {
  const { id } = useParams()
  return (
    <PageLayout title={`Chat ${id ?? ''}`.trim()}>
      <div className="text-sm text-white/30">Chat detail coming in Session 2</div>
    </PageLayout>
  )
}

export default ChatDetailPage
