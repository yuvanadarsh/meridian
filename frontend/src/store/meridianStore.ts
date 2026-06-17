import { create } from 'zustand'

import type { OrbState } from '../components/Orb/Orb'

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
  timestamp: Date
}

export type ActivePanel = 'settings' | 'drafts' | 'connections' | 'brief' | null

interface MeridianStore {
  /** Current orb animation state. */
  orbState: OrbState
  /** Full conversation history for the current session. */
  messages: ChatMessage[]
  /** Total tokens used today (mirrors the backend token_usage table). */
  tokensToday: number
  /** Whether the hamburger menu is open. */
  menuOpen: boolean
  /** Which slide-up panel is showing, if any. */
  activePanel: ActivePanel

  setOrbState: (state: OrbState) => void
  addMessage: (msg: ChatMessage) => void
  setTokensToday: (n: number) => void
  setMenuOpen: (open: boolean) => void
  setActivePanel: (panel: ActivePanel) => void
}

export const useMeridianStore = create<MeridianStore>((set) => ({
  orbState: 'idle',
  messages: [],
  tokensToday: 0,
  menuOpen: false,
  activePanel: null,

  setOrbState: (orbState) => set({ orbState }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  setTokensToday: (tokensToday) => set({ tokensToday }),
  setMenuOpen: (menuOpen) => set({ menuOpen }),
  setActivePanel: (activePanel) => set({ activePanel }),
}))
