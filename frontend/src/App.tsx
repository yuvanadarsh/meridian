import { useEffect } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'

import { api } from './api/client'
import Onboarding from './components/Onboarding/Onboarding'
import { Sidebar } from './components/Sidebar/Sidebar'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { BriefPage } from './pages/BriefPage'
import { CalendarPage } from './pages/CalendarPage'
import { ChatDetailPage } from './pages/ChatDetailPage'
import { ChatPage } from './pages/ChatPage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { ContactsPage } from './pages/ContactsPage'
import { DraftsPage } from './pages/DraftsPage'
import { HomePage } from './pages/HomePage'
import { ReviewPage } from './pages/ReviewPage'
import { SettingsPage } from './pages/SettingsPage'
import { useMeridianStore } from './store/meridianStore'

/**
 * App shell: the persistent sidebar on the left and the routed page content on
 * the right. Cross-route concerns live here — OAuth redirect handling, the
 * onboarding overlay, and one-time conversation history hydration — so they
 * survive navigation between pages.
 */
function App() {
  const navigate = useNavigate()
  const setMessages = useMeridianStore((state) => state.setMessages)
  const justConnectedEmail = useMeridianStore((state) => state.justConnectedEmail)
  const setJustConnectedEmail = useMeridianStore((state) => state.setJustConnectedEmail)
  const onboardingAccountId = useMeridianStore((state) => state.onboardingAccountId)
  const setOnboardingAccountId = useMeridianStore((state) => state.setOnboardingAccountId)
  const triageReviewAccountId = useMeridianStore((state) => state.triageReviewAccountId)
  const setTriageReviewAccountId = useMeridianStore((state) => state.setTriageReviewAccountId)

  // After Google OAuth, the backend redirects to /?connected=<email>. Capture
  // the email (handed off to the onboarding flow) and strip the query param so
  // a refresh doesn't reprocess it and the address bar stays clean.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const connected = params.get('connected')
    const reauthed = params.get('reauthed')
    if (connected) {
      setJustConnectedEmail(connected)
      window.history.replaceState({}, '', window.location.pathname)
    } else if (reauthed) {
      // Re-auth succeeded — send the user to Connections so they see the updated
      // status without having to navigate there manually.
      window.history.replaceState({}, '', window.location.pathname)
      navigate('/connections')
    }
  }, [setJustConnectedEmail, navigate])

  // Resolve the just-connected email to its account id, then drop into the
  // onboarding flow (sweep → triage → vectorize) for that account.
  useEffect(() => {
    if (!justConnectedEmail) return
    let cancelled = false
    api
      .getAccounts()
      .then((accounts) => {
        if (cancelled) return
        const match = accounts.find((account) => account.email === justConnectedEmail)
        if (match) setOnboardingAccountId(match.id)
        setJustConnectedEmail(null)
      })
      .catch(() => setJustConnectedEmail(null))
    return () => {
      cancelled = true
    }
  }, [justConnectedEmail, setOnboardingAccountId, setJustConnectedEmail])

  // Pre-load the recent conversation from the database so a refresh keeps the
  // thread intact. Best-effort: if the API is down the screen stays usable.
  useEffect(() => {
    let cancelled = false
    api
      .getMessages()
      .then((rows) => {
        if (cancelled) return
        setMessages(
          rows.map((row) => ({
            role: row.role,
            content: row.content,
            timestamp: row.created_at ? new Date(row.created_at) : new Date(),
          })),
        )
      })
      .catch(() => {
        // History is non-essential; ignore load failures.
      })
    return () => {
      cancelled = true
    }
  }, [setMessages])

  return (
    <div className="flex h-screen overflow-hidden bg-[#080808] text-white">
      <Sidebar />
      <main className="ml-[220px] flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:id" element={<ChatDetailPage />} />
          <Route path="/drafts" element={<DraftsPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/brief" element={<BriefPage />} />
          <Route path="/contacts" element={<ContactsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>

      {(onboardingAccountId !== null || triageReviewAccountId !== null) && (
        <Onboarding
          accountId={onboardingAccountId ?? triageReviewAccountId!}
          startAtReview={triageReviewAccountId !== null}
          onClose={() => {
            setOnboardingAccountId(null)
            setTriageReviewAccountId(null)
          }}
        />
      )}
    </div>
  )
}

export default App
