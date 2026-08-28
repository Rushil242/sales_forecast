import { useEffect, useState } from 'react'
import '../landing.css'

const Arrow = ({ className = '' }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
)

const Mark = () => <span className="ri-mark" aria-hidden="true"><i /><b /></span>

function SignalOrbit() {
  return (
    <div className="ri-orbit" aria-label="RetailIQ demand intelligence visualisation">
      <div className="ri-orbit-head"><span>LIVE DECISION SURFACE</span><span>01 / 04</span></div>
      <svg viewBox="0 0 560 560" role="img" aria-label="Sales, calendar, weather, and social signals converge to a forecast">
        <g className="ri-grid" stroke="currentColor" fill="none"><rect x="22" y="22" width="516" height="516" rx="4" /><path d="M22 151h516M22 280h516M22 409h516M151 22v516M280 22v516M409 22v516" /></g>
        <g className="ri-threads" fill="none" stroke="currentColor"><path d="M90 186C155 105 220 156 280 280S420 424 475 348" /><path d="M85 370C154 433 208 400 280 280S414 140 484 196" /><path d="M125 104C172 214 196 247 280 280S387 332 446 456" /></g>
        <g className="ri-ring" fill="none" stroke="currentColor"><circle cx="280" cy="280" r="166" /><circle cx="280" cy="280" r="86" /></g>
        <g className="ri-nodes"><circle cx="90" cy="186" r="9" /><circle cx="85" cy="370" r="9" /><circle cx="125" cy="104" r="9" /><circle cx="475" cy="348" r="9" /><circle cx="484" cy="196" r="9" /><circle cx="446" cy="456" r="9" /><circle cx="280" cy="280" r="29" /></g>
        <text x="280" y="274" textAnchor="middle">FORECAST</text><text x="280" y="296" textAnchor="middle">ENGINE</text>
        <g className="ri-plot" fill="none"><path d="M68 459c28-16 41 13 67-9s45-2 66-38 39 31 58-13 49-16 66-52 39 27 65-14 44-7 74-53" /><path d="M68 480c28-16 41 13 67-9s45-2 66-38 39 31 58-13 49-16 66-52 39 27 65-14 44-7 74-53" /></g>
      </svg>
      <div className="ri-orbit-label ri-label-a">ORDERS<br /><strong>63,609</strong></div>
      <div className="ri-orbit-label ri-label-b">SIGNALS<br /><strong>9 + trends</strong></div>
      <div className="ri-orbit-foot"><span className="ri-live-dot" /> Backtested, not guessed</div>
    </div>
  )
}

const featureCards = [
  { no: '01', title: 'A foundation model that earns its inputs', body: 'Chronos-2 forecasts demand while measured weather, Indian holidays, calendar and optional social sentiment compete to be included. If a signal does not reduce error on that series, it is dropped.', tag: 'TSFM + ablation' },
  { no: '02', title: 'Sales data, connected at the source', body: 'Shopify and Zoho use real OAuth. A synced store becomes an ordinary dataset and must pass the exact same 30-observation quality gate as every upload.', tag: 'OAuth + encrypted tokens' },
  { no: '03', title: 'Social is evidence, not decoration', body: 'Nine live sources plus Google Trends are normalised into an attributed social signal. Pinterest and Reddit use a browser-backed collection path; Instagram and X use Apify.', tag: 'Scrapling + Apify' },
  { no: '04', title: 'One service layer, three interfaces', body: 'The FastAPI application, the React workspace and a seven-tool MCP server call the same business layer. Refusals survive every path—including the agent path.', tag: 'FastAPI + MCP' },
]

