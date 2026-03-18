import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: { 50:'#f0fdf4', 100:'#dcfce7', 400:'#4ade80', 500:'#22c55e', 600:'#16a34a', 700:'#15803d' },
        surface: { 800:'#1e293b', 900:'#0f172a', 700:'#334155', 600:'#475569' },
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
    }
  },
  plugins: [],
}
export default config
