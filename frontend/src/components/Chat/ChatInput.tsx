interface ChatInputProps {
  /** Opens the chat modal — this bar is a trigger, not a live input. */
  onOpen: () => void
}

/**
 * The pill-shaped, glassmorphic bar below the orb. Clicking it (like clicking
 * the orb) opens the chat modal, where the real conversation happens.
 */
export function ChatInput({ onOpen }: ChatInputProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Open chat"
      className="w-[600px] max-w-[90vw] rounded-[28px] border border-white/10 bg-white/5 px-5 py-3 text-left text-sm text-white/30 backdrop-blur transition-colors hover:border-white/20 hover:text-white/50"
    >
      Talk to Meridian
    </button>
  )
}

export default ChatInput
