import { useEffect, useState } from 'react'
import { FiPlus, FiTrash2 } from 'react-icons/fi'

import { api } from '../../api/client'
import type { AvailableTask, ScheduledTask } from '../../api/client'

const DAYS = ['daily', 'weekdays', 'weekends'] as const

function relativeRun(task: ScheduledTask): string {
  if (!task.last_run_at) return 'never'
  const then = new Date(task.last_run_at)
  const mins = Math.round((Date.now() - then.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return then.toLocaleDateString()
}

function scheduleLabel(task: ScheduledTask): string {
  if (task.task_key === 'email_poll') return 'every 15 min'
  return `${task.schedule_time} ${task.schedule_days}`
}

/**
 * Scheduled Tasks settings: list every scheduled task with its cadence and last
 * run, toggle it on/off, remove it, or add a new one from a registered type.
 */
export function ScheduledTasksSection() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [available, setAvailable] = useState<AvailableTask[]>([])
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Add-form state.
  const [newKey, setNewKey] = useState('')
  const [newTime, setNewTime] = useState('17:00')
  const [newDays, setNewDays] = useState<string>('daily')
  const [newName, setNewName] = useState('')

  const load = async () => {
    try {
      const [{ tasks: list }, { tasks: types }] = await Promise.all([
        api.getTasks(),
        api.getAvailableTasks(),
      ])
      setTasks(list)
      setAvailable(types)
      if (types.length && !newKey) setNewKey(types[0].key)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load tasks')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = async (task: ScheduledTask) => {
    try {
      const updated = await api.updateTask(task.id, { enabled: !task.enabled })
      setTasks((current) => current.map((t) => (t.id === updated.id ? updated : t)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update task')
    }
  }

  const remove = async (id: number) => {
    try {
      await api.deleteTask(id)
      setTasks((current) => current.filter((t) => t.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete task')
    }
  }

  const create = async () => {
    if (!newKey) return
    try {
      const task = await api.createTask({
        task_key: newKey,
        display_name: newName.trim() || undefined,
        schedule_time: newTime,
        schedule_days: newDays,
      })
      setTasks((current) => [...current, task])
      setAdding(false)
      setNewName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create task')
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm text-white/70">Scheduled Tasks</span>
      {error && <p className="text-xs text-rose-300/80">{error}</p>}

      <div className="flex flex-col gap-2">
        {tasks.map((task) => (
          <div
            key={task.id}
            className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm text-white">
                {task.display_name || task.task_key}
              </p>
              <p className="text-xs text-white/40">
                {scheduleLabel(task)} · last run: {relativeRun(task)}
                {task.last_run_status === 'error' && (
                  <span className="text-rose-300/80"> · failed</span>
                )}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                role="switch"
                aria-checked={task.enabled}
                onClick={() => void toggle(task)}
                className={`relative h-5 w-9 rounded-full transition-colors ${
                  task.enabled ? 'bg-green-500/60' : 'bg-white/15'
                }`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    task.enabled ? 'translate-x-4' : 'translate-x-0.5'
                  }`}
                />
              </button>
              <button
                type="button"
                aria-label="Remove task"
                onClick={() => void remove(task.id)}
                className="text-white/40 transition-colors hover:text-rose-300"
              >
                <FiTrash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {adding ? (
        <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-white/5 p-3">
          <label className="flex items-center gap-2 text-xs text-white/60">
            <span className="w-20 shrink-0">Task type</span>
            <select
              value={newKey}
              onChange={(event) => setNewKey(event.target.value)}
              className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white focus:border-white/30 focus:outline-none"
            >
              {available.map((type) => (
                <option key={type.key} value={type.key} className="bg-[#0d0d0f]">
                  {type.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-white/60">
            <span className="w-20 shrink-0">Time</span>
            <input
              type="time"
              value={newTime}
              onChange={(event) => setNewTime(event.target.value)}
              className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white focus:border-white/30 focus:outline-none"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-white/60">
            <span className="w-20 shrink-0">Days</span>
            <select
              value={newDays}
              onChange={(event) => setNewDays(event.target.value)}
              className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white focus:border-white/30 focus:outline-none"
            >
              {DAYS.map((day) => (
                <option key={day} value={day} className="bg-[#0d0d0f]">
                  {day}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-white/60">
            <span className="w-20 shrink-0">Name</span>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="Optional"
              className="flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void create()}
              className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition-opacity hover:opacity-90"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="rounded-full px-3 py-1 text-xs text-white/50 hover:text-white"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-white/15 px-3 py-2 text-xs text-white/50 transition-colors hover:border-white/30 hover:text-white/80"
        >
          <FiPlus size={14} /> Add task
        </button>
      )}
    </div>
  )
}

export default ScheduledTasksSection
