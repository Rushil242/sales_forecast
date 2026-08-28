import { useEffect, useMemo, useState } from 'react'
import Glyph3D from './Glyph3D'
import { Icon } from './ui'
import { num } from '../lib/format'

const GLYPHS = {
  home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline>',
  market: '<circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line>',
  heart: '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>',
  sparkle: '<path d="M12 2l3 6 6 3-6 3-3 6-3-6-6-3 6-3z"></path>',
  mug: '<path d="M18 8h1a4 4 0 0 1 0 8h-1"></path><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"></path><line x1="6" y1="1" x2="6" y2="4"></line><line x1="10" y1="1" x2="10" y2="4"></line><line x1="14" y1="1" x2="14" y2="4"></line>',
  bag: '<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path>',
  tag: '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>',
  kitchen: '<path d="M11 20A1 1 0 0 1 10 21H6A1 1 0 0 1 5 20V5A1 1 0 0 1 6 4H10A1 1 0 0 1 11 5V20Z"></path><path d="M19 20A1 1 0 0 1 18 21H14A1 1 0 0 1 13 20V5A1 1 0 0 1 14 4H18A1 1 0 0 1 19 5V20Z"></path>',
  clothing: '<path d="M20.38 3.46L16 2a8 8 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"></path>',
  candle: '<path d="M12 22v-9"></path><path d="M8 22v-6"></path><path d="M16 22v-3"></path><path d="M12 4a2 2 0 0 0-2 2c0 2 2 3 2 3s2-1 2-3a2 2 0 0 0-2-2Z"></path>',
  gift: '<polyline points="20 12 20 22 4 22 4 12"></polyline><rect x="2" y="7" width="20" height="5"></rect><line x1="12" y1="22" x2="12" y2="7"></line><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"></path><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"></path>',
  stationery: '<path d="M12 19l7-7 3 3-7 7-3-3z"></path><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"></path><path d="M2 2l7.58 7.58"></path><circle cx="11" cy="11" r="2"></circle>'
};

const SWATCHES = {
  white: '#ffffff', black: '#000000', red: '#ef4444', pink: '#ec4899', blue: '#3b82f6',
  navy: '#1e3a8a', khaki: '#fde047', beige: '#f5f5dc', indigo: '#6366f1', grey: '#9ca3af'
};

// A tile's category index also picks its 3-D glyph hue, so a category keeps one
// identity colour across its tile, its icon and its charts.
const HUE_BY_INDEX = { 1: 'blush', 2: 'tangerine', 3: 'mint', 4: 'sky', 5: 'lilac', 6: 'butter' }

const COLORS = {
  1: { bg: 'bg-cat-1-100', text: 'text-cat-1-700', ring: 'ring-cat-1-200', blob: 'bg-cat-1-300', tint: 'bg-cat-1-50', activeRing: 'ring-cat-1-500' },
  2: { bg: 'bg-cat-2-100', text: 'text-cat-2-700', ring: 'ring-cat-2-200', blob: 'bg-cat-2-300', tint: 'bg-cat-2-50', activeRing: 'ring-cat-2-500' },
  3: { bg: 'bg-cat-3-100', text: 'text-cat-3-700', ring: 'ring-cat-3-200', blob: 'bg-cat-3-300', tint: 'bg-cat-3-50', activeRing: 'ring-cat-3-500' },
  4: { bg: 'bg-cat-4-100', text: 'text-cat-4-700', ring: 'ring-cat-4-200', blob: 'bg-cat-4-300', tint: 'bg-cat-4-50', activeRing: 'ring-cat-4-500' },
  5: { bg: 'bg-cat-5-100', text: 'text-cat-5-700', ring: 'ring-cat-5-200', blob: 'bg-cat-5-300', tint: 'bg-cat-5-50', activeRing: 'ring-cat-5-500' },
  6: { bg: 'bg-cat-6-100', text: 'text-cat-6-700', ring: 'ring-cat-6-200', blob: 'bg-cat-6-300', tint: 'bg-cat-6-50', activeRing: 'ring-cat-6-500' }
};

const DQ_CONFIG = {
  good: { color: 'text-cat-3-700 bg-cat-3-50 ring-cat-3-200', dot: 'bg-cat-3-500', label: 'Good' },
  adequate: { color: 'text-cat-4-700 bg-cat-4-50 ring-cat-4-200', dot: 'bg-cat-4-500', label: 'Adequate' },
  limited: { color: 'text-cat-6-700 bg-cat-6-50 ring-cat-6-200', dot: 'bg-cat-6-500', label: 'Limited' },
  insufficient: { color: 'text-cat-1-700 bg-cat-1-50 ring-cat-1-200', dot: 'bg-cat-1-500', label: 'Insufficient history' }
};

