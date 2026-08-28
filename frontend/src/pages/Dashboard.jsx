/**
 * The forecast workspace.
 *
 * The layout deliberately abandons the settings-panel-plus-canvas shape this page
 * used to have. A vertical stack of labelled form controls down the left edge is
 * what makes an analytics tool feel like a form to fill in rather than a place to
 * think, and it spends a permanent third of the screen on inputs that are read once
 * and then ignored for the rest of the session.
 *
 * Instead the configuration is a single sentence across the top —
 *   Forecast [product] from [source] for [30 days] using [model]
 * — where every bracketed token is a control. It reads as language, it collapses
 * four labelled fields into one line, and it hands the entire canvas below to the
 * answer. Choosing *what* to forecast is a big decision, so it opens a full-screen
 * picker rather than a cramped dropdown; the rest are small popovers because they
 * are small decisions.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import Browse from '../components/Browse'
import ForecastWorkspace from '../components/ForecastWorkspace'
import OwnerBrief from '../components/OwnerBrief'
import { Callout, Icon, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { num } from '../lib/format'

function datasetLabel(dataset) {
  if (!dataset) return 'Choose a source'
  if (dataset.source === 'connector') return dataset.connector?.label ?? 'Connected account'
  return dataset.name
}

/* ── primitives ─────────────────────────────────────────────────────────── */

/** Dismiss on outside click or Escape. */
function useDismiss(ref, onDismiss, active) {
  useEffect(() => {
    if (!active) return
    const onPointer = (e) => { if (ref.current && !ref.current.contains(e.target)) onDismiss() }
    const onKey = (e) => { if (e.key === 'Escape') onDismiss() }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, onDismiss, active])
}

/**
 * One clickable word in the command sentence. It is styled as text with a soft
 * underlay rather than as a form field, so the row keeps reading as a sentence.
 */
function Token({ icon: IconComp, label, value, onClick, tone = 'ink', open, dim }) {
  const tones = {
    ink: 'bg-white ring-ink-900/[0.07] hover:ring-blush-300 text-ink',
    blush: 'bg-blush-50 ring-blush-200 hover:ring-blush-300 text-blush-800',
  }
  return (
    <button
      onClick={onClick}
      className={`group inline-flex items-center gap-2 rounded-2xl px-3.5 py-2.5 ring-1
                  shadow-xs transition-all duration-200 ease-out-expo align-middle
                  hover:-translate-y-px hover:shadow-card-md
                  ${tones[tone]} ${open ? 'ring-blush-400 shadow-card-md' : ''}`}
    >
      {IconComp && (
        <span className="shrink-0 w-6 h-6 rounded-lg bg-ink-900/[0.04] flex items-center
                         justify-center text-ink-500 group-hover:text-blush-500
                         transition-colors">
          <IconComp className="w-3.5 h-3.5" />
        </span>
      )}
      <span className="text-left leading-tight">
        <span className="block text-[10px] uppercase tracking-[0.09em] text-ink-400 font-semibold">
          {label}
        </span>
        <span className={`block text-sm font-semibold max-w-[15rem] truncate
                          ${dim ? 'text-ink-400' : ''}`}>
          {value}
        </span>
      </span>
      <Icon.ChevronDown
        className={`w-3.5 h-3.5 shrink-0 text-ink-300 transition-transform duration-200
                    ${open ? 'rotate-180' : ''}`}
      />
    </button>
  )
}

/** A small popover anchored under its trigger, for the low-stakes choices. */
function Popover({ open, onClose, children, width = 'w-72' }) {
  const ref = useRef(null)
  useDismiss(ref, onClose, open)
  if (!open) return null
  return (
    <div
      ref={ref}
      className={`absolute z-40 top-full mt-2 left-0 ${width} rounded-2xl bg-white
                  shadow-card-xl ring-1 ring-ink-900/[0.08] p-2 animate-slide-down`}
    >
      {children}
    </div>
  )
}

