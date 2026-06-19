import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
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

// Tailwind strips default list/heading styles, so re-apply via component props.
const NEWS_MARKDOWN: Components = {
  p: (props) => <p className="my-1 first:mt-0 last:mb-0 leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold text-white/80" {...props} />,
  ul: (props) => <ul className="my-1 list-disc space-y-0.5 pl-4" {...props} />,
  ol: (props) => <ol className="my-1 list-decimal space-y-0.5 pl-4" {...props} />,
  h1: (props) => <h1 className="my-2 text-sm font-semibold text-white/80" {...props} />,
  h2: (props) => <h2 className="my-2 text-sm font-semibold text-white/80" {...props} />,
  h3: (props) => <h3 className="my-1.5 text-xs font-semibold text-white/70" {...props} />,
  a: (props) => (
    <a className="underline underline-offset-2 hover:text-white/80" target="_blank" rel="noreferrer" {...props} />
  ),
}

const TODAY_LABEL = new Date().toLocaleDateString('en-US', {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
})

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

/**
 * Daily brief: calendar, email, news, and stock watchlist for today.
 *
 * On open, calls GET /digest/today which returns the cached result instantly
 * when one exists (free, no API calls). The Refresh button calls
 * POST /digest/refresh to force a rebuild — spinner shows only on the button,
 * not on the whole panel, so existing content stays visible.
 */
export function DailyBrief() {
  const [digest, setDigest] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api
      .getDigest()
      .then((d) => { if (active) setDigest(d) })
      .catch((err: Error) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const handleRefresh = () => {
    setRefreshing(true)
    setError(null)
    api
      .refreshDigest()
      .then(setDigest)
      .catch((err: Error) => setError(err.message))
      .finally(() => setRefreshing(false))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-white/80">
            Today's Brief — {TODAY_LABEL}
          </h3>
          {digest?.cached && digest.updated_at && (
            <p className="mt-0.5 text-xs text-white/30">
              Last updated {timeAgo(digest.updated_at)}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={loading || refreshing}
          aria-label="Refresh brief"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white/50 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
        >
          <FiRefreshCw size={16} className={refreshing ? 'animate-spin' : undefined} />
        </button>
      </div>

      {loading && (
        <p className="py-6 text-center text-sm text-white/40">Gathering your brief…</p>
      )}

      {error && (
        <p className="py-6 text-center text-sm text-red-400/80">{error}</p>
      )}

      {digest && !loading && (
        <>
          <Section icon={FiCalendar} title="Calendar" body={digest.calendar} />
          <Section icon={FiMail} title="Email" body={digest.emails} />
          <Section icon={HiOutlineNewspaper} title="News" body={digest.news} markdown />
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
  markdown = false,
}: {
  icon: IconType
  title: string
  body: string
  markdown?: boolean
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-white/70">
        <Icon size={16} />
        <span className="text-sm font-medium">{title}</span>
      </div>
      {markdown ? (
        <div className="text-sm text-white/60">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={NEWS_MARKDOWN}>
            {body}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-white/60">
          {body}
        </p>
      )}
    </div>
  )
}

export default DailyBrief
