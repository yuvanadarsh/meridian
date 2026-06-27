import { useEffect, useState } from 'react'
import { FiSearch } from 'react-icons/fi'
import { HiOutlineUsers } from 'react-icons/hi2'

import { api } from '../api/client'
import type { Contact } from '../api/client'
import { PageLayout } from '../components/Layout/PageLayout'

/** Format an ISO timestamp as a short "Jun 27, 2026", or em-dash when null. */
function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** One contact row. Clicking it expands an inline detail panel. */
function ContactCard({ contact }: { contact: Contact }) {
  const [open, setOpen] = useState(false)
  const name = contact.display_name || contact.email_address

  return (
    <button
      type="button"
      onClick={() => setOpen((prev) => !prev)}
      className="w-full rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-left transition-colors hover:bg-white/[0.06]"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-white">{name}</div>
          {contact.display_name && (
            <div className="truncate text-xs text-white/40">{contact.email_address}</div>
          )}
        </div>
        <span className="shrink-0 text-xs text-white/40">
          {contact.email_count} email{contact.email_count === 1 ? '' : 's'}
        </span>
      </div>

      {contact.topics && contact.topics.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {contact.topics.map((topic) => (
            <span
              key={topic}
              className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-white/40"
            >
              {topic}
            </span>
          ))}
        </div>
      )}

      {open && (
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 border-t border-white/[0.06] pt-3 text-xs text-white/50">
          <div>
            Sent: <span className="text-white/70">{contact.sent_count}</span>
          </div>
          <div>
            Received: <span className="text-white/70">{contact.received_count}</span>
          </div>
          <div>
            First: <span className="text-white/70">{formatDate(contact.first_contacted)}</span>
          </div>
          <div>
            Last: <span className="text-white/70">{formatDate(contact.last_contacted)}</span>
          </div>
        </div>
      )}
    </button>
  )
}

/**
 * Dedicated Contacts page — the full contact graph, searchable and sorted by
 * email volume (most contacted first). Previously lived inside the Connections
 * panel; now it has its own route.
 */
export function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [building, setBuilding] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const { contacts: list } = await api.getContacts(500)
      setContacts(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load contacts')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const rebuild = async () => {
    setBuilding(true)
    setError(null)
    try {
      const accounts = await api.getAccounts()
      if (accounts.length === 0) {
        setError('Connect an account first.')
        return
      }
      await Promise.all(accounts.map((account) => api.buildContactGraph(account.id)))
      // The build runs in the background; refresh once after a short delay.
      setTimeout(() => void load(), 4000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start contact build')
    } finally {
      setBuilding(false)
    }
  }

  const term = search.trim().toLowerCase()
  const filtered = term
    ? contacts.filter(
        (c) =>
          c.display_name?.toLowerCase().includes(term) ||
          c.email_address?.toLowerCase().includes(term),
      )
    : contacts

  return (
    <PageLayout
      title="Contacts"
      subtitle={`${contacts.length} contacts from your email history`}
      actions={
        <button
          type="button"
          disabled={building}
          onClick={() => void rebuild()}
          className="rounded-xl bg-white/10 px-4 py-2 text-sm text-white transition-colors hover:bg-white/15 disabled:opacity-40"
        >
          {building ? 'Rebuilding…' : 'Rebuild graph'}
        </button>
      }
    >
      <div className="mb-6 flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5">
        <FiSearch size={16} className="shrink-0 text-white/40" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search contacts..."
          aria-label="Search contacts"
          className="flex-1 bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
        />
      </div>

      {error && <p className="mb-4 text-sm text-rose-300/80">{error}</p>}

      {loading ? (
        <p className="text-sm text-white/30">Loading contacts…</p>
      ) : filtered.length === 0 ? (
        <div className="py-20 text-center text-white/30">
          <HiOutlineUsers className="mx-auto mb-4 h-12 w-12 opacity-30" />
          <p className="text-sm">
            {term ? 'No matching contacts.' : 'No contacts yet.'}
          </p>
          {!term && (
            <p className="mt-1 text-xs">Rebuild the graph to populate this from your email.</p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((contact) => (
            <ContactCard key={contact.email_address} contact={contact} />
          ))}
        </div>
      )}
    </PageLayout>
  )
}

export default ContactsPage
