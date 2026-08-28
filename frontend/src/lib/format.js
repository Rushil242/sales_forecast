/** Shared formatting helpers, so numbers read the same way everywhere. */

export const num = (value, digits = 0) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : Number(value).toLocaleString('en-GB', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })

export const pct = (value, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : `${Number(value).toFixed(digits)}%`

export const signedPct = (value, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? '--'
    : `${value >= 0 ? '+' : ''}${Number(value).toFixed(digits)}%`

export const shortDate = (iso) => {
  const date = new Date(`${iso}T00:00:00`)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

export const longDate = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export const relativeTime = (iso) => {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/** Sentiment in [-1, 1] to a semantic colour set. */
export const sentimentTone = (score) => {
  if (score > 0.15) return { text: 'text-emerald-600', bg: 'bg-emerald-50', dot: 'bg-emerald-500' }
  if (score < -0.15) return { text: 'text-rose-600', bg: 'bg-rose-50', dot: 'bg-rose-500' }
  return { text: 'text-slate-600', bg: 'bg-slate-100', dot: 'bg-slate-400' }
}

export const QUALITY_TONE = {
  good: { label: 'Good', className: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' },
  adequate: { label: 'Adequate', className: 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' },
  limited: { label: 'Limited', className: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200' },
  insufficient: { label: 'Insufficient', className: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200' },
}

/**
 * MASE below 1 beats a seasonal-naive forecast; that threshold is the whole
 * point of the metric, so the colouring encodes it directly.
 */
export const maseTone = (mase) => {
  if (mase === null || mase === undefined) return 'text-slate-400'
  if (mase < 0.8) return 'text-emerald-600 font-semibold'
  if (mase < 1.0) return 'text-brand-700 font-medium'
  return 'text-rose-600'
}
