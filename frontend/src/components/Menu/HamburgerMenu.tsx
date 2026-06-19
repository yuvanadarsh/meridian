import { AnimatePresence, motion } from 'framer-motion'
import type { IconType } from 'react-icons'
import {
  HiOutlineBolt,
  HiOutlineDocumentText,
  HiOutlineLink,
  HiOutlineNewspaper,
} from 'react-icons/hi2'
import { IoArrowBack, IoClose, IoSettingsOutline } from 'react-icons/io5'
import { RxHamburgerMenu } from 'react-icons/rx'

import { useMeridianStore } from '../../store/meridianStore'
import type { ActivePanel } from '../../store/meridianStore'
import DailyBrief from '../Brief/DailyBrief'
import ConnectionsPanel from './ConnectionsPanel'
import DraftsPanel from './DraftsPanel'
import SettingsPanel from './SettingsPanel'
import SuperchargePanel from './SuperchargePanel'

type Panel = Exclude<ActivePanel, null>

interface MenuItem {
  panel: Panel
  label: string
  icon: IconType
}

const MENU_ITEMS: MenuItem[] = [
  { panel: 'settings', label: 'Settings', icon: IoSettingsOutline },
  { panel: 'drafts', label: 'Drafts', icon: HiOutlineDocumentText },
  { panel: 'connections', label: 'Connections', icon: HiOutlineLink },
  { panel: 'brief', label: 'Brief', icon: HiOutlineNewspaper },
  { panel: 'supercharge', label: 'Supercharge', icon: HiOutlineBolt },
]

const PANEL_TITLES: Record<Panel, string> = {
  settings: 'Settings',
  drafts: 'Drafts',
  connections: 'Connections',
  brief: 'Daily Brief',
  supercharge: 'Supercharge',
}

function PanelContent({ panel }: { panel: Panel }) {
  switch (panel) {
    case 'settings':
      return <SettingsPanel />
    case 'drafts':
      return <DraftsPanel />
    case 'connections':
      return <ConnectionsPanel />
    case 'brief':
      return <DailyBrief />
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

  const close = () => {
    setMenuOpen(false)
    setActivePanel(null)
  }

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
                  {activePanel && (
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
                    {activePanel ? PANEL_TITLES[activePanel] : 'Menu'}
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

              {activePanel ? (
                <PanelContent panel={activePanel} />
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {MENU_ITEMS.map((item) => (
                    <button
                      key={item.panel}
                      type="button"
                      onClick={() => setActivePanel(item.panel)}
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
