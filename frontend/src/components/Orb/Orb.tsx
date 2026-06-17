import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { BsMicFill } from 'react-icons/bs'

/** The four states the orb can occupy — drives every visual property below. */
export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking'

interface OrbVisual {
  /** Diameter in pixels. */
  size: number
  /** Organic border-radius keyframes the shape morphs through. */
  borderRadius: string[]
  /** Seconds for one border-radius morph sweep. */
  morphDuration: number
  /** Layered chromatic glow (magenta / purple / cyan). */
  boxShadow: string
  /** Scale keyframes for the breathing / pulse animation. */
  scale: number[]
  /** Seconds for one scale cycle. */
  scaleDuration: number
}

/** Radial core gradient — a lit sphere reading top-left. */
const CORE_GRADIENT = 'radial-gradient(circle at 35% 35%, #1e4a7a, #0d1b2a 70%)'

// Per-state visual config. `thinking` and `speaking` are filled in by the next
// build step; until then they fall back to `idle` via the lookup below.
const ORB_VISUALS: Partial<Record<OrbState, OrbVisual>> = {
  idle: {
    size: 300,
    borderRadius: [
      '60% 40% 55% 45% / 50% 60% 40% 50%',
      '45% 55% 40% 60% / 60% 40% 55% 45%',
    ],
    morphDuration: 8,
    boxShadow:
      '0 0 60px 20px rgba(192, 38, 211, 0.3), 0 0 120px 40px rgba(124, 58, 237, 0.15), 0 0 200px 80px rgba(14, 165, 233, 0.08)',
    scale: [0.97, 1.03, 0.97],
    scaleDuration: 3,
  },
  listening: {
    size: 380,
    borderRadius: [
      '60% 40% 55% 45% / 50% 60% 40% 50%',
      '40% 60% 45% 55% / 55% 45% 60% 40%',
    ],
    morphDuration: 1.5,
    boxShadow:
      '0 0 80px 30px rgba(192, 38, 211, 0.5), 0 0 160px 60px rgba(124, 58, 237, 0.25), 0 0 220px 90px rgba(14, 165, 233, 0.12)',
    scale: [0.95, 1.08, 0.95],
    scaleDuration: 1.5,
  },
}

const FALLBACK_VISUAL = ORB_VISUALS.idle as OrbVisual

interface OrbProps {
  state: OrbState
}

/**
 * The orb — Meridian's visual and interactive core. Its size, shape, glow, and
 * rhythm all shift with `state` to make the assistant feel alive.
 */
export function Orb({ state }: OrbProps) {
  const reduceMotion = useReducedMotion()
  const visual = ORB_VISUALS[state] ?? FALLBACK_VISUAL
  const showMic = state === 'listening'

  return (
    // Fixed-size stage keeps the layout stable while the orb grows and shrinks.
    <div
      className="relative flex items-center justify-center"
      style={{ width: 440, height: 440 }}
    >
      <motion.div
        className="relative"
        style={{ background: CORE_GRADIENT }}
        animate={
          reduceMotion
            ? {
                width: visual.size,
                height: visual.size,
                borderRadius: visual.borderRadius[0],
                boxShadow: visual.boxShadow,
                scale: 1,
              }
            : {
                width: visual.size,
                height: visual.size,
                borderRadius: visual.borderRadius,
                boxShadow: visual.boxShadow,
                scale: visual.scale,
              }
        }
        transition={
          reduceMotion
            ? { duration: 0.6, ease: 'easeInOut' }
            : {
                width: { duration: 0.7, ease: 'easeInOut' },
                height: { duration: 0.7, ease: 'easeInOut' },
                boxShadow: { duration: 0.7, ease: 'easeInOut' },
                borderRadius: {
                  duration: visual.morphDuration,
                  ease: 'easeInOut',
                  repeat: Infinity,
                  repeatType: 'reverse',
                },
                scale: {
                  duration: visual.scaleDuration,
                  ease: 'easeInOut',
                  repeat: Infinity,
                  repeatType: 'loop',
                },
              }
        }
      >
        <AnimatePresence>
          {showMic && (
            <motion.div
              key="mic"
              className="absolute inset-0 flex items-center justify-center text-white"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            >
              <BsMicFill size={32} aria-hidden />
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}

export default Orb