/** Full-screen overlay for the decisions that deserve room. */
function Overlay({ open, onClose, title, subtitle, children, footer }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:p-8">
      <button
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink-900/25 backdrop-blur-sm animate-fade-in"
      />
      <div
        className="relative w-full max-w-5xl max-h-full flex flex-col rounded-3xl bg-cream-50
                   shadow-card-xl ring-1 ring-ink-900/[0.08] overflow-hidden animate-scale-in"
      >
        <header className="flex items-start justify-between gap-4 px-6 sm:px-8 pt-6 pb-4
                           border-b border-ink-900/[0.06] bg-white/60">
          <div className="min-w-0">
            <h2 className="page-title text-xl">{title}</h2>
            {subtitle && (
              <p className="text-sm text-ink-500 mt-1 max-w-2xl leading-relaxed">{subtitle}</p>
            )}
          </div>
          <button onClick={onClose} className="btn-ghost shrink-0 -mr-2">Close</button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 sm:px-8 py-6 no-scrollbar">{children}</div>

        {footer && (
          <footer className="px-6 sm:px-8 py-4 border-t border-ink-900/[0.06]
                             bg-white/80 backdrop-blur-xl flex flex-wrap items-center gap-3">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}

/* ── the empty canvas ───────────────────────────────────────────────────── */

/**
 * What the page shows before anything has been run. A centred "no data" box tells
 * the user nothing; these three cards say what the tool is for and start the work.
 */
function QuickStart({ onPick, onRun, onConnect, selectionLabel }) {
  const cards = [
    {
      // Literal class strings, not `bg-${tone}-100`: Tailwind's JIT scans source
      // text, so an interpolated class name is never generated and renders colourless.
      swatch: 'bg-blush-100 text-blush-700', icon: Icon.Box, title: 'One product',
      body: 'Forecast a single SKU and see the interval you should actually stock to.',
      action: 'Choose a product', onClick: onPick,
    },
    {
      swatch: 'bg-mint-100 text-mint-700', icon: Icon.Layers, title: 'A whole category',
      body: 'Demand that is jumpy per SKU is often smooth in aggregate — and easier to buy against.',
      action: 'Browse groups', onClick: onPick,
    },
    {
      swatch: 'bg-sky-100 text-sky-700', icon: Icon.Plug, title: 'Your own store',
      body: 'Connect Shopify or Zoho and forecast the orders that came straight out of it.',
      action: 'Connect a source', onClick: onConnect,
    },
  ]

  return (
    <div className="reveal-stagger is-revealed">
      <div className="rounded-3xl bg-gradient-to-br from-blush-50 via-cream-50 to-mint-50
                      ring-1 ring-ink-900/[0.06] p-8 sm:p-10 mb-5 relative overflow-hidden">
        <div aria-hidden className="absolute -top-16 -right-10 w-56 h-56 rounded-full
                                    bg-tangerine-200/40 blur-3xl animate-float" />
        <div className="relative max-w-2xl">
          <span className="eyebrow text-blush-600">Ready when you are</span>
          <h2 className="page-title text-2xl sm:text-3xl mt-2 leading-tight text-balance">
            Pick something to forecast, and we'll show you what to buy.
          </h2>
          <p className="text-ink-600 mt-3 leading-relaxed">
            Every forecast is backtested against five statistical baselines before you see
            it, so the accuracy figure on screen was measured on your own history — not
            asserted.
          </p>
          <div className="flex flex-wrap gap-3 mt-6">
            <button className="btn-primary" onClick={onRun}>
              <Icon.Bolt className="w-4 h-4" />
              Forecast {selectionLabel ? `“${selectionLabel}”` : 'now'}
            </button>
            <button className="btn-secondary" onClick={onPick}>
              <Icon.Search className="w-4 h-4" /> Choose something else
            </button>
          </div>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        {cards.map((card) => (
          <button
            key={card.title}
            onClick={card.onClick}
            className="text-left rounded-2xl bg-white ring-1 ring-ink-900/[0.06] p-5
                       shadow-card hover:shadow-card-lg hover:-translate-y-1
                       transition-all duration-300 ease-out-expo group"
          >
            <span className={`inline-flex w-11 h-11 rounded-2xl items-center justify-center ${card.swatch}`}>
              <card.icon className="w-5 h-5" />
            </span>
            <h3 className="font-display font-semibold text-ink mt-4">{card.title}</h3>
            <p className="text-sm text-ink-500 mt-1.5 leading-relaxed">{card.body}</p>
            <span className="inline-flex items-center gap-1 text-sm font-medium text-blush-600 mt-3
                             group-hover:gap-2 transition-all">
              {card.action} <Icon.ArrowRight className="w-3.5 h-3.5" />
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/** Skeleton that mirrors the real result, so the page does not jump when it lands. */
const STAGE_META = {
  sentiment:  { icon: Icon.Share,    label: 'Social signal' },
  series:     { icon: Icon.Database, label: 'Demand series' },
  covariates: { icon: Icon.Layers,   label: 'External signals' },
  forecast:   { icon: Icon.Sparkles, label: 'Foundation model' },
  backtest:   { icon: Icon.Shield,   label: 'Accuracy check' },
  brief:      { icon: Icon.Chart,    label: 'Plain-English brief' },
}

/**
 * The run log.
 *
 * Every line here corresponds to a stage the backend announced as it started it,
 * streamed over server-sent events. Nothing is on a timer and nothing is invented:
 * if covariates are switched off, that line simply never appears, and if the
 * backtest takes twelve seconds it sits spinning for twelve seconds.
 */
function RunningState({ label, stages }) {
  return (
    <div className="rounded-3xl bg-white ring-1 ring-ink-900/[0.06] shadow-card
                    overflow-hidden animate-fade-in">
      <div className="px-7 py-5 border-b border-ink-900/[0.06] bg-gradient-to-r
                      from-blush-50/70 to-cream-50 flex items-center gap-3">
        <span className="relative flex w-2.5 h-2.5">
          <span className="absolute inline-flex w-full h-full rounded-full bg-blush-400 animate-pulse-ring" />
          <span className="relative inline-flex w-2.5 h-2.5 rounded-full bg-blush-500" />
        </span>
        <div className="min-w-0">
          <p className="font-display font-semibold text-ink">Forecasting {label}</p>
          <p className="text-xs text-ink-500 mt-0.5">
            Each step below is reported by the pipeline as it starts it.
          </p>
        </div>
      </div>

      <ol className="p-4 sm:p-6 space-y-1">
        {stages.length === 0 && (
          <li className="flex items-center gap-3 px-3 py-3 text-sm text-ink-400">
            <Spinner className="w-4 h-4" /> Starting…
          </li>
        )}
        {stages.map((s, i) => {
          const meta = STAGE_META[s.stage] ?? { icon: Icon.Bolt, label: s.stage }
          const StageIcon = meta.icon
          return (
            <li
              key={`${s.stage}-${i}`}
              className="flex items-start gap-3 px-3 py-3 rounded-2xl animate-fade-up
                         transition-colors"
              style={{ animationDelay: '40ms' }}
            >
              <span className={`shrink-0 w-8 h-8 rounded-xl flex items-center justify-center
                                transition-colors duration-300
                                ${s.done ? 'bg-mint-100 text-mint-700'
                                         : 'bg-blush-100 text-blush-600'}`}>
                {s.done ? <Icon.Check className="w-4 h-4" />
                        : <StageIcon className="w-4 h-4 animate-pulse" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className={`text-sm font-semibold ${s.done ? 'text-ink-600' : 'text-ink'}`}>
                    {meta.label}
                  </span>
                  {!s.done && <Spinner className="w-3 h-3 text-blush-500" />}
                </span>
                <span className="block text-xs text-ink-500 mt-0.5 leading-relaxed">
                  {s.detail}
                </span>
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/* ── page ───────────────────────────────────────────────────────────────── */

export default function Dashboard({
  onOpenSocial, onOpenConnect, productName, setProductName, dataVersion = 0,
}) {
  const [datasets, setDatasets] = useState([])
  const [datasetId, setDatasetId] = useState('online-retail-ii')
  const [taxonomy, setTaxonomy] = useState(null)
  const [taxonomyLoading, setTaxonomyLoading] = useState(false)
  const [selection, setSelection] = useState(null)
  const [models, setModels] = useState([])
  const [model, setModel] = useState('chronos-2')
  const [horizon, setHorizon] = useState(30)
  const [includeBacktest, setIncludeBacktest] = useState(true)
  const [includeSentiment, setIncludeSentiment] = useState(false)
  const [historyWindow, setHistoryWindow] = useState(180)
  const [view, setView] = useState('owner')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  // Stages reported by the backend as it reaches them. Not a scripted animation:
  // a skipped stage never arrives, and a slow one visibly takes its time.
  const [stages, setStages] = useState([])
  const [error, setError] = useState(null)
  const [uploadInfo, setUploadInfo] = useState(null)
  const fileInput = useRef(null)

  // Exactly one of: null | 'what' | 'source' (overlays) | 'horizon' | 'model' (popovers)
  const [openControl, setOpenControl] = useState(null)
  const close = useCallback(() => setOpenControl(null), [])

  useEffect(() => {
    Promise.all([api.listDatasets(), api.listModels()])
      .then(([datasetList, modelList]) => {
        setDatasets(datasetList)
        setModels(modelList)
        setDatasetId((current) => (
          current.startsWith('connector:') && !datasetList.some((d) => d.name === current)
            ? 'online-retail-ii' : current
        ))
      })
      .catch(setError)
  }, [dataVersion])

  useEffect(() => {
    if (!datasetId) return
    setTaxonomyLoading(true)
    api.datasetTaxonomy(datasetId)
      .then((t) => {
        setTaxonomy(t)
        const top = t.products?.[0]
        if (top) {
          setSelection({
            kind: 'product', label: top.label, productName: top.label, filters: {}, node: top,
          })
          setProductName(top.label)
        }
      })
      .catch(() => setTaxonomy(null))
      .finally(() => setTaxonomyLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId])

  const runForecast = useCallback(async () => {
    setLoading(true)
    setError(null)
    setOpenControl(null)
    setStages([])
    try {
      const response = await api.forecastStream({
        dataset: datasetId,
        product_name: selection?.productName ?? null,
        filters: selection?.filters ?? {},
        horizon_days: Number(horizon),
        model,
        include_backtest: includeBacktest,
        include_sentiment: includeSentiment,
      }, (event) => {
        setStages((prev) => [
          ...prev.map((s) => ({ ...s, done: true })),
          { stage: event.stage, detail: event.detail, done: false, at: Date.now() },
        ])
      })
      setResult(response)
    } catch (err) {
      setError(err)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [datasetId, selection, horizon, model, includeBacktest, includeSentiment])

  const handleUpload = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const response = await api.uploadDataset(file)
      setDatasets((prev) => [...prev.filter((d) => d.name !== response.dataset.name), response.dataset])
      setUploadInfo(response)
      setDatasetId(response.token)
      setOpenControl(null)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const selectedDataset = useMemo(
    () => datasets.find((d) => d.name === datasetId), [datasets, datasetId],
  )
  const activeModel = models.find((m) => m.name === model)

  return (
    <div className="max-w-[1500px] mx-auto px-5 lg:px-8 py-7">
      {/* ── title ─────────────────────────────────────────────────── */}
      <header className="mb-6 animate-fade-up">
        <span className="eyebrow text-blush-600">Demand intelligence</span>
        <h1 className="page-title text-3xl sm:text-[2.15rem] mt-1.5 leading-[1.08]">
          Forecast what you'll <span className="gradient-text">actually sell</span>
        </h1>
      </header>

      {/* ── the command sentence ──────────────────────────────────── */}
      <section
        className="surface-glass rounded-3xl ring-1 ring-ink-900/[0.07] shadow-card
                   px-4 sm:px-5 py-4 mb-6 animate-fade-up"
        style={{ animationDelay: '60ms' }}
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-3">
          <span className="text-sm text-ink-500 font-medium pl-1">Forecast</span>

          <Token
            icon={selection?.kind === 'product' ? Icon.Box : Icon.Layers}
            label={selection?.kind === 'product' ? 'Product' : 'Group'}
            value={selection?.label ?? 'choose something'}
            dim={!selection}
            tone="blush"
            open={openControl === 'what'}
            onClick={() => setOpenControl(openControl === 'what' ? null : 'what')}
          />

          <span className="text-sm text-ink-500 font-medium">from</span>

          <Token
            icon={selectedDataset?.source === 'connector' ? Icon.Plug : Icon.Database}
            label="Source"
            value={datasetLabel(selectedDataset)}
            open={openControl === 'source'}
            onClick={() => setOpenControl(openControl === 'source' ? null : 'source')}
          />

          <span className="text-sm text-ink-500 font-medium">for the next</span>

          <span className="relative">
            <Token
              icon={Icon.Calendar}
              label="Horizon"
              value={`${horizon} days`}
              open={openControl === 'horizon'}
              onClick={() => setOpenControl(openControl === 'horizon' ? null : 'horizon')}
            />
            <Popover open={openControl === 'horizon'} onClose={close}>
              <div className="grid grid-cols-4 gap-1.5 p-1">
                {[7, 14, 30, 60, 90, 120, 180].map((d) => (
                  <button
                    key={d}
                    onClick={() => { setHorizon(d); close() }}
                    className={`py-2 rounded-xl text-sm font-semibold transition-colors
                                ${Number(horizon) === d
                                  ? 'bg-blush-500 text-white'
                                  : 'bg-cream-100 text-ink-600 hover:bg-cream-200'}`}
                  >
                    {d}d
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-ink-400 px-3 pb-2 pt-1 leading-relaxed">
                Beyond 16 days the weather signal becomes climatology, and the response
                says so rather than implying a real forecast.
              </p>
            </Popover>
          </span>

          <span className="text-sm text-ink-500 font-medium">using</span>

          <span className="relative">
            <Token
              icon={Icon.Sparkles}
              label="Model"
              value={model}
              open={openControl === 'model'}
              onClick={() => setOpenControl(openControl === 'model' ? null : 'model')}
            />
            <Popover open={openControl === 'model'} onClose={close} width="w-80">
              <ul className="max-h-72 overflow-y-auto no-scrollbar">
                {models.map((m) => (
                  <li key={m.name}>
                    <button
                      onClick={() => { setModel(m.name); close() }}
                      disabled={!m.available}
                      className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors
                                  disabled:opacity-40
                                  ${m.name === model ? 'bg-blush-50' : 'hover:bg-cream-100'}`}
                    >
                      <span className="flex items-center gap-2">
                        <span className={`text-sm font-semibold
                                          ${m.name === model ? 'text-blush-700' : 'text-ink'}`}>
                          {m.name}
                        </span>
                        {m.supports_covariates && (
                          <span className="chip bg-mint-100 text-mint-800">signals</span>
                        )}
                        {m.name === model && (
                          <Icon.Check className="w-3.5 h-3.5 ml-auto text-blush-600" />
                        )}
                      </span>
                      <span className="block text-[11px] text-ink-400 mt-0.5 leading-snug">
                        {m.detail}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </Popover>
          </span>

          <button
            className="btn-primary ml-auto"
            onClick={runForecast}
            disabled={loading || !selection}
          >
            {loading ? <><Spinner className="w-4 h-4" /> Running…</>
                     : <><Icon.Bolt className="w-4 h-4" /> Run forecast</>}
          </button>
        </div>

        {/* secondary switches, as quiet pills rather than a form */}
        <div className="flex flex-wrap items-center gap-2 mt-3.5 pl-1">
          {[
            { on: includeBacktest, set: setIncludeBacktest, label: 'Measure accuracy',
              hint: 'rolling-origin backtest · ~3s' },
            { on: includeSentiment, set: setIncludeSentiment, label: 'Fuse social sentiment',
              hint: 'harvests live sources · ~10s' },
          ].map((t) => (
            <button
              key={t.label}
              onClick={() => t.set(!t.on)}
              title={t.hint}
              className={`inline-flex items-center gap-2 rounded-full pl-1.5 pr-3 py-1.5 text-xs
                          font-medium ring-1 transition-all duration-200
                          ${t.on
                            ? 'bg-mint-50 ring-mint-300 text-mint-800'
                            : 'bg-white ring-ink-900/[0.07] text-ink-400 hover:text-ink-600'}`}
            >
              <span className={`w-4 h-4 rounded-full flex items-center justify-center
                                ${t.on ? 'bg-mint-500 text-white' : 'bg-ink-900/[0.06]'}`}>
                {t.on && <Icon.Check className="w-2.5 h-2.5" />}
              </span>
              {t.label}
            </button>
          ))}
          {selectedDataset?.source === 'connector' && (
            <span className="chip bg-mint-100 text-mint-800 ml-1">
              <Icon.Plug className="w-3 h-3" /> live store data
            </span>
          )}
          {result && (
            <button className="btn-ghost text-xs ml-auto"
                    onClick={() => onOpenSocial(result.product_name)}>
              <Icon.Share className="w-3.5 h-3.5" /> What people are saying
            </button>
          )}
        </div>
      </section>

      {/* ── canvas ────────────────────────────────────────────────── */}
      {error && (
        <Callout
          tone="rose"
          title={
            error.code === 'insufficient_data' ? 'Not enough history to forecast this'
            : error.code === 'backend_unavailable' ? 'The API is not running'
            : error.code === 'network_error' ? 'Cannot reach the API'
            : 'That request failed'
          }
        >
          <p>{error.message}</p>
          {error.details?.suggestions?.length > 0 && (
            <p className="mt-1">
              Try:{' '}
              {error.details.suggestions.map((s, i) => (
                <button key={s} onClick={() => setProductName(s)}
                        className="underline underline-offset-2 hover:no-underline font-medium">
                  {s}{i < error.details.suggestions.length - 1 ? ', ' : ''}
                </button>
              ))}
            </p>
          )}
        </Callout>
      )}

      {uploadInfo?.warnings?.length > 0 && (
        <Callout tone="amber" title="Notes from parsing your file">
          {uploadInfo.warnings.map((w) => <p key={w}>{w}</p>)}
        </Callout>
      )}

      {loading && <RunningState label={selection?.label ?? 'your selection'} stages={stages} />}

      {!loading && !result && !error && (
        <QuickStart
          onPick={() => setOpenControl('what')}
          onRun={runForecast}
          onConnect={onOpenConnect}
          selectionLabel={selection?.label}
        />
      )}

      {!loading && result && (
        <div className="space-y-5">
          <OwnerBrief
            envelope={result.brief}
            covariates={result.covariates}
            compact={view === 'analyst'}
            onShowCharts={() => setView(view === 'analyst' ? 'owner' : 'analyst')}
          />
          <ForecastWorkspace
            result={result}
            view={view}
            onViewChange={setView}
            historyWindow={historyWindow}
            onHistoryWindowChange={setHistoryWindow}
            onOpenSocial={() => onOpenSocial(result.product_name)}
          />
        </div>
      )}

      {/* ── overlays ──────────────────────────────────────────────── */}
      <Overlay
        open={openControl === 'what'}
        onClose={close}
        title="What should we forecast?"
        subtitle="A single product, or a whole group summed into one demand series. Every tile shows whether it has the history to support a forecast."
        footer={
          <>
            <span className="text-sm text-ink-500 min-w-0 flex-1 truncate">
              {selection ? <>Selected: <strong className="text-ink">{selection.label}</strong></>
                         : 'Nothing selected yet'}
            </span>
            <button className="btn-secondary" onClick={close}>Done</button>
            <button className="btn-primary" onClick={runForecast} disabled={!selection || loading}>
              <Icon.Bolt className="w-4 h-4" /> Forecast this
            </button>
          </>
        }
      >
        <Browse
          taxonomy={taxonomy}
          loading={taxonomyLoading}
          selection={selection}
          onSelect={(next) => {
            setSelection(next)
            if (next.productName) setProductName(next.productName)
          }}
        />
      </Overlay>

      <Overlay
        open={openControl === 'source'}
        onClose={close}
        title="Where should the numbers come from?"
        subtitle="Bundled samples, files you have uploaded, and any store you have connected. All three go through identical checks."
        footer={
          <>
            <button className="btn-secondary" onClick={onOpenConnect}>
              <Icon.Plug className="w-4 h-4" /> Connect a platform
            </button>
            <input ref={fileInput} type="file" accept=".csv" onChange={handleUpload}
                   className="hidden" id="csv-upload" />
            <label htmlFor="csv-upload" className="btn-secondary cursor-pointer">
              <Icon.Upload className="w-4 h-4" /> Upload a CSV
            </label>
            <button className="btn-ghost ml-auto" onClick={close}>Done</button>
          </>
        }
      >
        <div className="grid sm:grid-cols-2 gap-4">
          {datasets.map((d) => {
            const id = d.source === 'upload' ? uploadInfo?.token ?? d.name : d.name
            const active = id === datasetId
            const live = d.source === 'connector'
            return (
              <button
                key={d.name}
                onClick={() => { setDatasetId(id); setOpenControl('what') }}
                className={`text-left rounded-2xl p-5 ring-1 transition-all duration-300
                            ease-out-expo relative overflow-hidden
                            ${active
                              ? 'bg-blush-50 ring-blush-300 shadow-glow'
                              : 'bg-white ring-ink-900/[0.07] hover:ring-blush-200 hover:shadow-card-lg hover:-translate-y-1'}`}
              >
                <span aria-hidden
                      className={`absolute -top-8 -right-6 w-28 h-28 rounded-full blur-2xl
                                  ${live ? 'bg-mint-200/50' : 'bg-lilac-200/40'}`} />
                <span className="relative flex items-start gap-3.5">
                  <span className={`shrink-0 w-11 h-11 rounded-2xl flex items-center justify-center
                                    ${live ? 'bg-mint-100 text-mint-700'
                                           : active ? 'bg-blush-500 text-white'
                                                    : 'bg-cream-200 text-ink-500'}`}>
                    {live ? <Icon.Plug className="w-5 h-5" /> : <Icon.Database className="w-5 h-5" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="font-display font-semibold text-ink truncate">
                        {datasetLabel(d)}
                      </span>
                      {live && <span className="chip bg-mint-100 text-mint-800">live</span>}
                    </span>
                    <span className="block text-[11px] text-ink-400 mt-1 tabular-nums">
                      {num(d.rows)} rows · {d.products} products · {d.span_days} days
                    </span>
                    <span className="block text-xs text-ink-500 mt-2 leading-relaxed line-clamp-3">
                      {d.description}
                    </span>
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </Overlay>
    </div>
  )
}
