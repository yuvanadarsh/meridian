import { useEffect, useRef } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

/** The four states the orb can occupy — drives rotation speed, size, and glow. */
export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking'

interface StateConfig {
  /** Wrapper + canvas size in px — tweened by Framer Motion between states. */
  size: number
  /** Y-axis rotation per frame in radians (negative reverses direction). */
  rotationSpeed: number
}

// Per-state configuration. Opacity/size pulses are computed per-frame in the
// render loop (they depend on elapsed time), so only the static values live here.
const STATE_CONFIG: Record<OrbState, StateConfig> = {
  idle: { size: 300, rotationSpeed: 0.003 },
  listening: { size: 340, rotationSpeed: 0.008 },
  // Direction reverses slowly to read as "turning the problem over".
  thinking: { size: 340, rotationSpeed: -0.002 },
  speaking: { size: 350, rotationSpeed: 0.01 },
}

// A latitude/longitude dot grid: 12 rings × 25 points ≈ 300 dots. The sphere
// shape emerges purely from this pattern — there is no fill or outline.
const LAT_RINGS = 12
const LON_POINTS = 25

interface Dot {
  x: number
  y: number
  /** Dot radius in px. */
  r: number
  /** Alpha 0–1. */
  o: number
  /** Projected depth, used to paint back-to-front. */
  z: number
}

interface OrbProps {
  state: OrbState
  /** Optional click handler — clicking the orb opens the chat modal. */
  onClick?: () => void
}

/**
 * The orb — Meridian's visual core. A canvas draws a rotating sphere of white
 * dots via orthographic projection; Framer Motion tweens the canvas size and
 * the CSS glow between states. The rotation/pulse animation runs entirely in a
 * requestAnimationFrame loop, reading the latest state from refs so prop
 * changes never restart it.
 */
export function Orb({ state, onClick }: OrbProps) {
  const reduceMotion = useReducedMotion()
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Live values the rAF loop reads without re-subscribing each render.
  const stateRef = useRef<OrbState>(state)
  const angleRef = useRef(0)
  const reduceRef = useRef<boolean>(Boolean(reduceMotion))

  useEffect(() => {
    stateRef.current = state
  }, [state])
  useEffect(() => {
    reduceRef.current = Boolean(reduceMotion)
  }, [reduceMotion])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    const start = performance.now()

    const render = (now: number) => {
      const elapsed = (now - start) / 1000 // seconds
      const current = stateRef.current
      const config = STATE_CONFIG[current]
      const reduce = reduceRef.current

      // Advance rotation (frozen entirely when reduced motion is requested).
      if (!reduce) {
        angleRef.current += config.rotationSpeed
      }
      const angle = angleRef.current

      // Track the displayed size (which Framer Motion animates) and keep the
      // backing buffer at device-pixel resolution so dots stay crisp.
      const dpr = window.devicePixelRatio || 1
      const cssSize = canvas.clientWidth || config.size
      const buffer = Math.round(cssSize * dpr)
      if (canvas.width !== buffer || canvas.height !== buffer) {
        canvas.width = buffer
        canvas.height = buffer
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, cssSize, cssSize)

      const center = cssSize / 2
      const radius = cssSize * 0.42 // leaves margin for the equator dots + glow

      // Base alpha per state. `thinking` breathes on a 0.8s sine wave.
      let baseOpacity = current === 'listening' ? 0.9 : 0.6
      if (current === 'thinking') {
        const wave = reduce ? 0.5 : 0.5 + 0.5 * Math.sin((elapsed / 0.8) * Math.PI * 2)
        baseOpacity = 0.4 + 0.5 * wave // sweeps 0.4 → 0.9
      }
      // `speaking` pulses the equator dots outward (radius 2 → 3.5px).
      const speakingPulse =
        current === 'speaking' && !reduce
          ? 0.5 + 0.5 * Math.sin((elapsed / 0.4) * Math.PI * 2)
          : 0

      const dots: Dot[] = []
      for (let i = 0; i < LAT_RINGS; i++) {
        // Distribute rings across the band, skipping the exact poles.
        const lat = -Math.PI / 2 + (Math.PI * (i + 0.5)) / LAT_RINGS
        const cosLat = Math.cos(lat) // 1 at equator → 0 at poles
        const sinLat = Math.sin(lat)
        for (let p = 0; p < LON_POINTS; p++) {
          const lon = (Math.PI * 2 * p) / LON_POINTS
          const z = cosLat * Math.cos(lon + angle)
          if (z <= -0.2) continue // cull the far hemisphere (with slight wrap)

          const x = center + radius * cosLat * Math.sin(lon + angle)
          const y = center + radius * sinLat
          const depth = (z + 1) / 2 // back dots dimmer

          let r = 2 + 0.5 * cosLat // 2px at poles → 2.5px at the equator
          if (speakingPulse) r += 1.5 * cosLat * speakingPulse // → up to 3.5px
          const o = Math.min(1, baseOpacity * depth * (0.7 + 0.3 * cosLat))
          dots.push({ x, y, r, o, z })
        }
      }

      // Paint far dots first so nearer ones layer on top.
      dots.sort((a, b) => a.z - b.z)
      for (const dot of dots) {
        ctx.beginPath()
        ctx.arc(dot.x, dot.y, dot.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255, 255, 255, ${dot.o})`
        ctx.fill()
      }

      raf = requestAnimationFrame(render)
    }

    raf = requestAnimationFrame(render)
    return () => cancelAnimationFrame(raf)
  }, [])

  const size = STATE_CONFIG[state].size

  return (
    // Fixed-size stage keeps the layout stable while the orb grows and shrinks.
    <div
      className="relative flex items-center justify-center"
      style={{ width: 440, height: 440 }}
    >
      <motion.div
        className={onClick ? 'cursor-pointer' : undefined}
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        aria-label={onClick ? 'Open chat' : undefined}
        initial={false}
        animate={{ width: size, height: size }}
        transition={{ duration: 0.7, ease: 'easeInOut' }}
        // Soft diffuse glow around the whole dot field.
        style={{ filter: 'drop-shadow(0 0 40px rgba(255, 255, 255, 0.15))' }}
      >
        <canvas ref={canvasRef} className="h-full w-full" />
      </motion.div>
    </div>
  )
}

export default Orb
