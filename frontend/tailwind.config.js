/** @type {import('tailwindcss').Config} */

// Warm coral replaces generic blue as the primary brand color
const blush = {
  50: '#fef1f0', 100: '#fce3e1', 200: '#f9c7c2', 300: '#f4a39b', 400: '#ef7e72',
  500: '#ff7a6b', 600: '#e56150', 700: '#bf493a', 800: '#993d31', 900: '#7e352a', 950: '#431913',
};

// Warm orange as the primary accent
const tangerine = {
  50: '#fff8f0', 100: '#ffefdb', 200: '#ffdab5', 300: '#ffbf85', 400: '#ffa15c',
  500: '#ff9f45', 600: '#e5802a', 700: '#bf621e', 800: '#994f1c', 900: '#7a421b', 950: '#42200a',
};

// Soft green for positive states and category 3
const mint = {
  50: '#effbf8', 100: '#d5f5ee', 200: '#aaeae0', 300: '#75d9cc', 400: '#5cdcd3',
  500: '#4ecdc4', 600: '#3ab4ab', 700: '#2d9088', 800: '#26736d', 900: '#225f5a', 950: '#103633',
};

// Friendly blue relegated to a supporting role
const sky = {
  50: '#f0f7ff', 100: '#e0effe', 200: '#b9dcfd', 300: '#7cc0fc', 400: '#68aef2',
  500: '#5b9fed', 600: '#4082cc', 700: '#3368a6', 800: '#2c5685', 900: '#274a70', 950: '#1a2e4a',
};

// Soft purple for category 5
const lilac = {
  50: '#f8f6ff', 100: '#efeaff', 200: '#dcd1ff', 300: '#c5b1ff', 400: '#b69ef5',
  500: '#a78bfa', 600: '#8e6ee3', 700: '#7752c4', 800: '#62459e', 900: '#523a82', 950: '#322354',
};

// Warm yellow for warnings and category 6
const butter = {
  50: '#fffdf2', 100: '#fff9db', 200: '#fff0af', 300: '#ffe57d', 400: '#ffda5c',
  500: '#ffd166', 600: '#e6b745', 700: '#bf942c', 800: '#997423', 900: '#7d5e21', 950: '#47320b',
};

// Off-white/cream scales to replace stark clinical whites/grays for surfaces
const cream = {
  50: '#fefcf8', 100: '#fbf7f0', 200: '#f5efe4', 300: '#ebe3d5', 400: '#ded3c1',
  500: '#d0c1ac', 600: '#bbaa93', 700: '#a49079', 800: '#8f7c68', 900: '#786756', 950: '#42372e',
};

// Warm brown-tinted near-blacks replace slate/blue-gray text
const ink = {
  50: '#f2efec', 100: '#e1dcd7', 200: '#c9c2bb', 300: '#b6ad9f', 400: '#a89a8b',
  500: '#8a7c6e', 600: '#6b5f54', 700: '#4a4038', 800: '#2a2520', 900: '#1e1a17', 950: '#120f0d',
  DEFAULT: '#2a2520',
};

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        blush,
        tangerine,
        mint,
        sky,
        lilac,
        butter,
        cream,
        ink,
        // Aliases for backward compatibility while adopting the new palette
        brand: blush,
        accent: tangerine,
        // Semantic category colors for data visualization tiles
        cat: {
          1: blush,
          2: tangerine,
          3: mint,
          4: sky,
          5: lilac,
          6: butter,
        }
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        display: ['Plus Jakarta Sans', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        '4xl': '1.75rem', // 28px - generous soft radius
        '5xl': '2.25rem', // 36px - ultra soft radius
      },
      boxShadow: {
        // Shadows are tinted with warm brown (74, 64, 56) instead of pure black
        // to maintain the warm, friendly, consumer-app feel
        'xs': '0 1px 2px 0 rgba(74, 64, 56, 0.05)',
        'card': '0 4px 6px -1px rgba(74, 64, 56, 0.05), 0 2px 4px -2px rgba(74, 64, 56, 0.05)',
        'card-md': '0 10px 15px -3px rgba(74, 64, 56, 0.08), 0 4px 6px -4px rgba(74, 64, 56, 0.04)',
        'card-lg': '0 20px 25px -5px rgba(74, 64, 56, 0.08), 0 8px 10px -6px rgba(74, 64, 56, 0.04)',
        'card-xl': '0 25px 50px -12px rgba(74, 64, 56, 0.12)',
        'glow': '0 0 15px rgba(255, 122, 107, 0.3)', // Blush tinted glow
        'glow-mint': '0 0 15px rgba(78, 205, 196, 0.3)',
        'glow-sky': '0 0 15px rgba(91, 159, 237, 0.3)',
      },
      transitionTimingFunction: {
        // Premium, controlled easing functions for smooth minimal animation
        'spring': 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
        'smooth': 'cubic-bezier(0.4, 0, 0.2, 1)',
        'out-expo': 'cubic-bezier(0.19, 1, 0.22, 1)',
        'bounce-soft': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'fade-down': {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'slide-down': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(0)' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(100%)' },
          '100%': { transform: 'translateY(0)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.8)', opacity: '0.5' },
          '100%': { transform: 'scale(1.3)', opacity: '0' },
        },
        'gradient-pan': {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-5px)' },
        },
        // Slow organic morph for background shapes
        'blob': {
          '0%': { transform: 'translate(0px, 0px) scale(1)' },
          '33%': { transform: 'translate(30px, -50px) scale(1.1)' },
          '66%': { transform: 'translate(-20px, 20px) scale(0.9)' },
          '100%': { transform: 'translate(0px, 0px) scale(1)' },
        },
        'tilt': {
          '0%, 100%': { transform: 'rotate(0deg)' },
          '25%': { transform: 'rotate(1deg)' },
          '75%': { transform: 'rotate(-1deg)' },
        },
        'marquee': {
          '0%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(-100%)' },
        },
        'draw-line': {
          '0%': { strokeDashoffset: '100%' },
          '100%': { strokeDashoffset: '0' },
        },
        'pop': {
          '0%': { transform: 'scale(0.95)' },
          '40%': { transform: 'scale(1.02)' },
          '100%': { transform: 'scale(1)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.5s cubic-bezier(0.19, 1, 0.22, 1) forwards',
        'fade-in': 'fade-in 0.4s ease-out forwards',
        'fade-down': 'fade-down 0.5s cubic-bezier(0.19, 1, 0.22, 1) forwards',
        'scale-in': 'scale-in 0.4s cubic-bezier(0.19, 1, 0.22, 1) forwards',
        'slide-down': 'slide-down 0.5s cubic-bezier(0.19, 1, 0.22, 1) forwards',
        'slide-up': 'slide-up 0.5s cubic-bezier(0.19, 1, 0.22, 1) forwards',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        'gradient-pan': 'gradient-pan 3s ease infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'float': 'float 3s ease-in-out infinite',
        'blob': 'blob 7s infinite',
        'tilt': 'tilt 10s infinite linear',
        'marquee': 'marquee 25s linear infinite',
        'draw-line': 'draw-line 1.5s ease-out forwards',
        'pop': 'pop 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) forwards',
      },
    },
  },
  plugins: [],
};
