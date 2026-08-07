import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#FAF9F6",
          card: "#FFFFFF",
          dark: "#0D0C0A",
          subtle: "#F3F2EE",
        },
        text: {
          primary: "#1A1917",
          secondary: "#6B6A65",
          muted: "#A8A7A3",
        },
        accent: {
          DEFAULT: "#C96442",
          hover: "#B05537",
        },
        border: {
          DEFAULT: "#E8E7E3",
          focus: "#1A1917",
        },
        tag: {
          "ok-bg": "#EEF5EE",
          "ok-text": "#2D6A2D",
          "warn-bg": "#FEF7ED",
          "warn-text": "#92540A",
          "bad-bg": "#FEF1EE",
          "bad-text": "#92290A",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Geist Mono", "JetBrains Mono", "monospace"],
      },
      maxWidth: {
        content: "1200px",
      },
    },
  },
  plugins: [],
};

export default config;
