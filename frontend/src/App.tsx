import { BsMicFill, BsMicMuteFill } from 'react-icons/bs'

import ChatHistory from './components/Chat/ChatHistory'
import ChatInput from './components/Chat/ChatInput'
import HamburgerMenu from './components/Menu/HamburgerMenu'
import Orb from './components/Orb/Orb'
import { useChat } from './hooks/useChat'
import { useVoice } from './hooks/useVoice'
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
  const { send, sending } = useChat()
  const { recording, supported, toggleRecording } = useVoice()

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

        {supported && (
          <div className="-mt-2 flex flex-col items-center gap-2">
            <button
              type="button"
              onClick={toggleRecording}
              aria-label={recording ? 'Stop recording' : 'Start recording'}
              className={`flex h-10 w-10 items-center justify-center rounded-full border border-white/10 backdrop-blur transition-colors ${
                recording ? 'bg-white/15 text-white' : 'bg-white/5 text-white/30 hover:text-white/60'
              }`}
            >
              {recording ? <BsMicFill size={18} /> : <BsMicMuteFill size={18} />}
            </button>
            <span className="text-[11px] text-white/25">Hold space to talk</span>
          </div>
        )}

        <ChatHistory messages={messages} />
        <ChatInput onSubmit={send} disabled={sending} />
      </div>

      <HamburgerMenu />
    </main>
  )
}

export default App
