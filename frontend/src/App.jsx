import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const API_BASE_URL = 'http://localhost:8000'

function StatCard({ label, value }) {
  return (
    <div className="rounded-2xl border border-slate-700/50 bg-slate-900/70 p-5 shadow-lg backdrop-blur">
      <p className="text-xs uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-2 font-display text-2xl text-white">{value}</p>
    </div>
  )
}

export default function App() {
  const [file, setFile] = useState(null)
  const [productName, setProductName] = useState('Cargo Shorts')
  const [predictionDays, setPredictionDays] = useState(30)
  const [history, setHistory] = useState([])
  const [forecast, setForecast] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const chartData = useMemo(() => {
    const historical = history.map((point) => ({
      date: point.date,
      historical_units: Number(point.units_sold.toFixed(2)),
      predicted_units: null,
      lower_ci: null,
      upper_ci: null,
    }))

    const projected = forecast.map((point) => ({
      date: point.date,
      historical_units: null,
      predicted_units: Number(point.predicted_units.toFixed(2)),
      lower_ci: Number(point.lower_ci.toFixed(2)),
      upper_ci: Number(point.upper_ci.toFixed(2)),
    }))

    return [...historical, ...projected]
  }, [history, forecast])

  const totalHistoryUnits = useMemo(
    () => history.reduce((sum, point) => sum + point.units_sold, 0),
    [history],
  )

  const avgForecastUnits = useMemo(() => {
    if (!forecast.length) return 0
    return forecast.reduce((sum, point) => sum + point.predicted_units, 0) / forecast.length
  }, [forecast])

  const submitForecast = async (event) => {
    event.preventDefault()
    setError('')

    if (!file) {
      setError('Please upload a CSV file first.')
      return
    }

    try {
      setLoading(true)
      const formData = new FormData()
      formData.append('file', file)

      const query = new URLSearchParams({
        product_name: productName,
        prediction_days: String(predictionDays),
      })

      const response = await fetch(`${API_BASE_URL}/api/forecast?${query.toString()}`, {
        method: 'POST',
        body: formData,
      })

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || 'Failed to fetch forecast.')
      }

      setHistory(payload.history || [])
      setForecast(payload.forecast || [])
    } catch (err) {
      setError(err.message)
      setHistory([])
      setForecast([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-hero text-slate-100">
      <div className="grid-pattern min-h-screen">
        <div className="mx-auto max-w-7xl px-6 py-10 lg:px-8">
          <header className="mb-8 rounded-3xl border border-slate-700/50 bg-slate-900/65 p-8 shadow-glow backdrop-blur">
            <p className="mb-2 text-sm uppercase tracking-[0.25em] text-cyan-300">MVP · Agentic AI Data Analyst</p>
            <h1 className="font-display text-4xl font-bold leading-tight text-white md:text-5xl">
              Retail Forecast Intelligence Hub
            </h1>
            <p className="mt-3 max-w-3xl text-slate-300">
              Upload transactional sales CSV data, choose a product, and generate a 30-day AI forecast powered by Chronos.
            </p>
          </header>

          <section className="grid gap-6 lg:grid-cols-[1fr,2fr]">
            <form onSubmit={submitForecast} className="rounded-3xl border border-slate-700/50 bg-slate-900/70 p-6 shadow-lg backdrop-blur">
              <h2 className="font-display text-2xl text-white">Run Forecast</h2>

              <label className="mt-5 block text-sm text-slate-300">CSV Dataset</label>
              <input
                type="file"
                accept=".csv"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-200 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-2 file:text-white hover:file:bg-brand-500"
              />

              <label className="mt-5 block text-sm text-slate-300">Product Name</label>
              <input
                type="text"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
                className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none ring-brand-600 focus:ring-2"
              />

              <label className="mt-5 block text-sm text-slate-300">Prediction Horizon (days)</label>
              <input
                type="number"
                min={1}
                max={180}
                value={predictionDays}
                onChange={(e) => setPredictionDays(Number(e.target.value))}
                className="mt-2 w-full rounded-xl border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none ring-brand-600 focus:ring-2"
              />

              <button
                type="submit"
                disabled={loading}
                className="mt-6 w-full rounded-xl bg-gradient-to-r from-brand-600 to-cyan-600 px-4 py-3 font-semibold text-white transition hover:from-brand-500 hover:to-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Generating Forecast...' : 'Generate Forecast'}
              </button>

              {error ? <p className="mt-4 rounded-lg border border-rose-400/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p> : null}
            </form>

            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-3">
                <StatCard label="History Points" value={history.length} />
                <StatCard label="Forecast Points" value={forecast.length} />
                <StatCard label="Avg Forecast / Day" value={avgForecastUnits.toFixed(2)} />
              </div>

              <div className="rounded-3xl border border-slate-700/50 bg-slate-900/75 p-6 shadow-lg backdrop-blur">
                <h3 className="mb-4 font-display text-xl text-white">Historical + Forecast Trend</h3>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" minTickGap={25} />
                      <YAxis stroke="#94a3b8" />
                      <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155' }} />
                      <Legend />
                      <Line type="monotone" dataKey="historical_units" stroke="#22d3ee" dot={false} strokeWidth={2} name="Historical" />
                      <Line type="monotone" dataKey="predicted_units" stroke="#a78bfa" dot={false} strokeWidth={2} name="Forecast" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-3xl border border-slate-700/50 bg-slate-900/75 p-6 shadow-lg backdrop-blur">
                <h3 className="mb-4 font-display text-xl text-white">Forecast Confidence Band</h3>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={forecast}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" minTickGap={20} />
                      <YAxis stroke="#94a3b8" />
                      <Tooltip contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155' }} />
                      <Legend />
                      <Area type="monotone" dataKey="upper_ci" stroke="#818cf8" fill="#818cf844" name="Upper CI" />
                      <Area type="monotone" dataKey="lower_ci" stroke="#38bdf8" fill="#38bdf833" name="Lower CI" />
                      <Line type="monotone" dataKey="predicted_units" stroke="#c4b5fd" dot={false} strokeWidth={2} name="Median Forecast" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-3xl border border-slate-700/50 bg-slate-900/75 p-6 text-sm text-slate-300">
                <p>
                  Total historical units in selection: <span className="font-semibold text-white">{totalHistoryUnits.toFixed(2)}</span>
                </p>
                <p className="mt-2 text-xs text-slate-400">
                  Ensure FastAPI backend is running on <code>http://localhost:8000</code> before generating forecasts.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}