function FutureAgents() {
  const [prompt, setPrompt] = useState('How did men’s T-shirt sales perform last summer?')
  const historic = /sales|summer|last|revenue|order/i.test(prompt) && !/trend|social|talking|buzz/i.test(prompt)
  return (
    <section id="future" className="ri-future ri-section">
      <div className="ri-section-kicker"><span>COMING NEXT MONTH</span><em>Phase 2 / agentic interface</em></div>
      <div className="ri-future-head">
        <h2>A question becomes<br /><i>the right route.</i></h2>
        <p>Instead of another general chatbot, RetailIQ will route a business question to the smallest agent that can answer it—and show the evidence it used.</p>
      </div>
      <div className="ri-agent-stage">
        <div className="ri-agent-copy">
          <span className="ri-chip">Preview concept</span>
          <h3>Ask the business<br />in plain language.</h3>
          <p>The orchestrator classifies intent, selects a tool path, then returns an answer with its source—historical sales, forecast runs, or a live social harvest.</p>
          <div className="ri-agent-legend"><span><b className="ri-dot ri-dot-lime" /> Historical data</span><span><b className="ri-dot ri-dot-coral" /> Live social data</span></div>
        </div>
        <div className="ri-chat-shell">
          <div className="ri-chat-top"><span><b /> RetailIQ assistant</span><small>prototype</small></div>
          <div className="ri-chat-body">
            <div className="ri-user-message">{prompt}</div>
            <div className="ri-route-line"><span>Intent router</span><i /> <strong>{historic ? 'Historical demand RAG' : 'Social signal agent'}</strong></div>
            <div className="ri-agent-nodes">
              <div className={historic ? 'active history' : 'history'}><b>H</b><span>Historic RAG<small>sales + invoices</small></span></div>
              <div className={!historic ? 'active social' : 'social'}><b>S</b><span>Social agent<small>nine live sources</small></span></div>
              <div><b>F</b><span>Forecast agent<small>model runs</small></span></div>
            </div>
            <div className="ri-answer"><span>Answer preview</span>{historic ? 'Sales moved through the historical series, then retrieval grounds the answer in the relevant summer period.' : 'A live collection checks discussion volume, sentiment and rising terms before the answer is written.'}</div>
          </div>
          <label className="ri-chat-input"><input value={prompt} onChange={(event) => setPrompt(event.target.value)} aria-label="Try a future RetailIQ question" /><button aria-label="Send question"><Arrow /></button></label>
        </div>
      </div>
      <p className="ri-future-note">Planned scope: intent router + RAG over historic sales and saved runs + the existing MCP tools. It is presented here as the next milestone, not as a feature already shipping.</p>
    </section>
  )
}

