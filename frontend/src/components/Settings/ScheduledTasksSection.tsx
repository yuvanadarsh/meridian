import { useEffect, useState } from 'react'

import { api } from '../../api/client'
import type { ScheduledTask } from '../../api/client'
import { Toggle } from './Toggle'

// The four fixed tasks, in display order. No add/delete in this UI — these map
// 1:1 to the registry in backend/services/tasks. `email_poll` runs on an
// interval (minutes); the rest run at a daily clock time.
const FIXED_TASKS: { key: string; label: string }[] = [
  { key: 'morning_brief', label: 'Morning Brief' },
  { key: 'email_poll', label: 'Email Sync' },
  { key: 'afternoon_review', label: 'Afternoon Review' },
  { key: 'calendar_sync', label: 'Calendar Sync' },
]

const isInterval = (task: ScheduledTask) => task.task_key === 'email_poll'

// An interval schedule stored as "*/15" (or "15") renders as a bare "15" so the
// field shows just the minute count.
function intervalMinutes(scheduleTime: string): string {
  const digits = scheduleTime.replace(/\D/g, '')
  return digits || '15'
}

function formatRelative(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return new Date(iso).toLocaleDateString()
}

function scheduleDescription(task: ScheduledTask): string {
  const base = isInterval(task)
    ? `Runs every ${intervalMinutes(task.schedule_time)} min`
    : `Runs daily at ${task.schedule_time}`
  return task.last_run_at ? `${base} · last run: ${formatRelative(task.last_run_at)}` : base
}

function TaskRow({
  task,
  onUpdate,
}: {
  task: ScheduledTask
  onUpdate: (id: number, patch: { schedule_time?: string; enabled?: boolean }) => void
}) {
  // The schedule as shown in the field: a bare minute count for interval tasks,
  // or the raw clock time otherwise.
  const displayed = isInterval(task) ? intervalMinutes(task.schedule_time) : task.schedule_time
  // Local copy of the editable schedule so typing doesn't fight the saved value.
  const [value, setValue] = useState(displayed)

  useEffect(() => {
    setValue(displayed)
  }, [displayed])

  return (
    <div className="flex items-center justify-between gap-4 border-t border-white/5 py-3 first:border-0">
      <div className="min-w-0">
        <div className="text-sm text-white/80">{FIXED_TASKS.find((t) => t.key === task.task_key)?.label ?? task.display_name ?? task.task_key}</div>
        <div className="mt-0.5 text-xs text-white/40">
          {scheduleDescription(task)}
          {task.last_run_status === 'error' && <span className="ml-1 text-red-400">· failed</span>}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={() => {
            const next = value.trim()
            if (next && next !== displayed) onUpdate(task.id, { schedule_time: next })
          }}
          aria-label={isInterval(task) ? 'Interval in minutes' : 'Daily run time'}
          className="w-20 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-center text-xs text-white/70 focus:border-white/20 focus:outline-none"
        />
        <Toggle
          checked={task.enabled}
          label={`Enable ${task.task_key}`}
          onChange={(enabled) => onUpdate(task.id, { enabled })}
        />
      </div>
    </div>
  )
}

/**
 * Scheduled Tasks: the four fixed background tasks, each with an enable toggle
 * and an editable schedule (a clock time, or the poll interval in minutes).
 * Changes persist via PATCH /tasks/{id}. There is no add or delete here.
 */
export function ScheduledTasksSection() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .getTasks()
      .then(({ tasks: list }) => {
        if (active) setTasks(list)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : 'Could not load tasks')
      })
    return () => {
      active = false
    }
  }, [])

  const update = async (
    id: number,
    patch: { schedule_time?: string; enabled?: boolean },
  ) => {
    try {
      const updated = await api.updateTask(id, patch)
      setTasks((current) => current.map((t) => (t.id === updated.id ? updated : t)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update task')
    }
  }

  // Render in the fixed order, including only tasks that exist in the backend.
  const ordered = FIXED_TASKS.map(({ key }) => tasks.find((t) => t.task_key === key)).filter(
    (task): task is ScheduledTask => Boolean(task),
  )

  return (
    <div className="flex flex-col">
      {error && <p className="mb-2 text-xs text-rose-300/80">{error}</p>}
      {ordered.length === 0 ? (
        <p className="text-sm text-white/30">No scheduled tasks configured.</p>
      ) : (
        ordered.map((task) => <TaskRow key={task.id} task={task} onUpdate={update} />)
      )}
    </div>
  )
}

export default ScheduledTasksSection
