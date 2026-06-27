import { PageLayout } from '../components/Layout/PageLayout'
import { DailyReviewPanel } from '../components/Menu/DailyReviewPanel'

/** Full-page Daily Review — renders the existing DailyReviewPanel as content. */
export function ReviewPage() {
  return (
    <PageLayout title="Review" subtitle="The afternoon email review, awaiting your approval">
      <DailyReviewPanel />
    </PageLayout>
  )
}

export default ReviewPage
