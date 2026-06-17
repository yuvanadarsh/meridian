import { RxHamburgerMenu } from 'react-icons/rx'

import ChatHistory from './components/Chat/ChatHistory'
import ChatInput from './components/Chat/ChatInput'
import Orb from './components/Orb/Orb'
import { useMeridianStore } from './store/meridianStore'

/**
 * Meridian's main screen: the orb at the center, conversation and prompt
 * stacked beneath it, with the wordmark, token counter, and menu around the
 * edges. Everything stays quiet so the orb reads as the centerpiece.
 */
function App() {
  const orbState = useMeridianStore((state) => state.orbState)
  const messages = useMeridianStore((state) => state.messages)
  const tokensToday = useMeridianStore((state) => state.tokensToday)
  const addMessage = useMeridianStore((state) => state.addMessage)
  const setMenuOpen = useMeridianStore((state) => state.setMenuOpen)

  // Wired to the Claude API in a later step; for now it echoes the user's turn.
  const handleSubmit = (text: string) => {
    addMessage({ role: 'user', content: text, timestamp: new Date() })
  }

  return (
    <main className="relative min-h-screen w-full overflow-hidden bg-[#0a0a0a] bg-[radial-gradient(ellipse_at_center,_#111827_0%,_#0a0a0a_70%)] text-white">
      <span className="absolute left-6 top-5 z-10 text-xl font-semibold tracking-tight text-white">
        Meridian
      </span>

      {/* Live polling counter replaces this span in a later step. */}
      <span className="absolute right-4 top-4 z-10 font-mono text-xs text-white/40">
        Tokens today: {tokensToday.toLocaleString()}
      </span>

      <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-4 py-16">
        <Orb state={orbState} />
        <ChatHistory messages={messages} />
        <ChatInput onSubmit={handleSubmit} />
      </div>

      {/* Full slide-up menu is added in the next step. */}
      <button
        type="button"
        aria-label="Open menu"
        onClick={() => setMenuOpen(true)}
        className="fixed bottom-6 left-6 z-10 flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/10 text-white/80 backdrop-blur transition-colors hover:bg-white/15 hover:text-white"
      >
        <RxHamburgerMenu size={20} />
      </button>
    </main>
  )
}

export default App
