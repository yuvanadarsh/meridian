import { motion } from 'framer-motion'
import type { IconType } from 'react-icons'
import {
  HiOutlineCalendarDays,
  HiOutlineChartBar,
  HiOutlineChatBubbleLeft,
  HiOutlineCog6Tooth,
  HiOutlineDocumentText,
  HiOutlineHome,
  HiOutlineInboxArrowDown,
  HiOutlineLink,
  HiOutlineUsers,
} from 'react-icons/hi2'
import { NavLink } from 'react-router-dom'

interface NavItem {
  path: string
  label: string
  icon: IconType
}

// Grouped navigation. The first two sections sit at the top; the last section
// (Connections, Settings) is pinned to the bottom of the sidebar.
const NAV_SECTIONS: NavItem[][] = [
  [
    { path: '/', label: 'Home', icon: HiOutlineHome },
    { path: '/analytics', label: 'Analytics', icon: HiOutlineChartBar },
  ],
  [
    { path: '/chat', label: 'Chat', icon: HiOutlineChatBubbleLeft },
    { path: '/drafts', label: 'Drafts', icon: HiOutlineDocumentText },
    { path: '/inbox', label: 'Inbox', icon: HiOutlineInboxArrowDown },
    { path: '/contacts', label: 'Contacts', icon: HiOutlineUsers },
    { path: '/calendar', label: 'Calendar', icon: HiOutlineCalendarDays },
  ],
]

// Pinned to the bottom, visually separated from the scrolling nav above.
const BOTTOM_SECTION: NavItem[] = [
  { path: '/connections', label: 'Connections', icon: HiOutlineLink },
  { path: '/settings', label: 'Settings', icon: HiOutlineCog6Tooth },
]

function NavRow({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.path}
      // `end` so the Home route ("/") is only active on an exact match, not on
      // every nested path.
      end={item.path === '/'}
      className={({ isActive }) =>
        `mx-2 flex items-center gap-3 rounded-lg border-l-2 px-4 py-2 text-sm transition-colors ${
          isActive
            ? 'border-white bg-white/[0.08] text-white'
            : 'border-transparent text-white/40 hover:bg-white/[0.04] hover:text-white/70'
        }`
      }
    >
      <item.icon size={20} className="shrink-0" />
      <span>{item.label}</span>
    </NavLink>
  )
}

/**
 * Persistent left navigation rail. Always visible at 220px on desktop; slides in
 * from the left on mount. Active route is derived from React Router via NavLink.
 */
export function Sidebar() {
  return (
    <motion.aside
      initial={{ x: -220, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="fixed left-0 top-0 z-40 flex h-screen w-[220px] flex-col border-r border-white/5 bg-[#0a0a0a]"
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="h-4 w-4 rounded-full bg-gradient-to-br from-[#1a3a5c] to-[#0d1b2a] shadow-[0_0_8px_rgba(124,58,237,0.6)]" />
        <span className="text-sm font-semibold tracking-tight text-white">Meridian</span>
      </div>

      {/* Top + middle sections */}
      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_SECTIONS.map((section, index) => (
          <div
            key={index}
            className={`flex flex-col gap-0.5 py-2 ${
              index > 0 ? 'border-t border-white/5' : ''
            }`}
          >
            {section.map((item) => (
              <NavRow key={item.path} item={item} />
            ))}
          </div>
        ))}
      </nav>

      {/* Bottom section — Connections + Settings */}
      <div className="flex flex-col gap-0.5 border-t border-white/5 py-3">
        {BOTTOM_SECTION.map((item) => (
          <NavRow key={item.path} item={item} />
        ))}
      </div>
    </motion.aside>
  )
}

export default Sidebar
