import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type { CalendarEvent } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'

/** Local YYYY-MM-DD key for a Date (used to bucket events by day). */
function dayKey(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** Monday of the week containing the given date. */
function startOfWeek(date: Date): Date {
  const result = new Date(date)
  const day = (result.getDay() + 6) % 7 // Monday = 0
  result.setDate(result.getDate() - day)
  result.setHours(0, 0, 0, 0)
  return result
}

function addDays(date: Date, days: number): Date {
  const result = new Date(date)
  result.setDate(result.getDate() + days)
  return result
}

/** Format an offset-aware ISO time as "9:00 AM"; empty when missing. */
function formatTime(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** A Google Calendar link for an event — its Meet link, else the calendar home. */
function eventLink(event: CalendarEvent): string {
  return event.meet_link || 'https://calendar.google.com'
}

/**
 * Read-only weekly calendar view. Displays synced events from calendar_events
 * (converted to the user's timezone by the backend) in a 7-column grid, with
 * week navigation. Each event links out to Google Calendar.
 */
export function CalendarPage() {
  const [weekStart, setWeekStart] = useState<Date>(() => startOfWeek(new Date()))
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )

  useEffect(() => {
    let cancelled = false
    const rangeStart = dayKey(weekStart)
    const rangeEnd = dayKey(addDays(weekStart, 7))
    api
      .getCalendarRange(rangeStart, rangeEnd)
      .then(({ events: list }) => {
        if (!cancelled) {
          setEvents(list)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load calendar')
      })
    return () => {
      cancelled = true
    }
  }, [weekStart])

  const eventsForDay = (date: Date) => {
    const key = dayKey(date)
    return events.filter((event) => event.day === key)
  }

  const weekEnd = addDays(weekStart, 6)
  const sameMonth = weekStart.getMonth() === weekEnd.getMonth()
  const rangeLabel = sameMonth
    ? `${weekStart.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })} – ${weekEnd.toLocaleDateString(undefined, { day: 'numeric', year: 'numeric' })}`
    : `${weekStart.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${weekEnd.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`

  const todayKey = dayKey(new Date())

  return (
    <PageLayout
      title="Calendar"
      subtitle={rangeLabel}
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setWeekStart((prev) => addDays(prev, -7))}
            className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/70 transition-colors hover:bg-white/5 hover:text-white"
          >
            ← Prev
          </button>
          <button
            type="button"
            onClick={() => setWeekStart(startOfWeek(new Date()))}
            className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/70 transition-colors hover:bg-white/5 hover:text-white"
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => setWeekStart((prev) => addDays(prev, 7))}
            className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/70 transition-colors hover:bg-white/5 hover:text-white"
          >
            Next →
          </button>
        </div>
      }
    >
      {error && <p className="mb-4 text-sm text-rose-300/80">{error}</p>}

      <div className="grid grid-cols-7 gap-2">
        {weekDays.map((day) => {
          const isToday = dayKey(day) === todayKey
          const dayEvents = eventsForDay(day)
          return (
            <div key={day.toISOString()} className="min-h-[420px]">
              <div
                className={`mb-2 text-center text-xs ${isToday ? 'font-semibold text-white' : 'text-white/40'}`}
              >
                {day.toLocaleDateString(undefined, { weekday: 'short' })}{' '}
                <span className={isToday ? 'text-white' : 'text-white/60'}>{day.getDate()}</span>
              </div>
              <div className="space-y-1">
                {dayEvents.length === 0 ? (
                  <div className="rounded-lg border border-white/[0.04] py-2 text-center text-[10px] text-white/20">
                    —
                  </div>
                ) : (
                  dayEvents.map((event) => (
                    <a
                      key={event.id}
                      href={eventLink(event)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded-lg border border-white/10 bg-white/[0.08] p-2 transition-colors hover:bg-white/[0.12]"
                    >
                      <div className="truncate text-xs font-medium text-white">
                        {event.title || '(untitled)'}
                      </div>
                      <div className="mt-0.5 text-[10px] text-white/50">
                        {formatTime(event.start_time)}
                        {event.end_time ? ` – ${formatTime(event.end_time)}` : ''}
                      </div>
                    </a>
                  ))
                )}
              </div>
            </div>
          )
        })}
      </div>
    </PageLayout>
  )
}

export default CalendarPage
