import { useMemo, useState } from 'react'
import { AreaChart, Area, LineChart, Line, BarChart, Bar, ComposedChart,
         XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
         ReferenceLine, Legend } from 'recharts'
import { Icon } from './ui'
import { AnimatedNumber, Reveal } from './motion'
import { Segmented } from './controls'
import { num, pct, signedPct, shortDate, longDate } from '../lib/format'

export default function ForecastWorkspace({
  result,
  view,
  onViewChange,
  historyWindow,
  onHistoryWindowChange,
  onOpenSocial
}) {
  const [activeTab, setActiveTab] = useState('Overview')

  const {
    product_name,
    selection,
    dataset_name,
    horizon_days,
    run_id,
    model_info,
    history,
    forecast,
    data_quality,
    backtest,
    covariates,
    insights,
    fusion,
    timings_ms
  } = result

  // --- Derived Metrics ---
  const { totalForecast, avgForecastDay, recentVsForecastPct, mase, coverage, historyDepth } = useMemo(() => {
    let total = 0
    forecast.forEach(f => {
      total += f.predicted_units
    })
    const avg = horizon_days > 0 ? total / horizon_days : 0

    let recentAvg = 0
    let recentPct = 0
    if (history.length > 0) {
      const recentDays = Math.min(30, history.length)
      const recentHist = history.slice(-recentDays)
      const recentTotal = recentHist.reduce((acc, h) => acc + h.units, 0)
      recentAvg = recentTotal / recentDays
      recentPct = recentAvg > 0 ? (avg - recentAvg) / recentAvg : 0
    }

    let bMase = null
    let bCov = null
    if (backtest?.best_model && backtest.metrics_by_model[backtest.best_model]) {
      const bMetrics = backtest.metrics_by_model[backtest.best_model]
      bMase = bMetrics.mase
      bCov = bMetrics.coverage_80
    }

    return {
      totalForecast: total,
      avgForecastDay: avg,
      recentVsForecastPct: recentPct,
      mase: bMase,
      coverage: bCov,
      historyDepth: data_quality.observations
    }
  }, [forecast, horizon_days, history, backtest, data_quality])

  // --- Chart Data Formatting ---
  const chartData = useMemo(() => {
    let filteredHistory = history
    if (historyWindow === '90d') filteredHistory = history.slice(-90)
    else if (historyWindow === '180d') filteredHistory = history.slice(-180)
    else if (historyWindow === '1y') filteredHistory = history.slice(-365)

    const mappedHist = filteredHistory.map(h => ({
      date: h.date,
      historical: h.units,
      predicted: null,
      lower_80: null,
      upper_80: null
    }))
    const mappedFore = forecast.map(f => ({
      date: f.date,
      historical: null,
      predicted: f.predicted_units,
      lower_80: f.lower_80,
      upper_80: f.upper_80,
      band: [f.lower_80, f.upper_80]
    }))

    // Connect the lines
    if (mappedHist.length > 0 && mappedFore.length > 0) {
      const lastHist = mappedHist[mappedHist.length - 1]
      mappedFore[0].historical = lastHist.historical
      mappedFore[0].predicted = lastHist.historical // connect predicted to last historical
      mappedFore[0].band = [lastHist.historical, lastHist.historical]
    }

    return [...mappedHist, ...mappedFore]
  }, [history, forecast, historyWindow])

  const bModelsData = useMemo(() => {
    if (!backtest) return []
    return Object.entries(backtest.metrics_by_model)
      .map(([model, metrics]) => ({ model, mase: metrics.mase }))
      .sort((a, b) => a.mase - b.mase)
  }, [backtest])

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload
      return (
        <div className="bg-white border border-slate-200 shadow-lg rounded-md p-3 text-sm">
          <div className="font-medium text-slate-700 mb-2">{shortDate(label)}</div>
          {data.historical !== null && (
            <div className="flex justify-between gap-4 mb-1">
              <span className="text-slate-500">Actual</span>
              <span className="font-semibold tabular-nums">{num(data.historical)}</span>
            </div>
          )}
          {data.predicted !== null && data.predicted !== data.historical && (
            <div className="flex justify-between gap-4 mb-1">
              <span className="text-blue-600 font-medium">Forecast</span>
              <span className="font-semibold tabular-nums text-blue-700">{num(data.predicted)}</span>
            </div>
          )}
          {data.lower_80 !== null && data.upper_80 !== null && (
            <div className="flex justify-between gap-4 text-xs text-slate-400 mt-2">
              <span>80% PI</span>
              <span className="tabular-nums">[{num(data.lower_80)} - {num(data.upper_80)}]</span>
            </div>
          )}
        </div>
      )
    }
    return null
  }

  return (
    <div className="flex flex-col h-full bg-slate-50 overflow-hidden text-slate-800">
      {/* 1. HEADER STRIP */}
      <header className="flex-none bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
        <div className="flex items-center gap-4">
          <div className="flex flex-col">
            <div className="flex items-center gap-2 mb-1">
              <h1 className="text-xl font-semibold tracking-tight text-slate-900 leading-none">
                {product_name}
              </h1>
              <span className="badge bg-slate-100 text-slate-600 text-xs px-2 py-0.5 rounded-full capitalize border border-slate-200">
                {selection.kind}
              </span>
              {model_info.fell_back_from && (
                <span className="badge bg-amber-50 text-amber-700 text-xs px-2 py-0.5 rounded-full border border-amber-200 flex items-center gap-1">
                  <Icon.Warning className="w-3 h-3" />
                  Fallback
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1"><Icon.Database className="w-3.5 h-3.5" /> {dataset_name}</span>
              <span className="text-slate-300">•</span>
              <span className="flex items-center gap-1"><Icon.Activity className="w-3.5 h-3.5" /> {timings_ms.total}ms run</span>
              <span className="text-slate-300">•</span>
              <span className="flex items-center gap-1 text-blue-600 font-medium"><Icon.Sparkles className="w-3.5 h-3.5" /> {model_info.name}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <Segmented
            value={view}
            onChange={onViewChange}
            size="sm"
            options={[
              { value: 'owner', label: 'Owner View' },
              { value: 'analyst', label: 'Analyst View' }
            ]}
          />
          <button 
            onClick={onOpenSocial}
            className="btn-secondary text-sm px-3 py-1.5 flex items-center gap-1.5 bg-white border border-slate-200 hover:bg-slate-50 rounded-md font-medium text-slate-700 transition-colors shadow-sm"
          >
            <Icon.Share className="w-4 h-4" />
            Social signals
          </button>
        </div>
      </header>

      {/* 2. METRIC STRIP */}
      <div className="flex-none bg-white border-b border-slate-200 px-6 py-4">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="flex flex-col">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Forecast Total</span>
            <div className="flex items-baseline gap-2">
              <span className="stat-value text-2xl font-semibold tabular-nums text-slate-900">
                <AnimatedNumber value={totalForecast} format={num} />
              </span>
            </div>
            <span className="text-xs text-slate-400 mt-1">Next {horizon_days} days</span>
          </div>
          
          <div className="flex flex-col">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Avg / Day</span>
            <div className="flex items-baseline gap-2">
              <span className="stat-value text-2xl font-semibold tabular-nums text-slate-900">
                <AnimatedNumber value={avgForecastDay} format={num} />
              </span>
            </div>
            <span className="text-xs text-slate-400 mt-1">Expected daily run-rate</span>
          </div>

          <div className="flex flex-col border-l border-slate-100 pl-4">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">vs Recent 30d</span>
            <div className="flex items-baseline gap-2">
              <span className={`stat-value text-2xl font-semibold tabular-nums ${recentVsForecastPct > 0 ? 'text-emerald-600' : recentVsForecastPct < 0 ? 'text-rose-600' : 'text-slate-900'}`}>
                {signedPct(recentVsForecastPct)}
              </span>
              {recentVsForecastPct !== 0 && (
                recentVsForecastPct > 0 ? <Icon.TrendUp className="w-4 h-4 text-emerald-600" /> : <Icon.TrendDown className="w-4 h-4 text-rose-600" />
              )}
            </div>
            <span className="text-xs text-slate-400 mt-1">Trend trajectory</span>
          </div>

          <div className="flex flex-col border-l border-slate-100 pl-4">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">Accuracy (MASE)</span>
            <div className="flex items-baseline gap-2">
              <span className="stat-value text-2xl font-semibold tabular-nums text-slate-900">
                {mase !== null ? num(mase, 2) : '—'}
              </span>
              {backtest?.improvement_over_naive_pct > 0 && (
                <span className="badge bg-emerald-50 text-emerald-700 text-[10px] px-1.5 py-0.5 rounded font-medium">
                  +{num(backtest.improvement_over_naive_pct, 1)}%
                </span>
              )}
            </div>
            <span className="text-xs text-slate-400 mt-1">Best model backtest</span>
          </div>

          <div className="flex flex-col border-l border-slate-100 pl-4">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">80% Interval Cov.</span>
            <div className="flex items-baseline gap-2">
              <span className="stat-value text-2xl font-semibold tabular-nums text-slate-900">
                {coverage !== null ? pct(coverage) : '—'}
              </span>
            </div>
            <span className="text-xs text-slate-400 mt-1">Target ~80%</span>
          </div>

          <div className="flex flex-col border-l border-slate-100 pl-4">
            <span className="eyebrow text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1">History Depth</span>
            <div className="flex items-baseline gap-2">
              <span className="stat-value text-2xl font-semibold tabular-nums text-slate-900">
                {num(historyDepth)}
              </span>
              <span className="text-sm font-medium text-slate-500">days</span>
            </div>
            <span className="flex items-center gap-1 text-xs text-slate-400 mt-1">
              <Icon.Check className="w-3 h-3 text-emerald-500" />
              {data_quality.level} quality
            </span>
          </div>
        </div>
      </div>

      {/* 3. TAB BAR */}
      <div className="flex-none px-6 pt-4 bg-white border-b border-slate-200">
        <div className="flex gap-6 text-sm font-medium">
          {['Overview', 'Accuracy', 'Drivers', 'Data'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-3 relative transition-colors ${activeTab === tab ? 'text-blue-600' : 'text-slate-500 hover:text-slate-800'}`}
            >
              {tab}
              {activeTab === tab && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 overflow-auto p-6">
        <Reveal>
          {/* 4. OVERVIEW TAB */}
          {activeTab === 'Overview' && (
            <div className="flex flex-col gap-6">
              <div className="flex flex-col min-w-0 bg-white border border-slate-200 rounded-lg shadow-sm">
                <div className="flex items-center justify-between p-4 border-b border-slate-100">
                  <h3 className="section-title text-base font-semibold text-slate-800">Forecast Horizon</h3>
                  <Segmented
                    value={historyWindow}
                    onChange={onHistoryWindowChange}
                    size="sm"
                    options={[
                      { value: '90d', label: '90D' },
                      { value: '180d', label: '180D' },
                      { value: '1y', label: '1Y' },
                      { value: 'all', label: 'All' }
                    ]}
                  />
                </div>
                <div className="flex-1 p-4">
                  <ResponsiveContainer width="100%" height={400}>
                    <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis 
                        dataKey="date" 
                        tickFormatter={shortDate}
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        axisLine={false}
                        tickLine={false}
                        minTickGap={30}
                      />
                      <YAxis 
                        tickFormatter={(v) => num(v)}
                        tick={{ fontSize: 11, fill: '#64748b' }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip content={<CustomTooltip />} />
                      <Legend verticalAlign="top" height={36} iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                      
                      <Area isAnimationActive={false} 
                        type="monotone" 
                        dataKey="band" 
                        stroke="none" 
                        fill="#bfdbfe" 
                        fillOpacity={0.4} 
                        name="80% Prediction Interval" 
                      />
                      <Line isAnimationActive={false} 
                        type="monotone" 
                        dataKey="historical" 
                        stroke="#64748b" 
                        strokeWidth={2} 
                        dot={false} 
                        name="Historical" 
                      />
                      <Line isAnimationActive={false} 
                        type="monotone" 
                        dataKey="predicted" 
                        stroke="#2563eb" 
                        strokeWidth={2.5} 
                        dot={false} 
                        name="Forecast" 
                      />
                      {chartData.some(d => d.historical !== null && d.predicted !== null) && (
                        <ReferenceLine x={chartData.find(d => d.historical !== null && d.predicted !== null)?.date} stroke="#94a3b8" strokeDasharray="3 3" />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="space-y-6">
                <div className="card bg-white border border-slate-200 rounded-lg shadow-sm p-4 w-full">
                  <h3 className="section-title text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
                    <Icon.BarChart className="w-4 h-4 text-slate-400" />
                    Weekly Profile
                  </h3>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={insights.weekday_profile} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                        <XAxis 
                          dataKey="weekday" 
                          tick={{ fontSize: 10, fill: '#64748b' }}
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={(v) => v.slice(0, 3)}
                        />
                        <YAxis tick={false} axisLine={false} tickLine={false} />
                        <Tooltip
                          cursor={{ fill: '#f8fafc' }}
                          content={({ active, payload }) => {
                            if (active && payload && payload.length) {
                              return (
                                <div className="bg-slate-800 text-white text-xs py-1 px-2 rounded shadow-sm">
                                  {payload[0].payload.weekday}: Avg {num(payload[0].value)} units
                                </div>
                              )
                            }
                            return null
                          }}
                        />
                        <Bar isAnimationActive={false} dataKey="mean_units" fill="#94a3b8" radius={[2, 2, 0, 0]}>
                          {insights.weekday_profile.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.index > 1.1 ? '#3b82f6' : entry.index < 0.9 ? '#cbd5e1' : '#94a3b8'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="card bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden w-full">
                  <div className="p-4 border-b border-slate-100 bg-slate-50/50">
                    <h3 className="section-title text-sm font-semibold text-slate-800 flex items-center gap-2">
                      <Icon.Star className="w-4 h-4 text-amber-500" />
                      Key Insights
                    </h3>
                  </div>
                  <div className="p-4 divide-y divide-slate-100">
                    {insights.cards.map(card => (
                      <div key={card.key} className="flex gap-3 items-start py-3 first:pt-0">
                        <div className={`mt-1 rounded-full p-1 shrink-0 ${card.trend === 'up' ? 'bg-emerald-100 text-emerald-600' : card.trend === 'down' ? 'bg-rose-100 text-rose-600' : 'bg-slate-100 text-slate-600'}`}>
                          {card.trend === 'up' ? <Icon.TrendUp className="w-3.5 h-3.5" /> : card.trend === 'down' ? <Icon.TrendDown className="w-3.5 h-3.5" /> : <Icon.Minus className="w-3.5 h-3.5" />}
                        </div>
                        {/* Full width now, so the label/value sit on the left and the
                            explanation runs alongside instead of wrapping under it. */}
                        <div className="flex-1 min-w-0 sm:flex sm:items-baseline sm:gap-6">
                          <div className="sm:w-64 sm:shrink-0">
                            <div className="text-[13px] font-medium text-slate-900">{card.label}</div>
                            <div className="text-lg font-semibold tabular-nums tracking-tight text-slate-800">{card.value}</div>
                          </div>
                          <div className="text-xs text-slate-500 leading-relaxed flex-1 min-w-0">{card.detail}</div>
                        </div>
                      </div>
                    ))}
                    {insights.recommendations.length > 0 && (
                      <ul className="text-[13px] text-slate-600 space-y-3 pt-4">
                        {insights.recommendations.map((rec, i) => (
                          <li key={i} className="flex items-start gap-3">
                            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                            <span className="leading-relaxed">{rec}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 5. ACCURACY TAB */}
          {activeTab === 'Accuracy' && (
            <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-6 h-full min-h-[500px]">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Backtest Model Evaluation</h2>
                  <p className="text-sm text-slate-500 mt-1">Tested on a hold-out window of {backtest?.horizon || '-'} days</p>
                </div>
                {backtest?.improvement_over_naive_pct !== null && (
                  <div className="bg-emerald-50 border border-emerald-100 px-4 py-2 rounded-lg text-emerald-800 flex items-center gap-3">
                    <div className="p-1.5 bg-white rounded-md shadow-sm text-emerald-600">
                      <Icon.Activity className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="text-[11px] uppercase tracking-wider font-semibold opacity-70">Improvement</div>
                      <div className="font-bold tabular-nums">+{num(backtest.improvement_over_naive_pct, 1)}% vs Naive</div>
                    </div>
                  </div>
                )}
              </div>

              {!backtest ? (
                <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed border-slate-200 rounded-lg bg-slate-50">
                  <Icon.Info className="w-8 h-8 text-slate-400 mb-3" />
                  <h3 className="font-medium text-slate-900">Not enough history for backtesting</h3>
                  <p className="text-sm text-slate-500 mt-1 max-w-sm">
                    The series is too short to carve out a hold-out window without degrading the forecast model. Accuracy metrics are unavailable.
                  </p>
                </div>
              ) : (
                <div className="flex flex-col lg:flex-row gap-8">
                  <div className="flex-1 overflow-x-auto">
                    <table className="w-full text-sm text-left">
                      <thead>
                        <tr className="border-b border-slate-200 text-slate-500 bg-slate-50/50">
                          <th className="font-medium py-3 px-4 rounded-tl-md">Model</th>
                          <th className="font-medium py-3 px-4 text-right">MASE</th>
                          <th className="font-medium py-3 px-4 text-right">RMSE</th>
                          <th className="font-medium py-3 px-4 text-right">sMAPE</th>
                          <th className="font-medium py-3 px-4 text-right">MAE</th>
                          <th className="font-medium py-3 px-4 text-right rounded-tr-md">80% Cov</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {Object.entries(backtest.metrics_by_model)
                          .sort(([, a], [, b]) => a.mase - b.mase)
                          .map(([mName, m]) => {
                            const isBest = mName === backtest.best_model
                            return (
                              <tr key={mName} className={`transition-colors hover:bg-slate-50/80 ${isBest ? 'bg-blue-50/30' : ''}`}>
                                <td className="py-3 px-4 font-medium text-slate-800 flex items-center gap-2">
                                  {mName}
                                  {isBest && (
                                    <span className="badge bg-blue-100 text-blue-700 text-[10px] px-1.5 py-0.5 rounded uppercase font-bold tracking-wide">Best</span>
                                  )}
                                </td>
                                <td className={`py-3 px-4 tabular-nums text-right ${isBest ? 'font-semibold text-blue-700' : 'text-slate-600'}`}>{num(m.mase, 3)}</td>
                                <td className="py-3 px-4 tabular-nums text-right text-slate-600">{num(m.rmse, 1)}</td>
                                <td className="py-3 px-4 tabular-nums text-right text-slate-600">{pct(m.smape, 1)}</td>
                                <td className="py-3 px-4 tabular-nums text-right text-slate-600">{num(m.mae, 1)}</td>
                                <td className="py-3 px-4 tabular-nums text-right text-slate-600">
                                  <span className={Math.abs(m.coverage_80 - 0.8) > 0.1 ? 'text-amber-600' : ''}>
                                    {pct(m.coverage_80, 1)}
                                  </span>
                                </td>
                              </tr>
                            )
                          })}
                      </tbody>
                    </table>
                    {backtest.note && (
                      <p className="text-xs text-slate-500 mt-4 flex gap-1.5">
                        <Icon.Info className="w-4 h-4 text-slate-400 shrink-0" />
                        {backtest.note}
                      </p>
                    )}
                  </div>
                  
                  <div className="w-full lg:w-80 flex flex-col gap-4">
                    <h4 className="text-sm font-semibold text-slate-700 mb-2">MASE Comparison</h4>
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart layout="vertical" data={bModelsData} margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                          <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                          <YAxis 
                            dataKey="model" 
                            type="category" 
                            tick={{ fontSize: 11, fill: '#475569' }} 
                            axisLine={false} 
                            tickLine={false} 
                            width={100}
                          />
                          <Tooltip 
                            cursor={{ fill: '#f8fafc' }}
                            formatter={(value) => [num(value, 3), 'MASE']}
                            contentStyle={{ fontSize: '12px', borderRadius: '6px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                          />
                          <Bar isAnimationActive={false} dataKey="mase" radius={[0, 4, 4, 0]} barSize={20}>
                            {bModelsData.map((entry, index) => (
                              <Cell key={`cell-${index}`} fill={entry.model === backtest.best_model ? '#3b82f6' : '#cbd5e1'} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="text-[11px] text-slate-500 text-center">Lower is better</div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 6. DRIVERS TAB */}
          {activeTab === 'Drivers' && (
            <div className="flex flex-col lg:flex-row gap-6 h-full min-h-[500px]">
              <div className="flex-1 bg-white border border-slate-200 rounded-lg shadow-sm p-6 flex flex-col">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                      <Icon.Layers className="w-5 h-5 text-blue-500" />
                      External Signal Evaluation
                    </h2>
                    <p className="text-sm text-slate-500 mt-1">Signals are evaluated specifically on this series. Only those improving cross-validated error are retained.</p>
                  </div>
                  <div className="text-right">
                    <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Selection Impact</div>
                    <div className={`text-xl font-bold tabular-nums ${covariates.improvement_pct > 0 ? 'text-emerald-600' : 'text-slate-700'}`}>
                      {covariates.improvement_pct > 0 ? `+${num(covariates.improvement_pct, 1)}%` : 'No impact'}
                    </div>
                  </div>
                </div>

                {!covariates.enabled ? (
                   <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
                     <Icon.Plug className="w-8 h-8 text-slate-300 mb-2" />
                     <p>Covariate processing is disabled for this run.</p>
                   </div>
                ) : covariates.scores.length === 0 ? (
                  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
                     <Icon.Search className="w-8 h-8 text-slate-300 mb-2" />
                     <p>No eligible covariate groups available for evaluation.</p>
                   </div>
                ) : (
                  <div className="space-y-4">
                    {covariates.scores.map(score => {
                      const maxAbsDelta = Math.max(...covariates.scores.map(s => Math.abs(s.delta_pct)), 1)
                      const barPct = Math.min((Math.abs(score.delta_pct) / maxAbsDelta) * 100, 100)
                      
                      return (
                        <div key={score.group} className="border border-slate-100 rounded-lg p-4 bg-slate-50/30">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-slate-800">{score.group}</span>
                              {score.helps ? (
                                <span className="badge bg-emerald-50 text-emerald-700 border border-emerald-100 text-[10px] px-1.5 py-0.5 rounded font-medium flex items-center gap-1">
                                  <Icon.Check className="w-3 h-3" /> Kept
                                </span>
                              ) : (
                                <span className="badge bg-slate-100 text-slate-500 border border-slate-200 text-[10px] px-1.5 py-0.5 rounded font-medium flex items-center gap-1">
                                  <Icon.Minus className="w-3 h-3" /> Dropped
                                </span>
                              )}
                            </div>
                            <div className={`font-semibold tabular-nums text-sm ${score.delta_pct > 0 ? 'text-emerald-600' : score.delta_pct < 0 ? 'text-rose-600' : 'text-slate-600'}`}>
                              {score.delta_pct > 0 ? '+' : ''}{num(score.delta_pct, 2)}%
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-4 text-sm text-slate-500 mb-3">
                            <span className="w-16 tabular-nums">{num(score.mase, 3)} MASE</span>
                            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden flex">
                              {score.delta_pct > 0 ? (
                                <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${barPct}%` }} />
                              ) : (
                                <div className="h-full bg-rose-400 rounded-full ml-auto" style={{ width: `${barPct}%` }} />
                              )}
                            </div>
                          </div>
                          <div className="text-xs text-slate-400 flex items-start gap-1.5 bg-white p-2 rounded border border-slate-100">
                            <Icon.Info className="w-3.5 h-3.5 mt-px shrink-0" />
                            {score.reason}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
                {covariates.warnings?.length > 0 && (
                  <div className="mt-6 bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
                    <div className="font-semibold flex items-center gap-2 mb-1"><Icon.Warning className="w-4 h-4" /> Signal Warnings</div>
                    <ul className="list-disc pl-5 space-y-1">
                      {covariates.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}
              </div>

              {fusion.applied && (
                <div className="w-full lg:w-80 bg-white border border-slate-200 rounded-lg shadow-sm p-6 shrink-0 h-fit">
                  <h3 className="section-title text-base font-semibold text-slate-800 mb-4 flex items-center gap-2">
                    <Icon.Bolt className="w-4 h-4 text-purple-500" />
                    Fusion Applied
                  </h3>
                  <div className="space-y-4">
                    <div className="flex justify-between items-baseline border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">Mode</span>
                      <span className="font-medium text-slate-800 capitalize">{fusion.mode}</span>
                    </div>
                    <div className="flex justify-between items-baseline border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">R² Fit</span>
                      <span className="font-medium tabular-nums text-slate-800">{num(fusion.r_squared, 3)}</span>
                    </div>
                    <div className="flex justify-between items-baseline border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">Mean Adj.</span>
                      <span className={`font-medium tabular-nums ${fusion.mean_adjustment_pct > 0 ? 'text-emerald-600' : fusion.mean_adjustment_pct < 0 ? 'text-rose-600' : 'text-slate-800'}`}>
                        {signedPct(fusion.mean_adjustment_pct, 1)}
                      </span>
                    </div>
                    <div className="flex justify-between items-baseline border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">Max Adj.</span>
                      <span className="font-medium tabular-nums text-slate-800">{pct(fusion.max_adjustment_pct, 1)}</span>
                    </div>
                    <div className="flex justify-between items-baseline border-b border-slate-100 pb-2">
                      <span className="text-sm text-slate-500">Lag</span>
                      <span className="font-medium tabular-nums text-slate-800">{fusion.lag_days} days</span>
                    </div>
                    {fusion.note && (
                      <div className="text-xs text-slate-500 bg-slate-50 p-3 rounded border border-slate-100 italic">
                        {fusion.note}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 7. DATA TAB */}
          {activeTab === 'Data' && (
            <div className="flex flex-col lg:flex-row gap-6 h-full min-h-[500px]">
              <div className="flex-1 bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden flex flex-col">
                <div className="p-4 border-b border-slate-200 bg-slate-50/50 flex justify-between items-center">
                  <h3 className="section-title text-base font-semibold text-slate-800">Forecast Data</h3>
                  <button className="btn-ghost text-xs flex items-center gap-1 text-slate-500 hover:text-blue-600 font-medium">
                    <Icon.Box className="w-4 h-4" /> Export CSV
                  </button>
                </div>
                <div className="flex-1 overflow-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="sticky top-0 bg-white border-b border-slate-200 shadow-sm z-10">
                      <tr className="text-slate-500">
                        <th className="font-medium py-3 px-4">Date</th>
                        <th className="font-medium py-3 px-4 text-right">Predicted</th>
                        <th className="font-medium py-3 px-4 text-right">Base Units</th>
                        <th className="font-medium py-3 px-4 text-right">Lower 80%</th>
                        <th className="font-medium py-3 px-4 text-right">Upper 80%</th>
                        <th className="font-medium py-3 px-4 text-right text-slate-400">Lower 95%</th>
                        <th className="font-medium py-3 px-4 text-right text-slate-400">Upper 95%</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {forecast.map((f, i) => (
                        <tr key={f.date} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/30'}>
                          <td className="py-2.5 px-4 tabular-nums text-slate-600">{longDate(f.date)}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right font-medium text-slate-900">{num(f.predicted_units)}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right text-slate-500">{num(f.base_units)}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right text-slate-600">{num(f.lower_80)}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right text-slate-600">{num(f.upper_80)}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right text-slate-400">{f.lower_95 !== null ? num(f.lower_95) : '—'}</td>
                          <td className="py-2.5 px-4 tabular-nums text-right text-slate-400">{f.upper_95 !== null ? num(f.upper_95) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {forecast.some(f => f.lower_95 === null) && (
                  <div className="p-3 bg-slate-50 border-t border-slate-200 text-xs text-slate-500 flex items-center gap-2">
                    <Icon.Info className="w-4 h-4 shrink-0 text-slate-400" />
                    95% prediction intervals are unavailable (em dash) because this model's quantile heads only cover 0.1–0.9. Wider bands would be unsupported extrapolation.
                  </div>
                )}
              </div>

              <div className="w-full lg:w-72 flex flex-col gap-4 shrink-0">
                <div className="card bg-white border border-slate-200 rounded-lg shadow-sm p-5">
                  <h3 className="section-title text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
                    <Icon.Shield className="w-4 h-4 text-slate-400" />
                    Data Quality Stats
                  </h3>
                  <div className="space-y-3">
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Quality Level</span>
                      <span className={`badge text-xs px-2 py-0.5 rounded capitalize font-medium ${
                        data_quality.level === 'good' ? 'bg-emerald-100 text-emerald-700' :
                        data_quality.level === 'adequate' ? 'bg-blue-100 text-blue-700' :
                        data_quality.level === 'limited' ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700'
                      }`}>
                        {data_quality.level}
                      </span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Observations</span>
                      <span className="text-sm font-medium tabular-nums text-slate-800">{num(data_quality.observations)}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Span Days</span>
                      <span className="text-sm font-medium tabular-nums text-slate-800">{num(data_quality.span_days)}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Non-zero Days</span>
                      <span className="text-sm font-medium tabular-nums text-slate-800">{num(data_quality.non_zero_days)}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Zero-day Ratio</span>
                      <span className="text-sm font-medium tabular-nums text-slate-800">{pct(data_quality.zero_day_ratio, 1)}</span>
                    </div>
                    <div className="flex justify-between items-baseline">
                      <span className="text-sm text-slate-500">Coverage Ratio</span>
                      <span className="text-sm font-medium tabular-nums text-slate-800">{pct(data_quality.coverage_ratio, 1)}</span>
                    </div>
                  </div>
                </div>

                {data_quality.warnings?.length > 0 && (
                  <div className="card bg-amber-50 border border-amber-200 rounded-lg p-4">
                    <h3 className="section-title text-sm font-semibold text-amber-800 mb-2 flex items-center gap-2">
                      <Icon.Warning className="w-4 h-4" />
                      Quality Warnings
                    </h3>
                    <ul className="list-disc pl-5 space-y-1.5 text-xs text-amber-700">
                      {data_quality.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </Reveal>
      </div>
    </div>
  )
}
