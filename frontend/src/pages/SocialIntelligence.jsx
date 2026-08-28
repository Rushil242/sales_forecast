import { useCallback, useEffect, useMemo, useState } from 'react'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
         ResponsiveContainer, Cell, ReferenceLine } from 'recharts'
import Browse from '../components/Browse'
import { Callout, EmptyState, Icon, Spinner } from '../components/ui'
import { AnimatedNumber } from '../components/motion'
import { api } from '../lib/api'
import { longDate, num, relativeTime } from '../lib/format'

const PLATFORM_COLORS = ['#fb923c', '#34d399', '#60a5fa', '#a78bfa', '#f472b6', '#fbbf24'];

function getMoodInfo(score) {
  if (typeof score !== 'number') return { text: 'Unknown', desc: 'No sentiment measured.', pos: 50 };
  const pos = Math.max(0, Math.min(100, ((score + 1) / 2) * 100));
  if (score >= 0.5) return { text: 'Very Positive', desc: 'People are highly enthusiastic.', pos };
  if (score >= 0.1) return { text: 'Mildly Positive', desc: 'Broadly happy, but nobody is raving.', pos };
  if (score > -0.1) return { text: 'Neutral', desc: 'Balanced opinions or factual chatter.', pos };
  if (score > -0.5) return { text: 'Mildly Negative', desc: 'Some complaints or concerns.', pos };
  return { text: 'Very Negative', desc: 'Significant backlash or issues.', pos };
}

