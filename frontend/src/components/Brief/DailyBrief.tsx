import { useEffect, useState } from 'react'
import {
  FiCalendar,
  FiMail,
  FiRefreshCw,
  FiTrendingUp,
  FiVolume2,
} from 'react-icons/fi'
import { HiOutlineNewspaper } from 'react-icons/hi2'
import type { IconType } from 'react-icons'

import { api, type Digest } from '../../api/client'
import { speak } from '../../api/speak'

const TODAY_LABEL = new Date().toLocaleDateString('en-US', {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
})

/**
 * Daily brief: calendar, email, news, and stock watchlist for today. Fetches
 * the assembled digest from the backend, with Refresh and Read-aloud controls.
 */
export function DailyBrief() {
  const [digest, setDigest] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .getDigest()
      .then(setDigest)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white/80">
          Today's Brief — {TODAY_LABEL}
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          aria-label="Refresh brief"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white/50 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
        >
          <FiRefreshCw size={16} className={loading ? 'animate-spin' : undefined} />
        </button>
      </div>

      {loading && (
        <p className="py-6 text-center text-sm text-white/40">Gathering your brief…</p>
      )}

      {error && !loading && (
        <p className="py-6 text-center text-sm text-red-400/80">{error}</p>
      )}

      {digest && !loading && (
        <>
          <Section icon={FiCalendar} title="Calendar" body={digest.calendar} />
          <Section icon={FiMail} title="Email" body={digest.emails} />
          <Section icon={HiOutlineNewspaper} title="News" body={digest.news} />
          <Section icon={FiTrendingUp} title="Stocks" body={digest.stocks} />

          <button
            type="button"
            onClick={() => void speak(digest.full_text)}
            className="mt-1 flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white/80 transition-colors hover:bg-white/10 hover:text-white"
          >
            <FiVolume2 size={16} /> Read brief aloud
          </button>
        </>
      )}
    </div>
  )
}

function Section({
  icon: Icon,
  title,
  body,
}: {
  icon: IconType
  title: string
  body: string
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-white/70">
        <Icon size={16} />
        <span className="text-sm font-medium">{title}</span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-white/60">
        {body}
      </p>
    </div>
  )
}

export default DailyBrief
