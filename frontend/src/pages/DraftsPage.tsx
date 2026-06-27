import { PageLayout } from '../components/Layout/PageLayout'
import { DraftsPanel } from '../components/Menu/DraftsPanel'

/** Full-page Drafts view — renders the existing DraftsPanel as page content. */
export function DraftsPage() {
  return (
    <PageLayout title="Drafts" subtitle="Replies Meridian drafted in your voice">
      <DraftsPanel />
    </PageLayout>
  )
}

export default DraftsPage