function getColorFamily(label) {
  let hash = 0;
  const str = String(label || '');
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  return (Math.abs(hash) % 6) + 1;
}

function glyphFor(label, dimensionKey) {
  const L = String(label || '').toLowerCase();
  const K = String(dimensionKey || '').toLowerCase();
  if (K === 'color' || L.includes('color') || L.includes('swatch')) return null;
  if (L.includes('home') || L.includes('decor')) return GLYPHS.home;
  if (L.includes('kitchen') || L.includes('dining')) return GLYPHS.kitchen;
  if (L.includes('bag') || L.includes('storage')) return GLYPHS.bag;
  if (L.includes('stationery') || L.includes('craft')) return GLYPHS.stationery;
  if (L.includes('clothing') || L.includes('wear') || L.includes('upper') || L.includes('lower')) return GLYPHS.clothing;
  if (L.includes('globe') || L.includes('market') || L.includes('region')) return GLYPHS.market;
  if (L.includes('sparkle')) return GLYPHS.sparkle;
  if (L.includes('heart')) return GLYPHS.heart;
  if (L.includes('mug')) return GLYPHS.mug;
  if (L.includes('candle')) return GLYPHS.candle;
  if (L.includes('gift')) return GLYPHS.gift;
  if (L.includes('tag')) return GLYPHS.tag;
  if (L.includes('folder')) return GLYPHS.folder;
  return GLYPHS.box;
}

function colorSwatchFor(label) {
  const L = String(label || '').toLowerCase();
  for (const [k, v] of Object.entries(SWATCHES)) {
    if (L.includes(k)) return v;
  }
  return null;
}

