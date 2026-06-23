import { useEffect, useState } from 'react'
import { HiOutlineCalendar, HiOutlineEnvelope, HiOutlineNewspaper } from 'react-icons/hi2'

import { api } from '../../api/client'

interface GlanceData {
  eventCount: number
  pendingCount: number
  briefReady: boolean
}

interface Props {
  onOpenBrief: () => void
  onOpenReview: () => void
}

/**
 * Single-row contextual strip that surfaces today's calendar count, pending
 * review emails, and digest status. All three items are clickable. Any fetch
 * failure silently hides that item rather than showing an error.
 */
export function GlanceStrip({ onOpenBrief, onOpenReview }: Props) {
  const [data, setData] = useState<GlanceData | null>(null)

  useEffect(() => {
    let active = true

    Promise.allSettled([
      api.getCalendarToday(),
      api.getReview(),
      api.getDigest(),
    ]).then(([calendarResult, reviewResult, digestResult]) => {
      if (!active) return

      const eventCount =
        calendarResult.status === 'fulfilled'
          ? (calendarResult.value.events?.length ?? 0)
          : 0

      let pendingCount = 0
      if (reviewResult.status === 'fulfilled' && reviewResult.value.review) {
        const review = reviewResult.value.review
        // Only show count when there's an unapproved pending review.
        if (review.status === 'pending') {
          pendingCount = review.emails.filter((e) => e.classification === 'keep').length
        }
      }

      const briefReady =
        digestResult.status === 'fulfilled' && !!digestResult.value?.calendar

      setData({ eventCount, pendingCount, briefReady })
    })

    return () => {
      active = false
    }
  }, [])

  if (!data) return null

  const dot = <span className="text-white/20">·</span>

  return (
    <div className="flex items-center justify-center gap-3 text-xs text-white/40">
      <button
        type="button"
        onClick={onOpenBrief}
        className="flex items-center gap-1 transition-colors hover:text-white/70"
      >
        <HiOutlineCalendar className="h-3 w-3" />
        {data.eventCount === 0
          ? 'No events today'
          : `${data.eventCount} event${data.eventCount !== 1 ? 's' : ''} today`}
      </button>

      {dot}

      <button
        type="button"
        onClick={onOpenReview}
        className="flex items-center gap-1 transition-colors hover:text-white/70"
      >
        <HiOutlineEnvelope className="h-3 w-3" />
        {data.pendingCount === 0 ? 'Inbox clear' : `${data.pendingCount} need attention`}
      </button>

      {dot}

      <button
        type="button"
        onClick={onOpenBrief}
        className="flex items-center gap-1 transition-colors hover:text-white/70"
      >
        <HiOutlineNewspaper className="h-3 w-3" />
        {data.briefReady ? 'Brief ready' : 'No brief yet'}
      </button>
    </div>
  )
}

export default GlanceStrip
