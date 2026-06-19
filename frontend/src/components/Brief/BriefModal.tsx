import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { IoClose } from 'react-icons/io5'

import DailyBrief from './DailyBrief'

interface BriefModalProps {
  open: boolean
  onClose: () => void
}

/**
 * Centered Daily Brief overlay, matching the chat modal pattern: a dimmed,
 * blurred backdrop with a centered panel that scrolls its content. Clicking the
 * backdrop or pressing Escape closes it.
 */
export function BriefModal({ open, onClose }: BriefModalProps) {
  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={onClose}
        >
          <motion.div
            className="flex max-h-[80vh] w-[720px] max-w-full flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0a0a0a]/90 shadow-2xl"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3">
              <span className="text-sm font-medium text-white/70">Daily Brief</span>
              <button
                type="button"
                aria-label="Close brief"
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-full text-white/50 transition-colors hover:bg-white/10 hover:text-white"
              >
                <IoClose size={20} />
              </button>
            </div>

            <div className="overflow-y-auto p-5">
              <DailyBrief />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default BriefModal