const Tile = ({ title, subtitle, node, isActive, onSelect, onDrill, dimensionKey, isHero, index = 0, verb }) => {
  const isInsufficient = node?.data_quality === 'insufficient';
  const colorFamily = getColorFamily(title);
  const c = COLORS[colorFamily];
  const glyph = glyphFor(title, dimensionKey);
  const swatch = (dimensionKey === 'color' || String(title || '').toLowerCase().includes('color')) ? colorSwatchFor(title) : null;
  const dq = DQ_CONFIG[node?.data_quality || 'adequate'];

  const handleClick = (e) => {
    if (!isInsufficient && onSelect) onSelect();
  };

  const handleDrill = (e) => {
    e.stopPropagation();
    if (onDrill) onDrill();
  };

  if (isHero) {
    return (
      <button
        onClick={handleClick}
        disabled={isInsufficient}
        aria-pressed={isActive}
        className={`relative group text-left transition-all duration-300 ease-out overflow-hidden p-6 rounded-3xl w-full flex flex-col sm:flex-row sm:items-center gap-6 reveal-stagger is-revealed
          ${isInsufficient ? 'opacity-60 cursor-not-allowed grayscale-[0.5]' : 'hover:-translate-y-1 hover:shadow-lg cursor-pointer'}
          ${isActive ? `${c.activeRing} ring-2 ${c.tint} shadow-md` : 'bg-gradient-to-br from-slate-50 to-white ring-1 ring-slate-200/60 shadow-sm'}
        `}
      >
        <div className={`absolute -top-20 -right-20 w-64 h-64 rounded-full blur-3xl opacity-20 transition-opacity duration-300 ${c.blob} ${isActive ? 'opacity-40' : 'group-hover:opacity-50'}`} />

        {/* Floated top-right, as a piece of product art rather than an icon in a
            box. It bobs gently and lifts on hover; it is decorative, so it is
            aria-hidden and never intercepts the click. */}
        <div className="absolute -top-3 right-4 z-0 pointer-events-none opacity-90
                        transition-transform duration-500 ease-out-expo
                        group-hover:-translate-y-1 group-hover:scale-105 animate-float">
          <Glyph3D label={title} hue={HUE_BY_INDEX[colorFamily] ?? 'blush'}
                   dimension={dimensionKey} size={96} />
        </div>

        <div className={`w-16 h-16 shrink-0 rounded-2xl flex items-center justify-center relative z-10 ${c.bg} ${c.text}`}>
          {swatch ? (
            <div className="w-8 h-8 rounded-full shadow-inner ring-1 ring-black/10" style={{ backgroundColor: swatch }} />
          ) : (
            <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: glyph }} />
          )}
        </div>
        
        <div className="flex-1 relative z-10">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-xl font-semibold text-slate-900">
              {verb} all of {title}
            </h2>
            <div className="w-0 overflow-hidden opacity-0 group-hover:w-5 group-hover:opacity-100 transition-all duration-300 ease-out -ml-1 text-slate-400">
              <Icon.ArrowRight className="w-5 h-5" />
            </div>
          </div>
          {subtitle && <p className="text-sm text-slate-500 mb-3">{subtitle}</p>}
          <div className="flex flex-wrap items-center gap-4 text-sm text-slate-500">
             {node?.products != null && <span>{num(node.products)} products</span>}
             {node?.units != null && <span>{num(node.units)} units</span>}
             {node?.span_days != null && <span>{num(node.span_days)} days span</span>}
             <span className={`px-2 py-1 rounded-md flex items-center gap-1.5 font-medium text-xs ${dq.color}`}>
                <div className={`w-2 h-2 rounded-full ${dq.dot}`} />
                {dq.label}
             </span>
          </div>
        </div>
        
        {isActive && (
          <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-white shadow-sm ring-1 ring-slate-100 relative z-10">
            <Icon.Check className={`w-5 h-5 ${c.text}`} />
          </div>
        )}
      </button>
    );
  }

  return (
    <div 
      className={`relative group text-left transition-all duration-300 ease-out flex flex-col justify-between overflow-hidden rounded-2xl h-full reveal-stagger is-revealed
        ${isInsufficient ? 'opacity-60 grayscale-[0.5]' : 'hover:-translate-y-1 hover:shadow-lg'}
        ${isActive ? `${c.activeRing} ring-2 ${c.tint} shadow-md` : 'bg-white ring-1 ring-slate-200/60 shadow-sm'}
      `}
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <button
        onClick={handleClick}
        disabled={isInsufficient}
        aria-pressed={isActive}
        className={`absolute inset-0 w-full h-full text-left rounded-[inherit] focus:outline-none focus:ring-2 focus:ring-slate-400/50 z-0 ${isInsufficient ? 'cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span className="sr-only">Select {title}</span>
      </button>

      <div className={`absolute -top-10 -right-10 w-32 h-32 rounded-full blur-2xl opacity-20 transition-opacity duration-300 pointer-events-none z-0 ${c.blob} ${isActive ? 'opacity-40' : 'group-hover:opacity-40'}`} />

      <div className="absolute -top-2 right-2 z-0 pointer-events-none opacity-95
                      transition-transform duration-500 ease-out-expo
                      group-hover:-translate-y-1 group-hover:scale-110">
        <Glyph3D label={title} hue={HUE_BY_INDEX[colorFamily] ?? 'blush'}
                 dimension={dimensionKey} size={64} />
      </div>

      <div className="relative z-10 pointer-events-none p-5 flex flex-col justify-between h-full">
        <div>
          {/* Reserve the top-right corner for the floated glyph. */}
          <div className="h-12" />
          
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className="w-0 overflow-hidden opacity-0 group-hover:w-4 group-hover:opacity-100 transition-all duration-300 ease-out -ml-1 text-slate-400 shrink-0">
                <Icon.ArrowRight className="w-4 h-4" />
              </div>
              <h3 className="font-medium text-slate-900 line-clamp-2 leading-tight">
                {title}
              </h3>
            </div>
            {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
          </div>
        </div>

        <div className="mt-5 pt-4 border-t border-slate-100 flex flex-wrap items-center gap-3 text-xs text-slate-500">
           {node?.products != null && node.products !== 1 && (
             <span title="Products">{num(node.products)} prod</span>
           )}
           {node?.units != null && (
             <span title="Units">{num(node.units)} units</span>
           )}
           {node?.span_days != null && (
             <span title="History">{node.span_days}d</span>
           )}
           <span className={`px-1.5 py-0.5 rounded-md flex items-center gap-1 font-medium ${dq.color}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${dq.dot}`} />
              {dq.label}
           </span>
        </div>
      </div>

      {isActive && (
        <div className="absolute top-4 right-4 w-6 h-6 rounded-full flex items-center justify-center bg-white shadow-sm ring-1 ring-slate-100 z-10 pointer-events-none">
          <Icon.Check className={`w-3.5 h-3.5 ${c.text}`} />
        </div>
      )}

      {onDrill && (
        <button
          onClick={handleDrill}
          className={`absolute top-4 ${isActive ? 'right-12' : 'right-4'} p-1.5 text-slate-400 hover:text-slate-900 transition-colors z-20 rounded-full hover:bg-slate-100/80 focus:outline-none focus:ring-2 focus:ring-slate-400`}
          aria-label={`Drill into ${title}`}
        >
          <Icon.ChevronRight className="w-5 h-5" />
        </button>
      )}
    </div>
  );
};

export default function Browse({ taxonomy, selection, onSelect, loading, verb = 'Forecast' }) {
  const [trail, setTrail] = useState([{ key: 'root', label: 'All data' }]);

  useEffect(() => {
    setTrail([{ key: 'root', label: 'All data' }]);
  }, [taxonomy?.dataset]);

  const activeFilters = useMemo(() => {
    const f = {};
    trail.forEach(t => {
      if (t.dimension && t.value) f[t.dimension] = t.value;
    });
    return f;
  }, [trail]);

  const filteredProducts = useMemo(() => {
    if (!taxonomy?.products) return [];
    return taxonomy.products.filter(p => {
      for (const [k, v] of Object.entries(activeFilters)) {
        if (String(p[k]) !== String(v)) return false;
      }
      return true;
    });
  }, [taxonomy?.products, activeFilters]);

  const currentEntry = trail[trail.length - 1];
  const currentNode = currentEntry.node || taxonomy?.total;
  // 'Forecast all of All data' reads badly; name the dataset at the root instead.
  const heroLabel = currentEntry.key === 'root' ? 'this dataset' : currentEntry.label;
  const isHeroActive = selection?.label === heroLabel && (selection?.kind === 'group' || selection?.kind === 'all');

  const availableDimensions = useMemo(() => {
    return taxonomy?.dimensions?.filter(d => !(d.key in activeFilters)) || [];
  }, [taxonomy?.dimensions, activeFilters]);

  if (loading || !taxonomy) {
    return (
      <div className="w-full max-w-7xl mx-auto p-4 sm:p-6 lg:p-8 space-y-8 animate-pulse">
        <div className="flex gap-2 mb-6">
          <div className="w-24 h-8 bg-slate-200 rounded-full" />
        </div>
        <div className="h-32 bg-slate-200 rounded-3xl w-full" />
        <div className="space-y-4">
          <div className="w-32 h-6 bg-slate-200 rounded" />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map(i => <div key={i} className="h-32 bg-slate-100 rounded-2xl" />)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-7xl mx-auto p-4 sm:p-6 lg:p-8">
      <div className="flex items-center flex-wrap gap-2 mb-8">
        {trail.map((t, idx) => {
          const isLast = idx === trail.length - 1;
          return (
            <div key={t.key} className="flex items-center gap-2">
              {idx > 0 && <Icon.ChevronRight className="w-4 h-4 text-slate-300" />}
              <button
                onClick={() => !isLast && setTrail(trail.slice(0, idx + 1))}
                disabled={isLast}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors
                  ${isLast ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
              >
                {t.label}
              </button>
            </div>
          );
        })}
      </div>

      <div className="mb-10 reveal-stagger is-revealed">
        <Tile
          isHero
          title={heroLabel}
          subtitle={`Select to ${verb.toLowerCase()} all items in this group.`}
          node={currentNode}
          verb={verb}
          isActive={isHeroActive}
          onSelect={() => onSelect({
            kind: currentEntry.key === 'root' ? 'all' : 'group',
            label: heroLabel,
            productName: null,
            filters: activeFilters,
            node: currentNode
          })}
        />
      </div>

      {availableDimensions.map(dim => (
        <div key={dim.key} className="mb-10 reveal-stagger is-revealed">
          <div className="flex items-end justify-between mb-4">
            <div>
              <h3 className="section-title text-lg font-semibold text-slate-900">{dim.label}</h3>
            </div>
            {dim.description && <p className="text-sm text-slate-500">{dim.description}</p>}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dim.values.map((v, i) => {
              const isSelected = selection?.kind === 'group' && selection?.label === v.label;
              return (
                <Tile
                  key={v.value}
                  index={i}
                  title={v.label}
                  node={v}
                  dimensionKey={dim.key}
                  isActive={isSelected}
                  onSelect={() => onSelect({
                    kind: 'group',
                    label: v.label,
                    productName: null,
                    filters: { ...activeFilters, [dim.key]: v.value },
                    node: v
                  })}
                  onDrill={() => setTrail([...trail, {
                    key: dim.key + '-' + v.value,
                    label: v.label,
                    dimension: dim.key,
                    value: v.value,
                    node: v
                  }])}
                />
              );
            })}
          </div>
        </div>
      ))}

      {filteredProducts.length > 0 && (
        <div className="mb-10 reveal-stagger is-revealed">
          <div className="mb-4">
            <h3 className="section-title text-lg font-semibold text-slate-900">Products</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredProducts.map((p, i) => {
              const isSelected = selection?.kind === 'product' && selection?.label === p.label;
              return (
                <Tile
                  key={p.value}
                  index={i}
                  title={p.label}
                  node={p}
                  dimensionKey="product"
                  isActive={isSelected}
                  onSelect={() => onSelect({
                    kind: 'product',
                    label: p.label,
                    productName: p.label,
                    filters: activeFilters,
                    node: p
                  })}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
