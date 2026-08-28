/**
 * Soft 3-D glyphs for the category and product tiles.
 *
 * These are hand-built SVG rather than downloaded 3-D renders. Stock packs like the
 * ones on Vecteezy are licensed per-asset and would have to be committed as binaries,
 * which is a lot of weight and a licensing question for a project that gets handed
 * around. The look — a tilted body, a lighter top face, one soft highlight and a
 * grounding shadow — is cheap to fake with two gradients and reads the same at tile
 * size, while staying resolution-independent and recolourable from the palette.
 *
 * Every glyph is drawn in a 64×64 box and takes its colours from a `hue` prop, so a
 * category keeps the same identity colour across the tile, its icon and its chart.
 */

const HUES = {
  blush:     { light: '#FFB4A8', mid: '#FF7A6B', dark: '#E04E3E', shade: '#C43D2F' },
  tangerine: { light: '#FFC98A', mid: '#FF9F45', dark: '#E07B1E', shade: '#C26512' },
  mint:      { light: '#8FE3DC', mid: '#4ECDC4', dark: '#2AA79E', shade: '#1E8A82' },
  sky:       { light: '#A3C9F7', mid: '#5B9FED', dark: '#3579CC', shade: '#2762A8' },
  lilac:     { light: '#CDBDFB', mid: '#A78BFA', dark: '#8362E0', shade: '#6B4CC4' },
  butter:    { light: '#FFE49B', mid: '#FFD166', dark: '#E0AE2E', shade: '#C2921C' },
}

/** Bodies are drawn once and tinted; only the silhouette changes per garment. */
const SHAPES = {
  tee: (c) => (
    <>
      <path d="M22 16 L16 20 L12 28 L18 32 L22 28 L22 50 Q32 53 42 50 L42 28 L46 32 L52 28 L48 20 L42 16 Q32 22 22 16 Z"
            fill={`url(#g-${c})`} />
      <path d="M22 16 Q32 22 42 16 L42 20 Q32 26 22 20 Z" fill={`url(#hi-${c})`} opacity="0.9" />
      <path d="M22 50 Q32 53 42 50 L42 47 Q32 50 22 47 Z" fill={`url(#sh-${c})`} opacity="0.5" />
    </>
  ),
  hoodie: (c) => (
    <>
      <path d="M20 20 L13 25 L9 34 L16 38 L20 34 L20 52 Q32 55 44 52 L44 34 L48 38 L55 34 L51 25 L44 20 Q32 25 20 20 Z"
            fill={`url(#g-${c})`} />
      <path d="M24 14 Q32 10 40 14 Q42 20 32 24 Q22 20 24 14 Z" fill={`url(#hi-${c})`} />
      <rect x="30" y="24" width="4" height="14" rx="2" fill={`url(#sh-${c})`} opacity="0.55" />
    </>
  ),
  trousers: (c) => (
    <>
      <path d="M22 12 L42 12 L44 30 L40 54 L33 54 L32 34 L31 54 L24 54 L20 30 Z"
            fill={`url(#g-${c})`} />
      <rect x="22" y="12" width="20" height="5" rx="2" fill={`url(#hi-${c})`} />
      <path d="M32 20 L32 34" stroke={c === 'butter' ? '#C2921C' : '#ffffff'} strokeWidth="1.2" opacity="0.35" />
    </>
  ),
  skirt: (c) => (
    <>
      <path d="M23 16 L41 16 L50 50 Q32 56 14 50 Z" fill={`url(#g-${c})`} />
      <rect x="23" y="14" width="18" height="5" rx="2" fill={`url(#hi-${c})`} />
      <path d="M28 20 L24 50 M36 20 L40 50" stroke="#ffffff" strokeWidth="1" opacity="0.28" />
    </>
  ),
  jacket: (c) => (
    <>
      <path d="M20 18 L12 24 L9 36 L16 39 L18 34 L18 52 L30 52 L32 24 L34 52 L46 52 L46 34 L48 39 L55 36 L52 24 L44 18 Z"
            fill={`url(#g-${c})`} />
      <path d="M20 18 L32 24 L44 18 L40 15 L32 19 L24 15 Z" fill={`url(#hi-${c})`} />
      <circle cx="32" cy="34" r="1.6" fill="#ffffff" opacity="0.6" />
      <circle cx="32" cy="42" r="1.6" fill="#ffffff" opacity="0.6" />
    </>
  ),
  ethnic: (c) => (
    <>
      <path d="M26 14 L38 14 L44 30 Q46 46 42 54 L22 54 Q18 46 20 30 Z" fill={`url(#g-${c})`} />
      <path d="M26 14 Q32 20 38 14 L38 18 Q32 24 26 18 Z" fill={`url(#hi-${c})`} />
      <path d="M25 34 Q32 38 39 34 M24 42 Q32 47 40 42" stroke="#ffffff" strokeWidth="1.1" opacity="0.45" fill="none" />
    </>
  ),
  bag: (c) => (
    <>
      <path d="M16 24 L48 24 L51 52 Q32 56 13 52 Z" fill={`url(#g-${c})`} />
      <path d="M16 24 L48 24 L47 29 L17 29 Z" fill={`url(#hi-${c})`} />
      <path d="M25 24 Q25 13 32 13 Q39 13 39 24" stroke={`url(#sh-${c})`} strokeWidth="3.2" fill="none" strokeLinecap="round" />
    </>
  ),
  box: (c) => (
    <>
      <path d="M32 12 L52 22 L32 32 L12 22 Z" fill={`url(#hi-${c})`} />
      <path d="M12 22 L32 32 L32 54 L12 44 Z" fill={`url(#g-${c})`} />
      <path d="M52 22 L32 32 L32 54 L52 44 Z" fill={`url(#sh-${c})`} />
    </>
  ),
  home: (c) => (
    <>
      <path d="M32 12 L54 30 L46 30 L46 52 L18 52 L18 30 L10 30 Z" fill={`url(#g-${c})`} />
      <path d="M32 12 L54 30 L46 30 L32 19 L18 30 L10 30 Z" fill={`url(#hi-${c})`} />
      <rect x="27" y="36" width="10" height="16" rx="1.5" fill={`url(#sh-${c})`} />
    </>
  ),
  mug: (c) => (
    <>
      <path d="M18 20 L44 20 L42 50 Q32 54 20 50 Z" fill={`url(#g-${c})`} />
      <ellipse cx="31" cy="20" rx="13" ry="4" fill={`url(#hi-${c})`} />
      <path d="M44 26 Q54 28 52 36 Q50 43 42 42" stroke={`url(#sh-${c})`} strokeWidth="3.4" fill="none" strokeLinecap="round" />
    </>
  ),
  globe: (c) => (
    <>
      <circle cx="32" cy="32" r="20" fill={`url(#g-${c})`} />
      <path d="M12 32 H52 M32 12 Q42 32 32 52 Q22 32 32 12" stroke="#ffffff" strokeWidth="1.4" fill="none" opacity="0.5" />
      <ellipse cx="26" cy="24" rx="7" ry="5" fill={`url(#hi-${c})`} opacity="0.55" />
    </>
  ),
  swatch: (c) => (
    <>
      <circle cx="32" cy="32" r="19" fill={`url(#g-${c})`} />
      <path d="M32 13 A19 19 0 0 1 32 51 Z" fill={`url(#sh-${c})`} opacity="0.65" />
      <ellipse cx="26" cy="24" rx="6.5" ry="4.5" fill="#ffffff" opacity="0.42" />
    </>
  ),
}

