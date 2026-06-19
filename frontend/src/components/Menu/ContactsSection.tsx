import { useEffect, useState } from 'react'
import { FiSearch } from 'react-icons/fi'
import { HiOutlineUsers } from 'react-icons/hi2'

import { api } from '../../api/client'
import type { Contact, GmailAccount } from '../../api/client'

/**
 * Contact intelligence section for the Connections panel: total contacts,
 * a search box, the most-contacted people, and a "Build contact graph" action
 * that aggregates the contact graph from the first account's email history.
 */
export function ContactsSection({ accounts }: { accounts: GmailAccount[] }) {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Contact[] | null>(null)
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      const { contacts: list } = await api.getContacts()
      setContacts(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load contacts')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  // Debounced contact search; empty query clears results and shows the top list.
  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setResults(null)
      return
    }
    const handle = setTimeout(async () => {
      try {
        const { contacts: found } = await api.searchContacts(trimmed)
        setResults(found)
      } catch {
        setResults([])
      }
    }, 250)
    return () => clearTimeout(handle)
  }, [query])

  const build = async () => {
    if (accounts.length === 0) {
      setError('Connect an account first.')
      return
    }
    setBuilding(true)
    setError(null)
    try {
      // Build the contact graph for every connected account.
      await Promise.all(accounts.map((account) => api.buildContactGraph(account.id)))
      // The build runs in the background; poll once after a short delay.
      setTimeout(() => void load(), 4000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start contact build')
    } finally {
      setBuilding(false)
    }
  }

  const shown = results ?? contacts.slice(0, 10)

  return (
    <div className="flex flex-col gap-3 border-t border-white/[0.06] pt-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HiOutlineUsers size={16} className="text-white/50" />
          <span className="text-sm font-medium text-white/70">Contacts</span>
          <span className="text-xs text-white/30">{contacts.length}</span>
        </div>
        <button
          type="button"
          disabled={building}
          onClick={() => void build()}
          className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
        >
          {building ? 'Building…' : 'Build contact graph'}
        </button>
      </div>

      {error && <p className="text-xs text-rose-300/80">{error}</p>}

      <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5">
        <FiSearch size={14} className="shrink-0 text-white/40" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search contacts"
          aria-label="Search contacts"
          className="flex-1 bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
        />
      </div>

      {shown.length === 0 ? (
        <p className="text-xs text-white/30">
          {query.trim()
            ? 'No matching contacts.'
            : 'No contacts yet — build the contact graph to populate this.'}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {shown.map((contact) => (
            <li
              key={contact.email_address}
              className="rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-white/80">
                  {contact.display_name || contact.email_address}
                </span>
                <span className="shrink-0 text-xs text-white/40">
                  {contact.email_count} emails
                </span>
              </div>
              {contact.display_name && (
                <div className="truncate text-xs text-white/30">{contact.email_address}</div>
              )}
              {contact.topics && contact.topics.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
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
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default ContactsSection
