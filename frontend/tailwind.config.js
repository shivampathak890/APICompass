/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: {
          DEFAULT: "#0b0f19",
          secondary: "#111827",
          panel: "#161f30",
          card: "#1e293b",
        },
        border: {
          DEFAULT: "#2d3748",
          subtle: "#1f2937",
        },
        accent: {
          violet: "#8b5cf6",
          cyan: "#06b6d4",
          emerald: "#10b981",
          amber: "#f59e0b",
        }
      },
    },
  },
  plugins: [],
}