/** Keyword → silhouette. Ordered, so the most specific match wins. */
const RULES = [
  [/hood|sweat/i, 'hoodie'],
  [/jacket|puffer|coat|outerwear/i, 'jacket'],
  [/jean|trouser|chino|jogger|pant|palazzo|bottomwear/i, 'trousers'],
  [/skirt/i, 'skirt'],
  [/saree|kurta|kurti|sherwani|ethnic|anarkali|occasion/i, 'ethnic'],
  [/tee|t-shirt|shirt|top|polo|blouse|topwear/i, 'tee'],
  [/bag|storage|tote|shopper|lunch/i, 'bag'],
  [/home|decor|light|candle|heart|ornament/i, 'home'],
  [/mug|cup|kitchen|dining|cake|tea/i, 'mug'],
  [/market|city|region|mumbai|delhi|bengaluru|chennai|kolkata|pune|hyderabad/i, 'globe'],
]

export function shapeFor(label = '', dimension = '') {
  if (dimension === 'color') return 'swatch'
  for (const [pattern, shape] of RULES) if (pattern.test(label)) return shape
  return 'box'
}

/**
 * @param {string} label      what the tile is about, used to pick a silhouette
 * @param {string} hue        one of the palette keys above
 * @param {string} dimension  'color' forces a paint swatch
 * @param {number} size       px
 */
export default function Glyph3D({ label = '', hue = 'blush', dimension = '', size = 56, className = '' }) {
  const shape = shapeFor(label, dimension)
  const palette = HUES[hue] ?? HUES.blush
  // Gradient ids must be unique per (hue, shape) or one tile's defs win everywhere.
  const key = `${hue}-${shape}`.replace(/[^a-z0-9-]/gi, '')
  const draw = SHAPES[shape] ?? SHAPES.box

  return (
    <svg
      width={size} height={size} viewBox="0 0 64 64"
      className={`overflow-visible ${className}`}
      aria-hidden
    >
      <defs>
        {/* Body: light at the top-left, saturated in the middle, dark at the base —
            the cheapest convincing read of a lit solid. */}
        <linearGradient id={`g-${key}`} x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0%" stopColor={palette.light} />
          <stop offset="55%" stopColor={palette.mid} />
          <stop offset="100%" stopColor={palette.dark} />
        </linearGradient>
        <linearGradient id={`hi-${key}`} x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor={palette.light} />
        </linearGradient>
        <linearGradient id={`sh-${key}`} x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor={palette.dark} />
          <stop offset="100%" stopColor={palette.shade} />
        </linearGradient>
        <filter id={`d-${key}`} x="-40%" y="-40%" width="180%" height="180%">
          <feDropShadow dx="0" dy="2.5" stdDeviation="2.2"
                        floodColor={palette.shade} floodOpacity="0.28" />
        </filter>
      </defs>

      {/* Contact shadow, so the object sits on the tile instead of floating. */}
      <ellipse cx="32" cy="57" rx="15" ry="3.2" fill={palette.shade} opacity="0.16" />
      <g filter={`url(#d-${key})`}>{draw(key)}</g>
    </svg>
  )
}

export { HUES }
