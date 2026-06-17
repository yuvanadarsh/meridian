/**
 * Drafts placeholder. Meridian will draft replies in the user's voice in a
 * later phase; this panel will list them for review.
 */
export function DraftsPanel() {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <p className="text-sm text-white/60">No drafts yet</p>
      <p className="text-xs text-white/30">
        Meridian will draft replies in your voice in a later phase.
      </p>
    </div>
  )
}

export default DraftsPanel
