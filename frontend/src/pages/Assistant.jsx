/**
 * The conversational surface over the whole system.
 *
 * Three things this page does that a generic chat UI does not.
 *
 * **It shows the work while it happens.** Every turn streams the agent's own
 * stage transitions — which sub-agent took it, which tools ran, how long each
 * took. A forecast turn is fifteen seconds and a social harvest can pass ninety,
 * and the honest way to spend that time is to show what is being done rather
 * than a spinner implying something faster.
 *
 * **It labels who wrote the sentence.** "Written by AI" means Gemini phrased the
 * answer and the number guard passed it; "Computed" means it was composed
 * directly from the measured figures. Both are true answers built from the same
 * facts — the badge tells the reader which they are looking at, exactly as the
 * forecast and social briefs already do.
 *
 * **It keeps the evidence attached.** Citations name the run, the dataset and
 * the harvest's provenance, so no figure on screen is unattributable.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Icon, Spinner } from '../components/ui'
import { api } from '../lib/api'

const STAGE_META = {
  understand: { label: 'Reading the question', icon: Icon.Search },
  route: { label: 'Choosing an agent', icon: Icon.Share },
  forecast: { label: 'Forecasting', icon: Icon.Chart },
  series: { label: 'Building the demand series', icon: Icon.Activity },
  covariates: { label: 'Testing outside signals', icon: Icon.Beaker },
  backtest: { label: 'Checking accuracy', icon: Icon.Shield },
  sales: { label: 'Reading sales history', icon: Icon.Database },
  social: { label: 'Harvesting public discussion', icon: Icon.Share },
  catalogue: { label: 'Listing your data', icon: Icon.Layers },
  brief: { label: 'Writing the summary', icon: Icon.Sparkles },
  compose: { label: 'Writing the answer', icon: Icon.Sparkles },
}

const AGENT_LABEL = {
  forecast: 'Forecast agent',
  sales: 'Sales agent',
  social: 'Social agent',
  catalogue: 'Data agent',
  none: 'Assistant',
}

/** Minimal markdown: **bold** only, which is all the composer emits. */
function RichText({ text }) {
  const parts = useMemo(() => (text ?? '').split(/(\*\*[^*]+\*\*)/g), [text])
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**') ? (
          <strong key={i} className="font-semibold text-ink-900">{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

function SourceBadge({ source, guardFlags = [] }) {
  const isLlm = source === 'llm'
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ${
        isLlm
          ? 'bg-blush-50 text-blush-800 ring-1 ring-blush-200'
          : 'bg-mint-50 text-mint-800 ring-1 ring-mint-200'
      }`}
      title={
        isLlm
          ? 'Phrased by Gemini from the measured figures. Every number was checked against the tool results before this was shown.'
          : guardFlags.length
            ? `The AI-written answer was discarded because it used ${guardFlags.join(', ')}. This was composed directly from the measured figures.`
            : 'Composed directly from the measured figures. It cannot invent anything.'
      }
    >
      {isLlm ? <Icon.Sparkles className="w-3 h-3" /> : <Icon.Beaker className="w-3 h-3" />}
      {isLlm ? 'Written by AI' : 'Computed'}
    </span>
  )
}

function AgentTrace({ trace, stages, running }) {
  const [open, setOpen] = useState(false)
  const route = trace?.route
  const shown = running ? stages : stages

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-400 hover:text-ink-700 transition-colors"
      >
        {open ? <Icon.ChevronDown className="w-3.5 h-3.5" /> : <Icon.ChevronRight className="w-3.5 h-3.5" />}
        How this was answered
        {trace?.total_ms ? (
          <span className="normal-case tracking-normal font-medium text-ink-400">
            · {(trace.total_ms / 1000).toFixed(1)}s
          </span>
        ) : null}
      </button>

      {open && (
        <div className="mt-2.5 rounded-2xl border border-ink-100 bg-ink-50/50 p-4 space-y-3">
          {route && (
            <div className="text-xs text-ink-600 leading-relaxed">
              <span className="font-semibold text-ink-800">
                {AGENT_LABEL[trace.agent] ?? trace.agent}
              </span>{' '}
              took this ({Math.round((route.confidence ?? 0) * 100)}% confident).{' '}
              <span className="text-ink-500">{route.reason}</span>
              {route.entities?.carried_over?.length > 0 && (
                <span className="text-ink-500">
                  {' '}Carried {route.entities.carried_over.join(' and ')} over from the
                  previous question.
                </span>
              )}
            </div>
          )}

          {shown.length > 0 && (
            <ol className="space-y-1.5">
              {shown.map((stage, i) => {
                const meta = STAGE_META[stage.stage] ?? { label: stage.stage, icon: Icon.Check }
                const StageIcon = meta.icon
                return (
                  <li key={i} className="flex items-start gap-2.5 text-xs text-ink-600">
                    <StageIcon className="w-3.5 h-3.5 mt-0.5 shrink-0 text-ink-400" />
                    <span className="leading-relaxed">{stage.detail}</span>
                  </li>
                )
              })}
            </ol>
          )}

          {trace?.tools?.length > 0 && (
            <div className="pt-2 border-t border-ink-100 space-y-1">
              {trace.tools.map((tool, i) => (
                <div key={i} className="flex items-center gap-2 text-[11px] font-mono">
                  <span className={tool.ok ? 'text-mint-700' : 'text-blush-700'}>
                    {tool.ok ? '✓' : '✕'}
                  </span>
                  <span className="text-ink-700">{tool.tool}</span>
                  <span className="text-ink-400">{tool.duration_ms}ms</span>
                  {tool.error && (
                    <span className="text-blush-600 truncate">{tool.error}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Citations({ citations }) {
  if (!citations?.length) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {citations.map((c, i) => (
        <span
          key={i}
          title={c.detail}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white border border-ink-200 text-[11px] text-ink-600"
        >
          <Icon.Shield className="w-3 h-3 text-ink-400" />
          {c.label}
          {c.provenance && (
            <span className="text-ink-400 uppercase tracking-wide">· {c.provenance}</span>
          )}
        </span>
      ))}
    </div>
  )
}

function LiveStages({ stages }) {
  const latest = stages[stages.length - 1]
  return (
    <div className="rounded-3xl border border-ink-100 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2.5 mb-3">
        <Spinner className="w-4 h-4 text-blush-500" />
        <span className="text-sm font-semibold text-ink-800">
          {latest ? (STAGE_META[latest.stage]?.label ?? 'Working') : 'Thinking'}
        </span>
      </div>
      <ol className="space-y-2">
        {stages.map((stage, i) => {
          const meta = STAGE_META[stage.stage] ?? { label: stage.stage, icon: Icon.Check }
          const StageIcon = meta.icon
          const isLast = i === stages.length - 1
          return (
            <li
              key={i}
              className={`flex items-start gap-2.5 text-sm transition-opacity ${
                isLast ? 'text-ink-800' : 'text-ink-400'
              }`}
            >
              {isLast ? (
                <StageIcon className="w-4 h-4 mt-0.5 shrink-0 text-blush-500" />
              ) : (
                <Icon.Check className="w-4 h-4 mt-0.5 shrink-0 text-mint-500" />
              )}
              <span className="leading-relaxed">{stage.detail}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export default function Assistant({ datasets = [], onOpenForecast }) {
  const [turns, setTurns] = useState([])
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [context, setContext] = useState(null)
  const [error, setError] = useState(null)

  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    let mounted = true
    api.chatSuggestions()
      .then((res) => mounted && setSuggestions(res.suggestions ?? []))
      .catch(() => {})
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, stages, running])

  const send = useCallback(async (text) => {
    const message = (text ?? '').trim()
    if (!message || running) return

    setError(null)
    setDraft('')
    setStages([])
    setRunning(true)
    setTurns((prev) => [...prev, { role: 'user', content: message }])

    const collected = []
    try {
      const result = await api.chatStream(
        {
          message,
          context,
          history: turns.slice(-6).map((t) => ({
            role: t.role,
            content: t.role === 'user' ? t.content : t.answer,
          })),
        },
        (stage) => {
          collected.push(stage)
          setStages([...collected])
        },
      )
      setTurns((prev) => [...prev, { role: 'assistant', ...result, stages: collected }])
      // Carrying entities forward is what makes "and next month?" resolve.
      setContext(result?.trace?.route?.entities ?? null)
      setSuggestions(
        (result.follow_ups ?? []).map((label) => ({ label, intent: 'follow_up' })),
      )
    } catch (err) {
      setError(err?.message ?? 'The assistant could not answer that.')
    } finally {
      setRunning(false)
      setStages([])
      inputRef.current?.focus()
    }
  }, [context, running, turns])

  const empty = turns.length === 0

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] bg-cream-50">
      <div className="border-b border-ink-100 bg-white/80 backdrop-blur-sm px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <div className="w-9 h-9 rounded-2xl bg-gradient-to-br from-blush-400 to-tangerine-400 flex items-center justify-center shadow-sm">
            <Icon.Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink-900">Ask RetailIQ</h1>
            <p className="text-xs text-ink-500">
              Forecasts, sales history and public opinion — answered from your own data
            </p>
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-4xl mx-auto space-y-6">
          {empty && !running && (
            <div className="text-center py-10">
              <div className="w-16 h-16 rounded-3xl bg-gradient-to-br from-blush-100 to-butter-100 flex items-center justify-center mx-auto mb-5">
                <Icon.Sparkles className="w-8 h-8 text-blush-500" />
              </div>
              <h2 className="text-2xl font-semibold text-ink-900 mb-2 tracking-tight">
                What do you want to know?
              </h2>
              <p className="text-sm text-ink-500 max-w-lg mx-auto leading-relaxed">
                I route your question to the right agent, run the real tools, and answer
                only from what comes back. If a product has too little history to
                forecast honestly, I will say so rather than invent a number.
              </p>
            </div>
          )}

          {turns.map((turn, i) =>
            turn.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-3xl rounded-br-lg bg-ink-900 text-white px-5 py-3 text-sm leading-relaxed shadow-sm">
                  {turn.content}
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-start">
                <div className="max-w-[92%] w-full">
                  <div className="rounded-3xl rounded-bl-lg bg-white border border-ink-100 px-5 py-4 shadow-sm">
                    <div className="flex items-center justify-between gap-3 mb-3">
                      <span className="text-[11px] font-bold uppercase tracking-widest text-ink-400">
                        {AGENT_LABEL[turn.trace?.agent] ?? 'Assistant'}
                      </span>
                      <SourceBadge source={turn.source} guardFlags={turn.guard_flags} />
                    </div>

                    <div className="text-[15px] text-ink-700 leading-relaxed">
                      <RichText text={turn.answer} />
                    </div>

                    <Citations citations={turn.citations} />

                    {turn.warnings?.length > 0 && (
                      <div className="mt-3 rounded-xl bg-butter-50 border border-butter-200 px-3.5 py-2.5">
                        {turn.warnings.map((w, wi) => (
                          <p key={wi} className="text-xs text-ink-700 leading-relaxed">{w}</p>
                        ))}
                      </div>
                    )}

                    <AgentTrace trace={turn.trace} stages={turn.stages ?? []} />
                  </div>
                </div>
              </div>
            ),
          )}

          {running && stages.length > 0 && (
            <div className="flex justify-start">
              <div className="max-w-[92%] w-full">
                <LiveStages stages={stages} />
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-2xl bg-blush-50 border border-blush-200 px-4 py-3 flex items-start gap-2.5">
              <Icon.Warning className="w-4 h-4 text-blush-600 mt-0.5 shrink-0" />
              <p className="text-sm text-blush-800">{error}</p>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-ink-100 bg-white/90 backdrop-blur-sm px-6 py-4">
        <div className="max-w-4xl mx-auto">
          {suggestions.length > 0 && !running && (
            <div className="flex flex-wrap gap-2 mb-3">
              {suggestions.slice(0, 4).map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s.label)}
                  className="px-3.5 py-1.5 rounded-full border border-ink-200 bg-white text-xs text-ink-700 hover:border-blush-300 hover:text-blush-700 hover:bg-blush-50/50 transition-colors"
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(e) => { e.preventDefault(); send(draft) }}
            className="flex items-end gap-2.5"
          >
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(draft) }
                }}
                rows={1}
                placeholder="Ask about a forecast, last month's sales, or what people are saying…"
                disabled={running}
                className="w-full resize-none rounded-2xl border border-ink-200 bg-white px-4 py-3 pr-12 text-sm text-ink-800 placeholder:text-ink-400 focus:outline-none focus:border-blush-300 focus:ring-2 focus:ring-blush-100 disabled:opacity-60 transition-colors max-h-40"
                style={{ minHeight: '48px' }}
              />
            </div>
            <button
              type="submit"
              disabled={running || !draft.trim()}
              className="h-12 w-12 shrink-0 rounded-2xl bg-ink-900 text-white flex items-center justify-center hover:bg-ink-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
              aria-label="Send"
            >
              {running ? <Spinner className="w-4 h-4" /> : <Icon.ArrowRight className="w-5 h-5" />}
            </button>
          </form>

          <p className="mt-2.5 text-[11px] text-ink-400 text-center">
            Answers are built from tool results. Figures written by AI are checked
            against those results before you see them.
          </p>
        </div>
      </div>
    </div>
  )
}
