/**
 * Chart components.
 *
 * Two conventions applied throughout:
 *  - History is a solid line, forecast is dashed. The visual break marks exactly
 *    where measurement ends and prediction begins.
 *  - Confidence bands are drawn as a stacked area (lower band transparent, span
 *    on top), which is the standard Recharts idiom for a floating ribbon.
 */

import { useMemo } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend,
  Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { num, shortDate } from '../lib/format'

const AXIS = { stroke: '#94a3b8', fontSize: 11 }
const GRID = { stroke: '#e2e8f0', strokeDasharray: '3 3', vertical: false }

function TooltipShell({ label, children }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-card-md px-3 py-2 text-xs">
      <p className="font-semibold text-slate-900 mb-1.5">{label}</p>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ colour, label, value }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: colour }} />
      <span className="text-slate-500">{label}</span>
      <span className="ml-auto font-medium text-slate-900 tabular-nums">{value}</span>
    </div>
  )
}

/** Historical actuals joined to the forecast, with the 80% band behind it. */
export function ForecastTrendChart({ history, forecast, height = 320 }) {
  // Legend lines for history vs forecast are distinguished by dash pattern below.
  const data = useMemo(() => {
    const rows = history.map((point) => ({
      date: point.date,
      actual: point.units,
    }))

    // Repeat the final actual as the forecast's first point so the two lines
    // meet instead of leaving a visual gap at the boundary.
    const last = history.at(-1)
    if (last) {
      rows[rows.length - 1] = { ...rows[rows.length - 1], predicted: last.units }
    }

    forecast.forEach((point) => {
      rows.push({
        date: point.date,
        predicted: point.predicted_units,
        bandBase: point.lower_80,
        bandSpan: Math.max(0, point.upper_80 - point.lower_80),
        lower80: point.lower_80,
        upper80: point.upper_80,
      })
    })
    return rows
  }, [history, forecast])

  const boundary = forecast.length ? history.at(-1)?.date : null

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" tickFormatter={shortDate} {...AXIS} minTickGap={44} tickLine={false} />
        <YAxis {...AXIS} tickLine={false} axisLine={false} width={52} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={shortDate(label)}>
                {row.actual !== undefined && (
                  <Row colour="#4f46e5" label="Actual" value={num(row.actual, 1)} />
                )}
                {row.predicted !== undefined && (
                  <Row colour="#0891b2" label="Forecast" value={num(row.predicted, 1)} />
                )}
                {row.lower80 !== undefined && (
                  <Row
                    colour="#a5f3fc"
                    label="80% interval"
                    value={`${num(row.lower80, 1)} - ${num(row.upper80, 1)}`}
                  />
                )}
              </TooltipShell>
            )
          }}
        />
        {/* The legend payload is declared explicitly rather than inferred from the
            series. The stacked-area trick needs a transparent `bandBase` series to
            lift the ribbon to the lower bound, and Recharts would otherwise list
            that internal series as though it were data. */}
        <Legend
          verticalAlign="top" align="right" height={28} iconType="plainline"
          wrapperStyle={{ fontSize: 12 }}
          // Recharts tints legend text with the swatch colour, which makes the
          // pale interval swatch unreadable. Force a consistent label colour.
          formatter={(value) => <span style={{ color: '#475569' }}>{value}</span>}
          payload={[
            { value: 'Historical', type: 'plainline', color: '#4f46e5', payload: { strokeDasharray: '0' } },
            { value: 'Forecast', type: 'plainline', color: '#0891b2', payload: { strokeDasharray: '5 4' } },
            { value: '80% interval', type: 'rect', color: '#a5f3fc' },
          ]}
        />

        {/* Transparent base lifts the visible span to the lower bound. */}
        <Area dataKey="bandBase" stackId="band" stroke="none" fill="none" legendType="none" isAnimationActive={false} />
        <Area
          dataKey="bandSpan" stackId="band" stroke="none" fill="#06b6d4" fillOpacity={0.14}
          name="80% interval" legendType="none" isAnimationActive={false}
        />

        {boundary && <ReferenceLine x={boundary} stroke="#cbd5e1" strokeDasharray="4 4" />}

        <Line
          dataKey="actual" name="Historical" stroke="#4f46e5" strokeWidth={1.8}
          dot={false} connectNulls={false} isAnimationActive={false} legendType="none"
        />
        <Line
          dataKey="predicted" name="Forecast" stroke="#0891b2" strokeWidth={2}
          strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} legendType="none"
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Forecast horizon alone, so the interval funnel is legible at full width. */
export function ConfidenceBandChart({ forecast, height = 260 }) {
  const data = useMemo(
    () =>
      forecast.map((point) => ({
        date: point.date,
        predicted: point.predicted_units,
        bandBase: point.lower_80,
        bandSpan: Math.max(0, point.upper_80 - point.lower_80),
        lower80: point.lower_80,
        upper80: point.upper_80,
      })),
    [forecast],
  )

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" tickFormatter={shortDate} {...AXIS} minTickGap={40} tickLine={false} />
        <YAxis {...AXIS} tickLine={false} axisLine={false} width={52} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={shortDate(label)}>
                <Row colour="#4f46e5" label="Forecast" value={num(row.predicted, 1)} />
                <Row colour="#c7d2fe" label="Lower 80%" value={num(row.lower80, 1)} />
                <Row colour="#c7d2fe" label="Upper 80%" value={num(row.upper80, 1)} />
              </TooltipShell>
            )
          }}
        />
        <Area dataKey="bandBase" stackId="b" stroke="none" fill="none" isAnimationActive={false} />
        <Area dataKey="bandSpan" stackId="b" stroke="none" fill="#6366f1" fillOpacity={0.16} isAnimationActive={false} />
        <Area
          dataKey="predicted" stroke="#4f46e5" strokeWidth={2} fill="none"
          dot={false} isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Measured mean units per weekday. The tallest bar is highlighted. */
