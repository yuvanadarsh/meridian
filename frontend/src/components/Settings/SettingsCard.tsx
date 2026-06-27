import type { ReactNode } from 'react'

interface SettingsCardProps {
  title: string
  description?: string
  children: ReactNode
}

/**
 * Full-width settings card: a titled, optionally-described container that groups
 * one section of settings. Cards stack vertically down the Settings page.
 */
export function SettingsCard({ title, description, children }: SettingsCardProps) {
  return (
    <div className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6">
      <h2 className="mb-1 text-base font-medium text-white">{title}</h2>
      {description && <p className="mb-4 text-sm text-white/40">{description}</p>}
      {children}
    </div>
  )
}

export default SettingsCard
