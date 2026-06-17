import Orb from './components/Orb/Orb'

/**
 * App shell. The full layout (chat, menu, token counter) is assembled in a
 * later step; for now it centers the orb on Meridian's dark canvas.
 */
function App() {
  return (
    <main className="relative min-h-screen w-full overflow-hidden bg-[#0a0a0a] bg-[radial-gradient(ellipse_at_center,_#111827_0%,_#0a0a0a_70%)]">
      <span className="absolute left-6 top-5 text-xl font-semibold tracking-tight text-white">
        Meridian
      </span>

      <div className="flex min-h-screen items-center justify-center">
        <Orb state="idle" />
      </div>
    </main>
  )
}

export default App
