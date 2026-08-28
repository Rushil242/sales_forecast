/**
 * The plain-English lead for the social page.
 *
 * Same hierarchy as the forecast page's OwnerBrief, for the same reason: an owner
 * deciding what to buy needs a sentence, not a sentiment score between -1 and +1.
 * The evidence line is deliberately part of the hero rather than a footnote —
 * social evidence is often thin, and how much of it there is changes what the
 * headline is worth.
 */

import { Callout, Icon } from './ui'

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
           'checked against the harvested data before this was shown.',
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

export default function SocialBrief({ envelope }) {
  if (!envelope?.brief) return null

  const { brief, source, guard_flags: flags = [] } = envelope
  const badge = SOURCE[source] ?? SOURCE.none

  return (
    <div className="space-y-4">
      <div className="rounded-xl text-white p-6 sm:p-8" style={{ backgroundColor: '#0B1F3A' }}>
        <div className="flex items-start justify-between gap-4 mb-3">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-teal-300">
            What people are saying
          </span>
          <span className={`badge shrink-0 ${badge.className}`} title={badge.title}>
            {badge.label}
          </span>
        </div>

        <h2 className="font-display text-xl sm:text-2xl font-bold leading-snug">
          {brief.headline}
        </h2>

        {brief.summary && (
          <p className="mt-3 text-slate-300 leading-relaxed max-w-3xl">{brief.summary}</p>
        )}

        {brief.evidence_note && (
          <div className="mt-5 pt-4 border-t border-white/10 flex gap-2.5">
            <Icon.Shield className="w-4 h-4 mt-0.5 shrink-0 text-teal-300" />
            <p className="text-sm text-slate-300 leading-relaxed">{brief.evidence_note}</p>
          </div>
        )}
      </div>

      {flags.length > 0 && (
        <Callout tone="amber" title="The AI-written brief was discarded">
          It referenced {flags.length} figure{flags.length > 1 ? 's' : ''} that were not in
          the harvested data ({flags.join(', ')}), so the computed brief is shown instead.
        </Callout>
      )}

      {(brief.actions?.length > 0 || brief.findings?.length > 0) && (
        <div className="grid lg:grid-cols-2 gap-4">
          {brief.actions?.length > 0 && (
            <div className="card p-6">
              <h3 className="section-title mb-4">What to do</h3>
              <ol className="space-y-3">
                {brief.actions.map((action, index) => {
                  const toneStyle = SEVERITY[action.urgency] ?? SEVERITY.info
                  return (
                    <li key={action.text} className="flex gap-3">
                      <span
                        className={`shrink-0 w-6 h-6 rounded-full text-xs font-semibold
                                    flex items-center justify-center ${toneStyle.chip}`}
                      >
                        {index + 1}
                      </span>
                      <p className={`text-sm leading-relaxed ${toneStyle.text}`}>
                        {action.text}
                      </p>
                    </li>
                  )
                })}
              </ol>
            </div>
          )}

          {brief.findings?.length > 0 && (
            <div className="card p-6">
              <h3 className="section-title mb-4">Worth knowing</h3>
              <ul className="space-y-2.5">
                {brief.findings.map((finding) => {
                  const toneStyle = SEVERITY[finding.severity] ?? SEVERITY.info
                  return (
                    <li key={finding.text} className="flex gap-3">
                      <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${toneStyle.dot}`} />
                      <p className={`text-sm leading-relaxed ${toneStyle.text}`}>
                        {finding.text}
                      </p>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
