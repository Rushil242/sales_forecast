/**
 * The plain-English view of a forecast.
 *
 * This sits above the charts because the charts were never the point — a shop owner
 * deciding how much stock to buy needs a sentence, not a quantile band. The analyst
 * view is still one click away for anyone who wants it.
 *
 * Provenance is shown, not hidden: a template brief is a rendering of measured
 * numbers and cannot invent anything, whereas an LLM brief is an interpretation.
 * Those are different things and the badge says which you are reading.
 */

import { Callout, Icon, iconFor } from './ui'
import { num, signedPct } from '../lib/format'

const SEVERITY = {
  info: { dot: 'bg-brand-500', text: 'text-slate-700', chip: 'bg-brand-50 text-brand-700' },
  watch: { dot: 'bg-amber-500', text: 'text-slate-800', chip: 'bg-amber-50 text-amber-700' },
  urgent: { dot: 'bg-rose-500', text: 'text-slate-900', chip: 'bg-rose-50 text-rose-700' },
}

const SOURCE = {
  llm: {
    label: 'AI-written',
    className: 'bg-violet-50 text-violet-700 ring-1 ring-violet-200',
    title: 'Written by Gemini from the measured figures. Every number it used was ' +
           'checked against the data before this was shown.',
  },
  template: {
    label: 'Computed',
    className: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
    title: 'Composed directly from the measured figures. It cannot invent anything.',
  },
  none: {
    label: 'Unavailable',
    className: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
    title: 'No brief could be produced.',
  },
}

function DriverBar({ driver }) {
  const helped = driver.effect?.includes('improve')
  return (
    <div className="flex items-start gap-3 py-2">
      <span
        className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${helped ? 'bg-emerald-500' : 'bg-slate-300'}`}
      />
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-800">{driver.label}</p>
        <p className="text-xs text-slate-500 leading-relaxed">
          {driver.effect}
          {driver.detail ? ` — ${driver.detail}` : ''}
        </p>
      </div>
    </div>
  )
}

export default function OwnerBrief({ envelope, covariates, onShowCharts, compact = false }) {
  if (!envelope?.brief) return null

  const { brief, source, warnings = [], guard_flags: flags = [] } = envelope
  const badge = SOURCE[source] ?? SOURCE.none

  // In analyst view the charts are the point, so the brief shrinks to a single
  // line rather than pushing them below the fold.
  if (compact) {
    return (
      <div
        className="rounded-xl px-5 py-4 flex flex-wrap items-center gap-x-4 gap-y-2"
        style={{ backgroundColor: '#0B1F3A' }}
      >
        <span className="text-[11px] font-semibold uppercase tracking-widest text-teal-300 shrink-0">
          In short
        </span>
        <p className="text-white text-sm sm:text-base font-medium flex-1 min-w-[280px] leading-snug">
          {brief.headline}
        </p>
        <span className={`badge shrink-0 ${badge.className}`} title={badge.title}>
          {badge.label}
        </span>
        <button
          onClick={onShowCharts}
          className="text-xs font-medium text-teal-300 hover:text-teal-200 shrink-0"
        >
          Back to plain English
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ── The headline ────────────────────────────────────────────── */}
      <div className="rounded-xl bg-ink text-white p-6 sm:p-8" style={{ backgroundColor: '#0B1F3A' }}>
        <div className="flex items-start justify-between gap-4 mb-3">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-teal-300">
            What this means
          </span>
          <span
            className={`badge shrink-0 ${badge.className}`}
            title={badge.title}
          >
            {badge.label}
          </span>
        </div>

        <h2 className="font-display text-xl sm:text-2xl font-bold leading-snug">
          {brief.headline}
        </h2>

        {brief.summary && (
          <p className="mt-3 text-slate-300 leading-relaxed max-w-3xl">{brief.summary}</p>
        )}

        {brief.confidence_note && (
          <div className="mt-5 pt-4 border-t border-white/10 flex gap-2.5">
            <Icon.Shield className="w-4 h-4 mt-0.5 shrink-0 text-teal-300" />
            <p className="text-sm text-slate-300 leading-relaxed">{brief.confidence_note}</p>
          </div>
        )}
      </div>

      {flags.length > 0 && (
        <Callout tone="amber" title="The AI-written brief was discarded">
          It referenced {flags.length} figure{flags.length > 1 ? 's' : ''} that were not in
          the measured data ({flags.join(', ')}), so the computed brief is shown instead.
        </Callout>
      )}

      <div className="grid lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4">
        {/* ── What to do ───────────────────────────────────────────── */}
        <div className="card p-6">
          <h3 className="section-title mb-4">What to do</h3>
          <ol className="space-y-3">
            {brief.actions?.map((action, index) => {
              const tone = SEVERITY[action.urgency] ?? SEVERITY.info
              return (
                <li key={action.text} className="flex gap-3">
                  <span
                    className={`shrink-0 w-6 h-6 rounded-full text-xs font-semibold
                                flex items-center justify-center ${tone.chip}`}
                  >
                    {index + 1}
                  </span>
                  <p className={`text-sm leading-relaxed ${tone.text}`}>{action.text}</p>
                </li>
              )
            })}
          </ol>

          {brief.findings?.length > 0 && (
            <>
              <h3 className="section-title mt-6 mb-3">Worth knowing</h3>
              <ul className="space-y-2.5">
                {brief.findings.map((finding) => {
                  const tone = SEVERITY[finding.severity] ?? SEVERITY.info
                  return (
                    <li key={finding.text} className="flex gap-3">
                      <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${tone.dot}`} />
                      <p className={`text-sm leading-relaxed ${tone.text}`}>{finding.text}</p>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>

        {/* ── Why we think this ────────────────────────────────────── */}
        <div className="card p-6">
          <h3 className="section-title">Why we think this</h3>
          <p className="text-xs text-slate-500 mt-0.5 mb-3">
            We test each outside signal on your own sales history and keep only the ones
            that actually improve accuracy.
          </p>

          {brief.drivers?.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {brief.drivers.map((driver) => (
                <DriverBar key={driver.label} driver={driver} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No outside signals were available for this product, so the forecast is
              based on your sales history alone.
            </p>
          )}

          {covariates?.selected_groups?.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <p className="text-xs text-slate-500">
                Using{' '}
                <span className="font-medium text-slate-700">
                  {covariates.selected_groups.join(', ')}
                </span>{' '}
                for {covariates.location}
                {covariates.improvement_pct ? (
                  <>
                    {' '}— worth {signedPct(covariates.improvement_pct, 2)} accuracy
                  </>
                ) : null}
              </p>
            </div>
          )}

          <button
            onClick={onShowCharts}
            className="btn-secondary w-full mt-5 inline-flex items-center justify-center gap-2"
          >
            <Icon.Chart className="w-4 h-4" />
            Show me the numbers
          </button>
        </div>
      </div>

      {warnings.map((warning) => (
        <p key={warning} className="text-xs text-slate-400 leading-relaxed">{warning}</p>
      ))}
    </div>
  )
}
