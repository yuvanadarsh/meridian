import { useMemo } from 'react'
import { BsMicFill, BsMicMuteFill } from 'react-icons/bs'

import ChatInput from './components/Chat/ChatInput'
import ChatModal from './components/Chat/ChatModal'
import HamburgerMenu from './components/Menu/HamburgerMenu'
import Orb from './components/Orb/Orb'
import TokenCounter from './components/TokenUsage/TokenCounter'
import { useChat } from './hooks/useChat'
import { useVoice } from './hooks/useVoice'
import { useMeridianStore } from './store/meridianStore'

/** Strip common markdown markers so the one-line subtitle reads cleanly. */
function plainPreview(text: string): string {
  return text.replace(/[*_`#>~]/g, '').replace(/\s+/g, ' ').trim()
}

/**
 * Meridian's main screen: the orb at the center with the wordmark, token
 * counter, and menu around the edges. Clicking the orb (or the bar beneath it)
 * opens the chat modal; the last reply shows as a one-line subtitle when it's
 * closed.
 */
function App() {
  const orbState = useMeridianStore((state) => state.orbState)
  const messages = useMeridianStore((state) => state.messages)
  const chatOpen = useMeridianStore((state) => state.chatOpen)
  const setChatOpen = useMeridianStore((state) => state.setChatOpen)
  const { send, sending } = useChat()
  const { recording, supported, toggleRecording } = useVoice()

  const lastAssistant = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return plainPreview(messages[i].content)
    }
    return ''
  }, [messages])

  const openChat = () => setChatOpen(true)

  return (
    <main className="relative min-h-screen w-full overflow-hidden bg-[#0a0a0a] bg-[radial-gradient(ellipse_at_center,_#111827_0%,_#0a0a0a_70%)] text-white">
      <span className="absolute left-6 top-5 z-10 text-xl font-semibold tracking-tight text-white">
        Meridian
      </span>

      <TokenCounter />

      <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 py-16">
        <Orb state={orbState} onClick={openChat} />

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

        {!chatOpen && lastAssistant && (
          <p className="w-[600px] max-w-[90vw] truncate px-4 text-center text-sm text-white/40">
            {lastAssistant}
          </p>
        )}

        <ChatInput onOpen={openChat} />
      </div>

      <ChatModal
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        messages={messages}
        onSend={(text) => void send(text)}
        sending={sending}
        voiceSupported={supported}
        recording={recording}
        onToggleMic={toggleRecording}
      />

      <HamburgerMenu />
    </main>
  )
}

export default App
