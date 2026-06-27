import { PageLayout } from '../components/Layout/PageLayout'
import { SettingsPanel } from '../components/Menu/SettingsPanel'

/**
 * Full-page Settings. Renders the existing SettingsPanel for now; the forge-style
 * card redesign replaces its internals in a follow-up commit.
 */
export function SettingsPage() {
  return (
    <PageLayout title="Settings" subtitle="Configure your Meridian instance.">
      <SettingsPanel />
    </PageLayout>
  )
}

export default SettingsPage
