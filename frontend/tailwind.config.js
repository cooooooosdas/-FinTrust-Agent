/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 深海军蓝 —— 主色
        navy: {
          50: '#f2f6fb',
          100: '#e2ebf5',
          200: '#c2d5e9',
          300: '#94b4d6',
          400: '#5f8cbb',
          500: '#3f6da1',
          600: '#2f5584',
          700: '#28446a',
          800: '#0f2745',
          900: '#0a1c34',
          950: '#06101f',
        },
        // 香槟金 —— 强调色
        champagne: {
          50: '#fbf8f0',
          100: '#f6efdb',
          200: '#ecd9ac',
          300: '#dfbf78',
          400: '#d4a856',
          500: '#c1903f',
          600: '#a37330',
          700: '#815729',
          800: '#694728',
          900: '#583c23',
        },
        ink: {
          DEFAULT: '#0a1c34',
          soft: '#40536b',
          muted: '#7c8ca3',
        },
      },
      fontFamily: {
        sans: [
          '"Inter var"',
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono"', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(10, 28, 52, 0.04), 0 8px 24px -12px rgba(10, 28, 52, 0.12)',
        lifted: '0 2px 4px rgba(10, 28, 52, 0.06), 0 18px 40px -18px rgba(10, 28, 52, 0.22)',
        inner: 'inset 0 1px 0 rgba(255, 255, 255, 0.06)',
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.92)', opacity: '0.7' },
          '70%': { transform: 'scale(1.25)', opacity: '0' },
          '100%': { transform: 'scale(1.25)', opacity: '0' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.32s cubic-bezier(0.22, 1, 0.36, 1) both',
        shimmer: 'shimmer 1.6s linear infinite',
        'pulse-ring': 'pulse-ring 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
