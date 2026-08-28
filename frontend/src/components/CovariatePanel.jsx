/**
 * What external signals were tested, and which survived the test.
 *
 * The point this panel makes is the one that distinguishes the product: we do not
 * assume weather or holidays help. We measure each on rolling windows of the user's
 * own series and attach only the ones that reduce error. On the bundled dataset that
 * means holidays are kept and calendar features are dropped — and the panel shows
 * both outcomes rather than quietly hiding the rejects.
 */

import { Callout, Icon } from './ui'
import { signedPct } from '../lib/format'

const GROUP_META = {
  holiday: { label: 'Holidays & festivals', icon: Icon.Calendar, blurb: 'Diwali, Christmas, Eid and state holidays' },
  weather: { label: 'Local weather', icon: Icon.Activity, blurb: 'Temperature, rainfall and wind' },
  calendar: { label: 'Day & payday patterns', icon: Icon.Star, blurb: 'Weekday, month-end and salary cycle' },
  sentiment: { label: 'Social sentiment', icon: Icon.Share, blurb: 'What people are posting about this product' },
}

const METHOD_NOTE = {
  measured: 'Measured on your own sales history.',
  cached: 'Measured earlier on this series; the result is reused.',
  skipped: 'Not enough history to measure, so nothing was assumed.',
  unavailable: 'No external signal could be attached.',
  disabled: 'External signals were switched off for this run.',
}

export default function CovariatePanel({ covariates }) {
  if (!covariates) return null

  const { scores = [], selected_groups: selected = [], method, location, windows } = covariates
  const hasScores = scores.length > 0

  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="section-title">External signals</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {METHOD_NOTE[method] ?? METHOD_NOTE.unavailable}
            {windows ? ` Tested over ${windows} rolling windows.` : ''}
            {location ? ` Location: ${location}.` : ''}
          </p>
        </div>
        {selected.length > 0 ? (
          <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
            {selected.length} of {scores.length} kept
          </span>
        ) : hasScores ? (
          <span className="badge bg-slate-100 text-slate-600 ring-1 ring-slate-200">
            none improved accuracy
          </span>
        ) : null}
      </div>

      {hasScores ? (
        <div className="mt-5 space-y-2">
          {scores.map((score) => {
            const meta = GROUP_META[score.group] ?? {
              label: score.group, icon: Icon.Info, blurb: '',
            }
            const IconComp = meta.icon
            return (
              <div
                key={score.group}
                className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 ${
                  score.helps
                    ? 'border-emerald-200 bg-emerald-50/50'
                    : 'border-slate-200 bg-slate-50/60'
                }`}
              >
                <span
                  className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
                    score.helps ? 'bg-emerald-500 text-white' : 'bg-slate-200 text-slate-500'
                  }`}
                >
                  <IconComp className="w-4 h-4" />
                </span>

                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-800">{meta.label}</p>
                  <p className="text-xs text-slate-500 truncate">{meta.blurb}</p>
                </div>

                <div className="text-right shrink-0">
                  <p
                    className={`text-sm font-semibold tabular-nums ${
                      score.helps ? 'text-emerald-700' : 'text-slate-400'
                    }`}
                  >
                    {signedPct(score.delta_pct, 2)}
                  </p>
                  <p className="text-[11px] text-slate-400">
                    {score.helps ? 'kept' : 'left out'}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-sm text-slate-500 mt-4">{covariates.note}</p>
      )}

      {hasScores && (
        <p className="text-xs text-slate-500 mt-4 leading-relaxed">{covariates.note}</p>
      )}

      {covariates.warnings?.map((warning) => (
        <div key={warning} className="mt-3">
          <Callout tone="slate" icon={Icon.Info}>{warning}</Callout>
        </div>
      ))}
    </div>
  )
}
