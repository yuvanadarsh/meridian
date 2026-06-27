import DailyBrief from '../components/Brief/DailyBrief'
import { PageLayout } from '../components/Layout/PageLayout'

/** Full-page Daily Brief — renders the existing DailyBrief as page content. */
export function BriefPage() {
  return (
    <PageLayout title="Brief" subtitle="Today's calendar, email, news, and stocks">
      <DailyBrief />
    </PageLayout>
  )
}

export default BriefPage