export default function SocialIntelligence({ query, onBack, datasets = [], initialDataset }) {
  const [subject, setSubject] = useState(query || (initialDataset ? initialDataset.id : ''));
  const [lookback, setLookback] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isSubjectModalOpen, setIsSubjectModalOpen] = useState(false);
  const [taxonomyData, setTaxonomyData] = useState(null);
  // The post wall used to show the six most-engaged documents overall, which one
  // chatty platform could fill entirely. These let a reader pick a source and
  // open the rest.
  const [sourceFilter, setSourceFilter] = useState('all');
  const [showAllPosts, setShowAllPosts] = useState(false);

  useEffect(() => {
    if (query && query !== subject) {
      setSubject(query);
    }
  }, [query]);

  const loadData = useCallback(async (refresh = false) => {
    if (!subject) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.social({ query: subject, lookbackDays: lookback, refresh });
      setData(res);
      setSourceFilter('all');
      setShowAllPosts(false);
    } catch (err) {
      setError(err.message || 'Failed to load data.');
    } finally {
      setLoading(false);
    }
  }, [subject, lookback]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    // App passes a `datasets` array and no `initialDataset`, so keying the fetch on
    // initialDataset?.id meant it never ran and the modal sat on its skeleton
    // forever. Resolve an id from whatever we were actually given.
    const datasetId =
      initialDataset?.id || initialDataset?.name || datasets[0]?.name || 'online-retail-ii'
    if (isSubjectModalOpen && !taxonomyData && datasetId) {
      api.datasetTaxonomy(datasetId)
         .then(setTaxonomyData)
         .catch(console.error);
    }
  }, [isSubjectModalOpen, taxonomyData, initialDataset, datasets]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isSubjectModalOpen) {
        setIsSubjectModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSubjectModalOpen]);

  const SubjectModal = () => (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 transition-opacity duration-300">
      <div className="absolute inset-0 bg-cream-500/80 backdrop-blur-sm" onClick={() => setIsSubjectModalOpen(false)} />
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-cream-50 rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-cream-50 z-10 shrink-0">
          <h2 className="text-xl font-semibold text-ink-900">Change Subject</h2>
          <button 
            onClick={() => setIsSubjectModalOpen(false)}
            className="text-sm font-medium text-ink-500 hover:text-ink-900 px-4 py-2 rounded-full hover:bg-ink-100 transition-colors"
          >
            Close
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
          <Browse 
            verb="Analyse" 
            datasets={datasets} 
            taxonomy={taxonomyData}
            onSelect={(next) => {
              // Browse hands back a selection object ({kind, label, productName,
              // filters, node}), not a string. Passing it straight to setSubject
              // put an object in the <h1> and React threw "Objects are not valid
              // as a React child" -- a blank page, no build error.
              const label =
                typeof next === 'string'
                  ? next
                  : next?.productName || next?.label || '';
              if (label) setSubject(label);
              setIsSubjectModalOpen(false);
            }}

          />
        </div>
      </div>
    </div>
  );

  if (!subject) {
    return (
      <div className="min-h-screen bg-cream-50 font-sans pb-24">
        {isSubjectModalOpen && <SubjectModal />}
        <div className="max-w-4xl mx-auto flex flex-col items-center justify-center pt-32 text-center px-6">
          <div className="w-20 h-20 bg-ink-100 rounded-full flex items-center justify-center mb-6 shadow-sm">
             <Icon.Search className="w-8 h-8 text-ink-400" />
          </div>
          <h2 className="text-3xl font-semibold text-ink-900 mb-4 tracking-tight">What should we analyse?</h2>
          <p className="text-ink-500 max-w-md mx-auto mb-8 text-lg">
            Select a product, brand, or topic to see social intelligence and demand signals translated into plain English.
          </p>
          <button 
            onClick={() => setIsSubjectModalOpen(true)}
            className="btn-primary py-3 px-8 rounded-full text-lg shadow-sm hover-lift flex items-center gap-2"
          >
            <Icon.Search className="w-5 h-5" />
            Choose Subject
          </button>
        </div>
      </div>
    );
  }

  const renderSkeleton = () => (
    <div className="animate-pulse space-y-12">
      <div className="h-64 bg-ink-100/50 rounded-3xl w-full"></div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => <div key={i} className="h-40 bg-ink-100/50 rounded-3xl"></div>)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 h-80 bg-ink-100/50 rounded-3xl"></div>
        <div className="flex flex-col gap-3">
           {[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-ink-100/50 rounded-2xl"></div>)}
        </div>
      </div>
    </div>
  );

  const mood = getMoodInfo(data?.overall_sentiment);
  const timeline = data?.timeline || [];
  const busiestDay = timeline.reduce((max, d) => (d.document_count > (max.document_count || -1) ? d : max), { document_count: -1, date: null });
  const standardPlatforms = (data?.platforms || []).filter(p => p.platform !== 'Google Trends');
  const googleTrends = (data?.platforms || []).find(p => p.platform === 'Google Trends');
  const brief = data?.brief?.brief;
  // Every source that actually returned a post, largest first, so a reader can
  // see at a glance that more than one platform had something.
  const docSources = useMemo(() => {
    const counts = new Map()
    for (const doc of data?.top_documents ?? []) {
      counts.set(doc.source, (counts.get(doc.source) ?? 0) + 1)
    }
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
  }, [data])

  const filteredDocs = useMemo(() => {
    const docs = data?.top_documents ?? []
    return sourceFilter === 'all' ? docs : docs.filter((d) => d.source === sourceFilter)
  }, [data, sourceFilter])

  const visibleDocs = showAllPosts ? filteredDocs : filteredDocs.slice(0, 6)

  const isLlm = data?.brief?.source === 'llm';
  // Why it is computed rather than AI-written. "Computed" alone reads as "no key
  // configured" even when the real cause is a spent daily quota.
  const briefWarnings = data?.brief?.warnings ?? [];
  const triedCount = data?.connectors?.length || 0;
  const answeredCount = (data?.connectors || []).filter(c => c.status === 'ok').length;

  return (
    <div className="min-h-screen bg-cream-50 text-ink-900 font-sans pb-24 px-4 sm:px-6 lg:px-8">
      {isSubjectModalOpen && <SubjectModal />}
      
      <div className="max-w-7xl mx-auto">
        <div className="sticky top-0 z-30 bg-cream-50/80 backdrop-blur-xl border-b border-ink-100/50 py-4 mb-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 -mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex items-center gap-3">
            {onBack && (
              <button onClick={onBack} className="p-2 -ml-2 text-ink-500 hover:text-ink-900 rounded-full hover:bg-ink-100 transition-colors shadow-sm bg-white">
                <Icon.Back className="w-5 h-5" />
              </button>
            )}
            <h1 className="text-2xl font-bold text-ink-900 line-clamp-1">
              {subject}
            </h1>
            <button 
              onClick={() => setIsSubjectModalOpen(true)}
              className="btn-soft bg-white border border-ink-200 text-sm py-1.5 px-4 rounded-full flex items-center gap-1.5 font-medium hover:bg-ink-50 shadow-sm transition-all"
            >
              Change <Icon.ChevronDown className="w-3 h-3 opacity-60" />
            </button>
          </div>
          <div className="flex items-center gap-3 overflow-x-auto no-scrollbar w-full sm:w-auto pb-1 sm:pb-0">
            <div className="flex bg-ink-200/40 p-1 rounded-full shrink-0">
              {[7, 14, 30, 60].map(days => (
                <button
                  key={days}
                  onClick={() => setLookback(days)}
                  className={`px-3.5 py-1.5 text-sm font-semibold rounded-full transition-all ${lookback === days ? 'bg-white text-ink-900 shadow-sm' : 'text-ink-500 hover:text-ink-900'}`}
                >
                  {days}d
                </button>
              ))}
            </div>
            <button onClick={() => loadData(true)} disabled={loading} className="btn-ghost p-2 rounded-full text-ink-500 hover:text-ink-900 bg-white shadow-sm border border-ink-200 shrink-0 transition-colors">
              <Icon.Refresh className={`w-5 h-5 ${loading ? 'animate-spin opacity-50' : ''}`} />
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-blush-50 border border-blush-200 text-blush-800 p-4 rounded-2xl mb-8 flex items-start gap-3 shadow-sm">
            <Icon.Warning className="w-5 h-5 shrink-0 mt-0.5" />
            <div>
              <h4 className="font-semibold mb-1">Failed to load data</h4>
              <p className="text-sm opacity-80">{error}</p>
            </div>
          </div>
        )}

        {loading && !data ? renderSkeleton() : data ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            
            {/* The Answer First - Hero Card */}
            <div className="card rounded-[2rem] p-6 sm:p-10 bg-gradient-to-br from-butter-50/80 to-blush-50/80 shadow-sm border border-ink-100/50 mb-12 relative overflow-hidden">
              <div className="absolute top-0 right-0 p-8 opacity-5 pointer-events-none">
                <Icon.Sparkles className="w-48 h-48 text-blush-500" />
              </div>
              <div className="relative z-10">
                <div className="flex flex-wrap items-center gap-3 mb-6">
                  <div className={`badge ${isLlm ? 'bg-blush-100 text-blush-800' : 'bg-ink-100 text-ink-800'} inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-sm font-medium shadow-sm`}>
                    {isLlm ? <Icon.Sparkles className="w-4 h-4" /> : <Icon.Beaker className="w-4 h-4" />}
                    {isLlm ? 'AI-Written Summary' : 'Computed Summary'}
                  </div>
                  {!isLlm && briefWarnings.length > 0 && (
                    <span
                      className="text-xs text-ink-500 bg-white/60 px-2.5 py-1.5 rounded shadow-sm max-w-xl"
                      title={briefWarnings.join(' ')}
                    >
                      {briefWarnings[0]}
                    </span>
                  )}
                  {data?.provenance && data.provenance !== 'none' && (
                    <div className="text-xs font-bold uppercase tracking-wider text-ink-500 flex items-center gap-1 bg-white/60 px-2.5 py-1.5 rounded shadow-sm">
                      <Icon.Database className="w-3.5 h-3.5" />
                      {data.provenance}
                    </div>
                  )}
                </div>
                
                <h2 className="text-3xl sm:text-4xl font-semibold text-ink-900 tracking-tight leading-tight mb-5 max-w-4xl">
                  {brief?.headline || 'Analysis Complete'}
                </h2>
                
                {brief?.summary && (
                  <p className="text-lg text-ink-700 leading-relaxed max-w-4xl mb-8">
                    {brief.summary}
                  </p>
                )}

                {/* The brief carries four to six concrete findings and the actions
                    that follow from them. Showing only the headline sentence threw
                    away almost all of what was actually written. */}
                {brief?.findings?.length > 0 && (
                  <ul className="space-y-3.5 mb-8 max-w-4xl">
                    {brief.findings.map((finding, i) => (
                      <li key={i} className="flex items-start gap-3">
                        <span
                          className={`mt-2 w-2 h-2 rounded-full shrink-0 ${
                            finding.severity === 'urgent'
                              ? 'bg-blush-500'
                              : finding.severity === 'watch'
                              ? 'bg-tangerine-500'
                              : 'bg-mint-500'
                          }`}
                        />
                        <span className="text-base text-ink-700 leading-relaxed">
                          {finding.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {brief?.actions?.length > 0 && (
                  <div className="bg-white/70 backdrop-blur-sm rounded-2xl border border-white/60 p-5 mb-8 max-w-4xl shadow-sm">
                    <div className="eyebrow text-xs font-bold uppercase tracking-widest text-ink-500 mb-3">
                      What to do about it
                    </div>
                    <ol className="space-y-3">
                      {brief.actions.map((action, i) => (
                        <li key={i} className="flex items-start gap-3">
                          <span
                            className={`shrink-0 w-6 h-6 rounded-full text-xs font-semibold flex items-center justify-center ${
                              action.urgency === 'urgent'
                                ? 'bg-blush-100 text-blush-800'
                                : action.urgency === 'watch'
                                ? 'bg-tangerine-100 text-tangerine-800'
                                : 'bg-ink-100 text-ink-700'
                            }`}
                          >
                            {i + 1}
                          </span>
                          <span className="text-sm text-ink-700 leading-relaxed">
                            {action.text}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {brief?.evidence_note && (
                  <div className="inline-block bg-white/60 backdrop-blur-sm px-4 py-2.5 rounded-xl text-sm text-ink-600 border border-white/50 shadow-sm">
                    <span className="font-semibold text-ink-800 mr-2">Evidence:</span>
                    {brief.evidence_note}
                  </div>
                )}
              </div>
            </div>

            {/* What This Means - Scorecard */}
            <div className="section-title mb-6 text-xl font-semibold text-ink-900">What This Means</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-16">
              <div className="tile p-6 flex flex-col justify-between hover-lift bg-white border border-ink-100 rounded-3xl shadow-sm">
                <div>
                  <h3 className="eyebrow text-xs font-bold uppercase tracking-widest text-ink-500 mb-3">Public Mood</h3>
                  <div className="stat-value text-2xl font-bold text-ink-900 mb-2">{mood.text}</div>
                  <p className="text-sm text-ink-600 mb-6">{mood.desc}</p>
                </div>
                <div className="w-full h-2.5 bg-gradient-to-r from-blush-400 via-butter-300 to-mint-400 rounded-full relative mt-auto shadow-inner">
                  {data?.overall_sentiment != null && (
                    <div 
                      className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-white border-[3px] border-ink-900 rounded-full shadow-sm transition-all duration-500" 
                      style={{ left: `calc(${mood.pos}% - 8px)` }} 
                    />
                  )}
                </div>
              </div>

              <div className="tile p-6 flex flex-col justify-between hover-lift bg-white border border-ink-100 rounded-3xl shadow-sm">
                <div>
                  <h3 className="eyebrow text-xs font-bold uppercase tracking-widest text-ink-500 mb-3">Chatter Volume</h3>
                  <div className="stat-value text-3xl font-bold text-ink-900 mb-2">
                    {data?.total_documents != null ? <AnimatedNumber value={data.total_documents} /> : '—'}
                  </div>
                  <p className="text-sm text-ink-600 mb-4">
                    {data?.total_documents > 1000 ? 'A high volume of discussion.' : data?.total_documents > 100 ? 'Moderate attention.' : 'Quiet out there.'}
                  </p>
                </div>
                <Icon.Activity className="w-7 h-7 text-ink-300 mt-auto" />
              </div>

              <div className="tile p-6 flex flex-col justify-between hover-lift bg-white border border-ink-100 rounded-3xl shadow-sm">
                <div>
                  <h3 className="eyebrow text-xs font-bold uppercase tracking-widest text-ink-500 mb-3">Sources Reached</h3>
                  <div className="stat-value text-3xl font-bold text-ink-900 mb-2">
                    {answeredCount}
                  </div>
                  <p className="text-sm text-ink-600 mb-4">
                    Active platforms providing data.
                  </p>
                </div>
                <Icon.Layers className="w-7 h-7 text-ink-300 mt-auto" />
              </div>

              <div className="tile p-6 flex flex-col justify-between hover-lift bg-white border border-ink-100 rounded-3xl shadow-sm">
                <div>
                  <h3 className="eyebrow text-xs font-bold uppercase tracking-widest text-ink-500 mb-3">Busiest Day</h3>
                  <div className="stat-value text-xl font-bold text-ink-900 mb-2 mt-1 line-clamp-1">
                    {busiestDay.date ? longDate(busiestDay.date) : '—'}
                  </div>
                  <p className="text-sm text-ink-600 mb-4">
                    {busiestDay.document_count > 0 ? `Spiked at ${num(busiestDay.document_count)} documents.` : 'No significant spikes.'}
                  </p>
                </div>
                <Icon.Calendar className="w-7 h-7 text-ink-300 mt-auto" />
              </div>
            </div>

            {/* Where the Talk Is - Platforms */}
            {standardPlatforms.length > 0 && (
              <div className="mb-16">
                <div className="section-title mb-6 text-xl font-semibold text-ink-900">Where the Talk Is</div>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div className="lg:col-span-2 card p-6 bg-white border border-ink-100 rounded-[2rem] h-80 shadow-sm">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={standardPlatforms} layout="vertical" margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#f3f4f6" />
                        <XAxis type="number" tickFormatter={(v) => num(v)} stroke="#9ca3af" fontSize={12} tickLine={false} axisLine={false} />
                        <YAxis type="category" dataKey="platform" stroke="#6b7280" fontSize={12} tickLine={false} axisLine={false} width={90} />
                        <Tooltip cursor={{fill: '#f9fafb'}} contentStyle={{ borderRadius: '16px', border: '1px solid #e5e7eb', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                        <Bar dataKey="documents" name="Documents" radius={[0, 6, 6, 0]} isAnimationActive={false} barSize={28}>
                          {standardPlatforms.map((entry, index) => (
                             <Cell key={`cell-${index}`} fill={PLATFORM_COLORS[index % PLATFORM_COLORS.length]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex flex-col gap-3">
                    {standardPlatforms.map((p, i) => (
                      <div key={i} className="tile p-4 flex flex-row items-center justify-between bg-white border border-ink-100 rounded-2xl border-l-[6px] shadow-sm hover-lift" style={{ borderLeftColor: PLATFORM_COLORS[i % PLATFORM_COLORS.length] }}>
                        <div>
                          <div className="font-semibold text-ink-900">{p.platform}</div>
                          <div className="text-sm text-ink-500 mt-0.5 font-medium">
                            {p.share != null ? `${(p.share * 100).toFixed(0)}% of talk` : `${num(p.documents)} documents`}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-bold uppercase tracking-wide" style={{ color: p.sentiment_score > 0.1 ? '#10b981' : p.sentiment_score < -0.1 ? '#ef4444' : '#f59e0b' }}>
                            {p.sentiment_score > 0.1 ? 'Positive' : p.sentiment_score < -0.1 ? 'Negative' : 'Neutral'}
                          </div>
                          {p.engagement_total > 0 && (
                            <div className="text-xs text-ink-400 mt-0.5">{num(p.engagement_total)} actions</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Google Trends visually separated */}
            {googleTrends && (
              <div className="mb-16 card p-6 sm:p-8 bg-gradient-to-r from-sky-50 to-white border border-sky-100 rounded-[2rem] shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <Icon.Search className="w-6 h-6 text-sky-500" />
                    <h4 className="text-xl font-semibold text-sky-900">Google Trends Search Interest</h4>
                  </div>
                  <p className="text-sm text-sky-700 max-w-2xl leading-relaxed">
                    This measures overall public attention and search volume. High numbers indicate strong awareness or curiosity, but do not imply positive or negative approval.
                  </p>
                </div>
                <div className="flex items-center gap-6 bg-white px-8 py-5 rounded-3xl shadow-sm border border-sky-50 shrink-0 w-full md:w-auto">
                  <div className="text-center">
                    <div className="text-4xl font-bold text-sky-900 leading-none mb-1.5"><AnimatedNumber value={googleTrends.documents} /></div>
                    <div className="text-[10px] text-sky-600 font-bold uppercase tracking-widest">Index Volume</div>
                  </div>
                  {googleTrends.trend_pct != null && (
                    <div className={`flex flex-col items-center justify-center min-w-[5rem] px-4 py-2 rounded-2xl ${googleTrends.trend_pct > 0 ? 'bg-mint-50 text-mint-700 border border-mint-100' : googleTrends.trend_pct < 0 ? 'bg-blush-50 text-blush-700 border border-blush-100' : 'bg-ink-50 text-ink-600 border border-ink-100'}`}>
                      <div className="flex items-center gap-1 text-base font-bold">
                        {googleTrends.trend_pct > 0 ? <Icon.TrendUp className="w-5 h-5" /> : googleTrends.trend_pct < 0 ? <Icon.TrendDown className="w-5 h-5" /> : <Icon.Minus className="w-5 h-5" />}
                        {Math.abs(googleTrends.trend_pct)}%
                      </div>
                      <div className="text-[10px] font-bold uppercase tracking-wider opacity-70 mt-0.5">Trend</div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Over Time - Timeline */}
            {timeline.length > 0 && (
              <div className="mb-16">
                <div className="section-title mb-6 text-xl font-semibold text-ink-900">Over Time</div>
                <div className="card p-6 sm:p-8 bg-white border border-ink-100 rounded-[2rem] shadow-sm">
                  <div className="flex items-center gap-2 mb-8 text-sm text-ink-600 bg-ink-50 border border-ink-100 px-4 py-2.5 rounded-xl inline-flex font-medium">
                    <Icon.Info className="w-4 h-4 text-ink-400 shrink-0" />
                    <span>A flat line at zero means nothing was said, not that sentiment was neutral.</span>
                  </div>
                  <div className="h-80 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={timeline} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorDocs" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#fca5a5" stopOpacity={0.3}/>
                            <stop offset="95%" stopColor="#fca5a5" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                        <XAxis 
                          dataKey="date" 
                          tickFormatter={(d) => new Date(d).toLocaleDateString(undefined, {month:'short', day:'numeric'})} 
                          stroke="#9ca3af" 
                          fontSize={12} 
                          tickLine={false} 
                          axisLine={false} 
                          dy={10} 
                          minTickGap={20}
                        />
                        <YAxis 
                          yAxisId="left"
                          stroke="#9ca3af" 
                          fontSize={12} 
                          tickLine={false} 
                          axisLine={false} 
                          tickFormatter={(v) => v === 0 ? '0' : num(v)}
                        />
                        <YAxis 
                          yAxisId="right"
                          orientation="right"
                          domain={[-1, 1]}
                          stroke="#9ca3af" 
                          fontSize={12} 
                          tickLine={false} 
                          axisLine={false} 
                          tickFormatter={(v) => v > 0 ? `+${v}` : v}
                          width={40}
                        />
                        <Tooltip 
                          contentStyle={{ borderRadius: '16px', border: '1px solid #e5e7eb', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                          labelFormatter={(d) => longDate(d)}
                          labelStyle={{ fontWeight: 600, color: '#111827', marginBottom: '4px' }}
                        />
                        <Area 
                          yAxisId="left"
                          type="monotone" 
                          dataKey="document_count" 
                          name="Documents"
                          stroke="#fca5a5" 
                          fillOpacity={1} 
                          fill="url(#colorDocs)" 
                          isAnimationActive={false}
                        />
                        <Area 
                          yAxisId="right"
                          type="monotone" 
                          dataKey="sentiment_index" 
                          name="Sentiment"
                          stroke="#34d399" 
                          fillOpacity={0}
                          strokeWidth={2}
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}

            {/* What People Say */}
            {(data?.trending_terms?.length > 0 || data?.top_documents?.length > 0) && (
              <div className="mb-16">
                <div className="section-title mb-6 text-xl font-semibold text-ink-900">What People Are Saying</div>
                
                {data?.trending_terms?.length > 0 && (
                  <div className="flex flex-wrap gap-2.5 mb-8">
                    {data.trending_terms.map((t, i) => {
                      const isPos = t.sentiment_score > 0.1;
                      const isNeg = t.sentiment_score < -0.1;
                      let bg = 'bg-ink-100 text-ink-700 border-ink-200';
                      if (isPos) bg = 'bg-mint-50 text-mint-800 border-mint-200';
                      if (isNeg) bg = 'bg-blush-50 text-blush-800 border-blush-200';
                      
                      const isLarge = t.share > 0.15 || t.count > 100;
                      const sizeClasses = isLarge ? 'text-base py-2.5 px-4' : 'text-sm py-1.5 px-3';
                      
                      return (
                        <div key={i} className={`chip rounded-full border ${bg} ${sizeClasses} inline-flex items-center gap-2 shadow-sm transition-transform hover:scale-105`}>
                          <span className="font-medium">{t.term}</span>
                          <span className="opacity-60 text-xs font-bold">{num(t.count)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {docSources.length > 1 && (
                  <div className="flex flex-wrap gap-2 mb-6">
                    {[{ name: 'all', count: data.top_documents.length }, ...docSources].map((src) => {
                      const active = sourceFilter === src.name
                      return (
                        <button
                          key={src.name}
                          onClick={() => { setSourceFilter(src.name); setShowAllPosts(false) }}
                          className={`text-sm px-3.5 py-1.5 rounded-full border transition-colors ${
                            active
                              ? 'bg-ink-900 text-white border-ink-900'
                              : 'bg-white text-ink-700 border-ink-200 hover:border-ink-400'
                          }`}
                        >
                          {src.name === 'all' ? 'All sources' : src.name}
                          <span className={`ml-2 text-xs font-bold ${active ? 'opacity-70' : 'text-ink-400'}`}>
                            {src.count}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}

                {visibleDocs.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                    {visibleDocs.map((doc, i) => (
                      <a key={i} href={doc.url} target="_blank" rel="noopener noreferrer" className="card p-6 hover-lift bg-white border border-ink-100 rounded-3xl flex flex-col group shadow-sm">
                        <div className="flex items-center justify-between mb-4">
                          <div className="badge bg-ink-100 text-ink-700 text-xs px-2.5 py-1 rounded-lg font-bold tracking-wide uppercase">
                            {doc.source}
                          </div>
                          <div className="text-xs text-ink-500 flex items-center gap-1.5 font-medium">
                            <Icon.Calendar className="w-3.5 h-3.5" />
                            {relativeTime(doc.published_at)}
                          </div>
                        </div>
                        <h4 className="font-semibold text-ink-900 mb-2.5 line-clamp-2 group-hover:text-blush-600 transition-colors leading-snug">
                          {doc.title || 'Untitled Document'}
                        </h4>
                        <p className="text-sm text-ink-600 line-clamp-3 mb-6 flex-1 leading-relaxed">
                          {doc.text}
                        </p>
                        <div className="flex items-center justify-between mt-auto pt-4 border-t border-ink-100/60">
                          <div className="flex items-center gap-2 text-xs font-bold text-ink-700 uppercase tracking-wider">
                            <div className={`w-2.5 h-2.5 rounded-full shadow-sm ${doc.sentiment_score > 0.1 ? 'bg-mint-500' : doc.sentiment_score < -0.1 ? 'bg-blush-500' : 'bg-butter-500'}`} />
                            {doc.sentiment_label || 'Neutral'}
                          </div>
                          {doc.engagement > 0 && (
                            <div className="text-xs font-semibold text-ink-600 flex items-center gap-1.5 bg-ink-50 px-2.5 py-1 rounded-lg">
                              <Icon.Star className="w-3.5 h-3.5 text-butter-500" />
                              {num(doc.engagement)}
                            </div>
                          )}
                        </div>
                      </a>
                    ))}
                  </div>
                )}

                {filteredDocs.length > visibleDocs.length && (
                  <button
                    onClick={() => setShowAllPosts(true)}
                    className="mt-6 w-full py-3 rounded-2xl border border-ink-200 bg-white text-sm font-semibold text-ink-700 hover:border-ink-400 transition-colors shadow-sm"
                  >
                    Show all {filteredDocs.length} posts
                    {sourceFilter !== 'all' ? ` from ${sourceFilter}` : ''}
                  </button>
                )}
                {showAllPosts && filteredDocs.length > 6 && (
                  <button
                    onClick={() => setShowAllPosts(false)}
                    className="mt-6 w-full py-3 rounded-2xl border border-ink-200 bg-white text-sm font-semibold text-ink-700 hover:border-ink-400 transition-colors shadow-sm"
                  >
                    Show fewer
                  </button>
                )}
              </div>
            )}

            {/* Coverage Section */}
            <div className="mb-12">
              <div className="section-title mb-6 text-xl font-semibold text-ink-900">Coverage & Sources</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 mb-8">
                <div className="col-span-full mb-2 text-sm font-medium text-ink-700 bg-ink-100/60 inline-flex px-4 py-2.5 rounded-xl border border-ink-100">
                  We tried {triedCount} places to find mentions. {answeredCount} provided active data.
                </div>
                {(data?.connectors || []).map((c, i) => (
                  <div key={i} className="tile p-5 bg-white border border-ink-100 rounded-3xl shadow-sm hover-lift relative flex flex-col">
                    <div className="flex items-start justify-between mb-3 gap-2">
                      <div className="font-semibold text-ink-900 flex items-center gap-2.5">
                        <div className={`w-2.5 h-2.5 rounded-full shrink-0 shadow-sm ${c.status === 'ok' ? 'bg-mint-500' : c.status === 'empty' ? 'bg-butter-500' : 'bg-blush-500'}`} />
                        <span className="line-clamp-1">{c.name}</span>
                      </div>
                      {c.documents > 0 && (
                        <span className="text-[10px] font-bold uppercase tracking-wider text-ink-600 bg-ink-100 px-2 py-1 rounded-lg shrink-0">
                          {num(c.documents)} docs
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-ink-600 font-medium">
                      {c.status === 'ok' ? 'Active and responding.' : c.status === 'empty' ? 'No mentions found.' : c.status === 'unavailable' ? 'Currently unavailable.' : 'Error connecting.'}
                    </div>
                    
                    {c.detail && (
                      <details className="mt-4 text-xs group/details border-t border-ink-100/50 pt-3">
                        <summary className="text-ink-400 cursor-pointer hover:text-ink-700 list-none flex items-center gap-1 font-semibold transition-colors uppercase tracking-wider text-[10px]">
                          <Icon.ChevronRight className="w-3 h-3 group-open/details:rotate-90 transition-transform" />
                          Technical details
                        </summary>
                        <div className="mt-3 p-3 bg-ink-50 rounded-xl text-ink-700 font-mono text-[10px] break-words border border-ink-100 shadow-inner">
                          {c.detail}
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
              <div className="text-center text-xs font-medium text-ink-400 mt-16 pt-8 border-t border-ink-100/50">
                Sentiment analysis powered by {data?.sentiment_model?.name || 'standard model'} {data?.sentiment_model?.device ? `(${data.sentiment_model.device})` : ''}.
              </div>
            </div>

          </div>
        ) : null}
      </div>
    </div>
  );
}
