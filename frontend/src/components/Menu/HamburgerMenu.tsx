import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { IconType } from 'react-icons'
import {
  HiOutlineBolt,
  HiOutlineDocumentText,
  HiOutlineInbox,
  HiOutlineLink,
  HiOutlineNewspaper,
} from 'react-icons/hi2'
import { IoArrowBack, IoClose, IoSettingsOutline } from 'react-icons/io5'
import { RxHamburgerMenu } from 'react-icons/rx'

import { useMeridianStore } from '../../store/meridianStore'
import type { ActivePanel } from '../../store/meridianStore'
import ConnectionsPanel from './ConnectionsPanel'
import DailyReviewPanel from './DailyReviewPanel'
import DraftsPanel from './DraftsPanel'
import SettingsPanel from './SettingsPanel'
import SuperchargePanel from './SuperchargePanel'

// The Brief opens as its own centered modal rather than a slide-up panel.
type Panel = Exclude<ActivePanel, null | 'brief'>

interface MenuItem {
  label: string
  icon: IconType
  // Either a slide-up panel, or 'brief' which opens the centered Brief modal.
  panel: Panel | 'brief'
}

const MENU_ITEMS: MenuItem[] = [
  { panel: 'settings', label: 'Settings', icon: IoSettingsOutline },
  { panel: 'review', label: 'Review', icon: HiOutlineInbox },
  { panel: 'drafts', label: 'Drafts', icon: HiOutlineDocumentText },
  { panel: 'connections', label: 'Connections', icon: HiOutlineLink },
  { panel: 'brief', label: 'Brief', icon: HiOutlineNewspaper },
  { panel: 'supercharge', label: 'Supercharge', icon: HiOutlineBolt },
]

const PANEL_TITLES: Record<Panel, string> = {
  settings: 'Settings',
  review: 'Daily Review',
  drafts: 'Drafts',
  connections: 'Connections',
  supercharge: 'Supercharge',
}

function PanelContent({ panel }: { panel: Panel }) {
  switch (panel) {
    case 'settings':
      return <SettingsPanel />
    case 'review':
      return <DailyReviewPanel />
    case 'drafts':
      return <DraftsPanel />
    case 'connections':
      return <ConnectionsPanel />
    case 'supercharge':
      return <SuperchargePanel />
  }
}

/**
 * Bottom-left circular button that opens a slide-up panel. The panel first
 * shows the four menu options; selecting one swaps in that panel's content.
 */
export function HamburgerMenu() {
  const menuOpen = useMeridianStore((state) => state.menuOpen)
  const activePanel = useMeridianStore((state) => state.activePanel)
  const setMenuOpen = useMeridianStore((state) => state.setMenuOpen)
  const setActivePanel = useMeridianStore((state) => state.setActivePanel)
  const setBriefOpen = useMeridianStore((state) => state.setBriefOpen)

  const close = () => {
    setMenuOpen(false)
    setActivePanel(null)
  }

  // Escape closes the menu (and any open panel within it), matching the chat and
  // brief modals so every overlay dismisses the same way.
  useEffect(() => {
    if (!menuOpen) return
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [menuOpen])

  const openItem = (panel: Panel | 'brief') => {
    if (panel === 'brief') {
      // The Brief is a centered modal — close the menu and open it.
      close()
      setBriefOpen(true)
      return
    }
    setActivePanel(panel)
  }

  // activePanel never holds 'brief' (Brief opens as a modal), so this is a Panel.
  const slidePanel = activePanel === 'brief' ? null : activePanel

  return (
    <>
      <button
        type="button"
        aria-label="Open menu"
        onClick={() => setMenuOpen(true)}
        className="fixed bottom-6 left-6 z-20 flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/10 text-white/80 backdrop-blur transition-colors hover:bg-white/15 hover:text-white"
      >
        <RxHamburgerMenu size={20} />
      </button>

      <AnimatePresence>
        {menuOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={close}
            />

            <motion.div
              className="fixed inset-x-0 bottom-0 z-40 mx-auto max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-t-3xl border border-white/10 bg-[#0d0d0f]/95 p-6 backdrop-blur-xl"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            >
              <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {slidePanel && (
                    <button
                      type="button"
                      aria-label="Back"
                      onClick={() => setActivePanel(null)}
                      className="flex h-8 w-8 items-center justify-center rounded-full text-white/60 transition-colors hover:bg-white/10 hover:text-white"
                    >
                      <IoArrowBack size={18} />
                    </button>
                  )}
                  <h2 className="text-base font-semibold text-white">
                    {slidePanel ? PANEL_TITLES[slidePanel] : 'Menu'}
                  </h2>
                </div>
                <button
                  type="button"
                  aria-label="Close menu"
                  onClick={close}
                  className="flex h-8 w-8 items-center justify-center rounded-full text-white/60 transition-colors hover:bg-white/10 hover:text-white"
                >
                  <IoClose size={20} />
                </button>
              </div>

              {slidePanel ? (
                <PanelContent panel={slidePanel} />
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {MENU_ITEMS.map((item) => (
                    <button
                      key={item.panel}
                      type="button"
                      onClick={() => openItem(item.panel)}
                      className="flex flex-col items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-5 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
                    >
                      <item.icon size={22} />
                      <span className="text-sm">{item.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

export default HamburgerMenu
