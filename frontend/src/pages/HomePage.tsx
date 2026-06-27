import { BsMicFill, BsMicMuteFill } from 'react-icons/bs'
import { HiOutlineChatBubbleLeft } from 'react-icons/hi2'

import ChatModal from '../components/Chat/ChatModal'
import Orb from '../components/Orb/Orb'
import { useChat } from '../hooks/useChat'
import { useVoice } from '../hooks/useVoice'
import { useMeridianStore } from '../store/meridianStore'

/**
 * Home: just the orb, centered. Clicking the orb opens the daily chat modal;
 * holding Space starts push-to-talk (handled globally by `useVoice`). The chat
 * modal's own input is the only text entry — there is no separate input bar,
 * glance strip, or token counter on this page anymore.
 */
export function HomePage() {
  const orbState = useMeridianStore((state) => state.orbState)
  const messages = useMeridianStore((state) => state.messages)
  const chatOpen = useMeridianStore((state) => state.chatOpen)
  const setChatOpen = useMeridianStore((state) => state.setChatOpen)
  const chatPrefill = useMeridianStore((state) => state.chatPrefill)
  const setChatPrefill = useMeridianStore((state) => state.setChatPrefill)
  const { send, sending } = useChat()
  // Mounting useVoice here wires the global Space-to-talk listener while Home is
  // visible. Voice behavior is unchanged from the previous single-page layout.
  const { recording, supported, toggleRecording } = useVoice()

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-6 px-4">
      {/* Orb — clicking opens the daily chat modal (Orb renders its own
          role="button" target, so it isn't wrapped in another button). */}
      <Orb state={orbState} onClick={() => setChatOpen(true)} />

      {/* Subtle hints: push-to-talk (when supported) and click-to-chat. */}
      <div className="-mt-2 flex items-center gap-3 text-xs text-white/20">
        {supported && (
          <>
            <button
              type="button"
              onClick={toggleRecording}
              aria-label={recording ? 'Stop recording' : 'Start recording'}
              className="flex items-center gap-1 transition-colors hover:text-white/40"
            >
              {recording ? <BsMicFill className="h-3 w-3" /> : <BsMicMuteFill className="h-3 w-3" />}
              Hold Space to talk
            </button>
            <span className="text-white/10">·</span>
          </>
        )}
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          className="flex items-center gap-1 transition-colors hover:text-white/40"
        >
          <HiOutlineChatBubbleLeft className="h-3 w-3" />
          Click to chat
        </button>
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
        prefill={chatPrefill}
        onPrefillConsumed={() => setChatPrefill(null)}
      />
    </div>
  )
}

export default HomePage