export default function Landing({ onOpenWorkspace }) {
  const [dark, setDark] = useState(false)
  useEffect(() => {
    document.documentElement.style.scrollBehavior = 'smooth'
    return () => { document.documentElement.style.scrollBehavior = '' }
  }, [])

  return (
    <div className={`ri-landing ${dark ? 'ri-dark' : ''}`}>
      <header className="ri-nav">
        <a className="ri-brand" href="#top" aria-label="RetailIQ home"><Mark /><span>RETAIL<span>IQ</span></span></a>
        <nav aria-label="Landing page navigation"><a href="#method">Method</a><a href="#system">System</a><a href="#future">Next</a></nav>
        <div className="ri-nav-actions">
          <button className="ri-theme" onClick={() => setDark((value) => !value)} aria-label={dark ? 'Use light theme' : 'Use dark theme'}><span>{dark ? 'LIGHT' : 'DARK'}</span><i /></button>
          <button className="ri-nav-cta" onClick={onOpenWorkspace}>Open workspace <Arrow /></button>
        </div>
      </header>

      <main id="top">
        <section className="ri-hero">
          <div className="ri-hero-copy">
            <p className="ri-overline"><span className="ri-live-dot" /> Retail demand intelligence / final-year project</p>
            <h1>Demand is a<br /><i>moving target.</i><br />Treat it that way.</h1>
            <p className="ri-hero-text">RetailIQ connects sales records, the calendar, local conditions and the conversation around a product—then refuses to claim more certainty than the evidence supports.</p>
            <div className="ri-hero-actions"><button className="ri-cta-main" onClick={onOpenWorkspace}>Enter the dashboard <Arrow /></button><a className="ri-text-link" href="#method">See the method <span>↓</span></a></div>
            <div className="ri-hero-foot"><span>Built for a retail decision, not a demo graph.</span><span>VTU / BMSIT</span></div>
          </div>
          <SignalOrbit />
        </section>

        <section className="ri-statement" id="method">
          <p className="ri-overline">The operating principle</p>
          <h2>“Useful” is not the same<br />as <i>“confident-sounding.”</i></h2>
          <p>Every forecast is backtested. Every external number is attributed. A short history is refused rather than padded with plausible-looking data.</p>
          <div className="ri-principles">
            <article><b>01</b><span>No synthetic history</span><small>Under 30 observations? The system says so.</small></article>
            <article><b>02</b><span>No injected seasonality</span><small>Weekly and festival effects are measured, never hard-coded.</small></article>
            <article><b>03</b><span>No false precision</span><small>Intervals are only shown at quantiles the model can support.</small></article>
            <article><b>04</b><span>No orphaned numbers</span><small>Social data and AI briefs carry provenance and caveats.</small></article>
          </div>
        </section>

        <section className="ri-flow" id="system">
          <div className="ri-section-kicker"><span>THE SYSTEM</span><em>Inputs → evidence → action</em></div>
          <div className="ri-flow-grid">
            <div className="ri-flow-rail"><span>01</span><i /><span>02</span><i /><span>03</span><i /><span>04</span></div>
            <div className="ri-flow-items">
              <article><span>Connect or upload</span><h3>Orders arrive with<br />their provenance.</h3><p>CSV, Shopify and Zoho feed the same ingestion route. Tokens are Fernet-encrypted; connected data cannot skip validation.</p><div className="ri-source-pills"><b>Shopify</b><b>Zoho</b><b>CSV</b></div></article>
              <article><span>Build the series</span><h3>Groups before guesses.</h3><p>Forecast a product, a category, or an entire collection. Aggregation happens before forecasting, so group demand is not a sum of invented SKU forecasts.</p><div className="ri-mini-bars"><i /><i /><i /><i /><i /><i /><i /></div></article>
              <article><span>Measure the model</span><h3>Covariates must<br />win their place.</h3><p>Chronos-2 is evaluated in rolling windows. Holidays, weather, calendar and social sentiment are kept per-series only if they improve measured error.</p><div className="ri-score-line"><b>HOLIDAYS</b><span>+1.28%</span><i /></div></article>
              <article><span>Explain the result</span><h3>Give an owner a next move.</h3><p>Recharts keeps the analytical detail. A Gemini-or-template brief turns it into a clear action, while a number-provenance guard checks generated claims.</p><div className="ri-brief-snippet">“Demand is expected to remain within the measured interval. Reorder against the upper band, not a single point.”</div></article>
            </div>
          </div>
        </section>

        <section className="ri-capabilities">
          <div className="ri-capabilities-head"><p className="ri-overline">THE BUILD, BRIEFLY</p><h2>One research project.<br /><i>Several real surfaces.</i></h2><p>Each capability exists to make a forecast more inspectable—not simply more impressive-looking.</p></div>
          <div className="ri-feature-grid">
            {featureCards.map((feature) => <article key={feature.no} className="ri-feature-card"><div><span>{feature.no}</span><em>{feature.tag}</em></div><h3>{feature.title}</h3><p>{feature.body}</p><Arrow /></article>)}
          </div>
        </section>

        <section className="ri-proof">
          <div><p className="ri-overline">THE BASELINE</p><h2>Show the<br /><i>working.</i></h2></div>
          <div className="ri-proof-grid"><article><b>63,609</b><span>real UCI retail records used for the primary accuracy benchmark</span></article><article><b>739</b><span>days of real history—not a synthetic curve</span></article><article><b>+38.4%</b><span>RMSE improvement versus seasonal-naive on the benchmark</span></article><article><b>0.81</b><span>interval coverage against nominal 0.80</span></article></div>
          <p className="ri-proof-caveat">A separate Indian apparel catalogue is included for interface demonstrations and is explicitly simulated. It is never used for the real-data accuracy claim above.</p>
        </section>

        <FutureAgents />
      </main>

      <footer className="ri-footer"><div><a className="ri-brand" href="#top"><Mark /><span>RETAIL<span>IQ</span></span></a><p>Retail demand intelligence with an auditable point of view.</p></div><div><span>Final-year major project</span><span>BMS Institute of Technology & Management · VTU</span><span>2026</span></div><button onClick={onOpenWorkspace}>Open workspace <Arrow /></button></footer>
    </div>
  )
}
