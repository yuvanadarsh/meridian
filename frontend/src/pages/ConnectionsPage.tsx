import { PageLayout } from '../components/Layout/PageLayout'
import { ConnectionsPanel } from '../components/Menu/ConnectionsPanel'

/** Full-page Connections — renders the existing ConnectionsPanel as content. */
export function ConnectionsPage() {
  return (
    <PageLayout title="Connections" subtitle="Your connected Google accounts">
      <ConnectionsPanel />
    </PageLayout>
  )
}

export default ConnectionsPage
