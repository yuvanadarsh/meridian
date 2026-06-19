import { create } from 'zustand'

import type { OrbState } from '../components/Orb/Orb'

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
  timestamp: Date
}

export type ActivePanel =
  | 'settings'
  | 'drafts'
  | 'connections'
  | 'brief'
  | 'supercharge'
  | null

interface MeridianStore {
  /** Current orb animation state. */
  orbState: OrbState
  /** Full conversation history for the current session. */
  messages: ChatMessage[]
  /** Total tokens used today (mirrors the backend token_usage table). */
  tokensToday: number
  /** Whether the chat modal overlay is open. */
  chatOpen: boolean
  /** Whether the hamburger menu is open. */
  menuOpen: boolean
  /** Which slide-up panel is showing, if any. */
  activePanel: ActivePanel
  /** Email just connected via OAuth — hands off into the onboarding flow. */
  justConnectedEmail: string | null
  /** Account currently being onboarded (sweep → triage → vectorize), if any. */
  onboardingAccountId: number | null
  /** Account whose completed triage results are being reviewed from the Connections panel. */
  triageReviewAccountId: number | null

  setOrbState: (state: OrbState) => void
  addMessage: (msg: ChatMessage) => void
  /** Replace the whole conversation (used to hydrate history from the DB). */
  setMessages: (msgs: ChatMessage[]) => void
  setTokensToday: (n: number) => void
  setChatOpen: (open: boolean) => void
  setMenuOpen: (open: boolean) => void
  setActivePanel: (panel: ActivePanel) => void
  setJustConnectedEmail: (email: string | null) => void
  setOnboardingAccountId: (id: number | null) => void
  setTriageReviewAccountId: (id: number | null) => void
}

export const useMeridianStore = create<MeridianStore>((set) => ({
  orbState: 'idle',
  messages: [],
  tokensToday: 0,
  chatOpen: false,
  menuOpen: false,
  activePanel: null,
  justConnectedEmail: null,
  onboardingAccountId: null,
  triageReviewAccountId: null,

  setOrbState: (orbState) => set({ orbState }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  setMessages: (messages) => set({ messages }),
  setTokensToday: (tokensToday) => set({ tokensToday }),
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setMenuOpen: (menuOpen) => set({ menuOpen }),
  setActivePanel: (activePanel) => set({ activePanel }),
  setJustConnectedEmail: (justConnectedEmail) => set({ justConnectedEmail }),
  setOnboardingAccountId: (onboardingAccountId) => set({ onboardingAccountId }),
  setTriageReviewAccountId: (triageReviewAccountId) => set({ triageReviewAccountId }),
}))
