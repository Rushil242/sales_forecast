/**
 * Scroll-reveal and count-up primitives.
 *
 * Deliberately no animation library. Everything here is an IntersectionObserver
 * plus a CSS class, which keeps the runtime off the critical path and means a
 * `prefers-reduced-motion` user gets the whole system disabled by one media
 * query in index.css rather than by JavaScript branching in a dozen places.
 *
 * The rule these follow: motion signals *arrival* of content, never decorates
 * content that is already there. Things animate once, on first sight, and then
 * stay put -- a dashboard that re-animates every time you scroll past is
 * exhausting to actually use.
 */

import { useEffect, useRef, useState } from 'react'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Reveal children when they first scroll into view.
 *
 * `stagger` cascades the immediate children instead of moving the block as one.
 */
export function Reveal({
  children,
  stagger = false,
  delay = 0,
  threshold = 0.12,
  className = '',
  as: Tag = 'div',
}) {
  const ref = useRef(null)
  const [revealed, setRevealed] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    // No observer, or motion is unwelcome: show it immediately.
    if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
      setRevealed(true)
      return
    }

    // Content already on screen at mount should not wait for a scroll event.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        const timer = setTimeout(() => setRevealed(true), delay)
        observer.disconnect()
        return () => clearTimeout(timer)
      },
      { threshold, rootMargin: '0px 0px -40px 0px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [delay, threshold])

  const base = stagger ? 'reveal-stagger' : 'reveal'
  return (
    <Tag ref={ref} className={`${base} ${revealed ? 'is-revealed' : ''} ${className}`}>
      {children}
    </Tag>
  )
}

/**
 * Count a number up to its value when it first appears, and animate between
 * values afterwards.
 *
 * Rounds to `decimals` throughout, so an integer never flickers through
 * fractional frames on its way to the answer.
 */
export function AnimatedNumber({
  value,
  decimals = 0,
  duration = 900,
  format = (n) => n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }),
  className = '',
}) {
  const [display, setDisplay] = useState(() => (prefersReducedMotion() ? value : 0))
  const fromRef = useRef(0)
  const frameRef = useRef(0)

  useEffect(() => {
    if (typeof value !== 'number' || Number.isNaN(value)) return
    if (prefersReducedMotion()) {
      setDisplay(value)
      return
    }

    const from = fromRef.current
    const start = performance.now()

    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      // Ease-out-expo: most of the distance early, then a long settle. Reads as
      // "resolving to a figure" rather than a linear counter.
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t)
      setDisplay(from + (value - from) * eased)
      if (t < 1) frameRef.current = requestAnimationFrame(tick)
      else fromRef.current = value
    }

    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
  }, [value, duration])

  if (typeof value !== 'number' || Number.isNaN(value)) {
    return <span className={className}>--</span>
  }
  return <span className={`tabular-nums ${className}`}>{format(display)}</span>
}

/** Fade/slide a subtree whenever `trigger` changes. Used for page switches. */
export function Transition({ trigger, children, className = '' }) {
  const [shown, setShown] = useState(false)

  useEffect(() => {
    setShown(false)
    const timer = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(timer)
  }, [trigger])

  return (
    <div
      className={`transition-all duration-500 ease-out-expo ${
        shown ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      } ${className}`}
    >
      {children}
    </div>
  )
}
