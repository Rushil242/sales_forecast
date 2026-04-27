/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Manrope', 'sans-serif'],
        display: ['Space Grotesk', 'sans-serif'],
      },
      colors: {
        brand: {
          500: '#7c3aed',
          600: '#6d28d9',
          700: '#5b21b6'
        }
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(124,58,237,.3), 0 16px 40px rgba(124,58,237,.25)',
      },
      backgroundImage: {
        hero: 'radial-gradient(circle at 20% 20%, rgba(124,58,237,.24), transparent 45%), radial-gradient(circle at 80% 0%, rgba(14,165,233,.2), transparent 38%)',
      }
    },
  },
  plugins: [],
}
