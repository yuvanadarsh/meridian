import type { ReactNode } from 'react'

interface PageLayoutProps {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
}

/**
 * Shared page chrome: a header with title/subtitle and an optional actions slot
 * on the right, above the page content. Every routed page wraps its content in
 * this so headers, spacing, and max width stay consistent across the app.
 */
export function PageLayout({ title, subtitle, actions, children }: PageLayoutProps) {
  return (
    <div className="min-h-full p-8">
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-white/40">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-3">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export default PageLayout
