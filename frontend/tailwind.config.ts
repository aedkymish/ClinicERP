import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        dental: { 50: "#eff6ff", 100: "#dbeafe", 600: "#2563eb", 700: "#1d4ed8", 800: "#1e40af" },
        derma: { 50: "#f5f3ff", 100: "#ede9fe", 600: "#7c3aed", 700: "#6d28d9", 800: "#5b21b6" },
        brand: { 50: "#f0f9ff", 100: "#e0f2fe", 500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1", 900: "#0c4a6e" },
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Noto Sans Arabic", "Tahoma", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