export function WeekdayProfileChart({ profile, height = 180 }) {
  if (!profile?.length) return null
  const peak = Math.max(...profile.map((row) => row.mean_units))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={profile} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="weekday" {...AXIS} tickLine={false} axisLine={false} />
        <YAxis {...AXIS} tickLine={false} axisLine={false} width={44} />
        <Tooltip
          cursor={{ fill: '#f1f5f9' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={row.weekday}>
                <Row colour="#4f46e5" label="Mean units" value={num(row.mean_units, 1)} />
                <Row colour="#94a3b8" label="vs average" value={`${row.index.toFixed(2)}x`} />
              </TooltipShell>
            )
          }}
        />
        <Bar dataKey="mean_units" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {profile.map((row) => (
            <Cell key={row.weekday} fill={row.mean_units === peak ? '#4f46e5' : '#c7d2fe'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * Daily sentiment index with document volume behind it.
 *
 * Both series are shown together deliberately: a sentiment reading of 0.0 on a
 * day with no documents means "nothing was said", not "opinion was neutral",
 * and only the volume bars distinguish the two.
 */
export function SentimentTimelineChart({ timeline, height = 260 }) {
  const maxDocuments = Math.max(1, ...timeline.map((point) => point.document_count))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={timeline} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" tickFormatter={shortDate} {...AXIS} minTickGap={40} tickLine={false} />
        <YAxis
          yAxisId="sentiment" domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
          {...AXIS} tickLine={false} axisLine={false} width={44}
        />
        <YAxis yAxisId="volume" orientation="right" domain={[0, maxDocuments * 3]} hide />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={shortDate(label)}>
                <Row colour="#94a3b8" label="Documents" value={num(row.document_count)} />
                <Row
                  colour="#4f46e5"
                  label="Sentiment"
                  value={row.document_count ? row.sentiment_index.toFixed(3) : 'no data'}
                />
              </TooltipShell>
            )
          }}
        />
        <ReferenceLine yAxisId="sentiment" y={0} stroke="#cbd5e1" />
        <Bar
          yAxisId="volume" dataKey="document_count" fill="#e2e8f0"
          radius={[3, 3, 0, 0]} isAnimationActive={false} name="Documents"
        />
        <Line
          yAxisId="sentiment" dataKey="sentiment_index" stroke="#4f46e5" strokeWidth={2}
          dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} name="Sentiment index"
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Horizontal bars comparing model error. Lower is better, so the best is highlighted. */
export function ModelComparisonChart({ metrics, bestModel, metric = 'mase', height = 190 }) {
  const data = Object.entries(metrics)
    .map(([name, values]) => ({ name, value: values[metric] }))
    .filter((row) => row.value !== null && row.value !== undefined)
    .sort((a, b) => a.value - b.value)

  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 44, bottom: 0, left: 4 }}>
        <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" {...AXIS} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" {...AXIS} width={104} tickLine={false} axisLine={false} />
        <Tooltip
          cursor={{ fill: '#f8fafc' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            return (
              <TooltipShell label={payload[0].payload.name}>
                <Row colour="#4f46e5" label={metric.toUpperCase()} value={payload[0].value.toFixed(3)} />
              </TooltipShell>
            )
          }}
        />
        {metric === 'mase' && <ReferenceLine x={1} stroke="#f43f5e" strokeDasharray="4 4" />}
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {data.map((row) => (
            <Cell key={row.name} fill={row.name === bestModel ? '#4f46e5' : '#cbd5e1'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
