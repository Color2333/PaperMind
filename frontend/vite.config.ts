/**
 * PaperMind Frontend - Vite Configuration
 * @author Bamzc
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom", "react-router-dom"],
          "markdown": ["react-markdown", "remark-gfm", "remark-math", "rehype-katex", "katex"],
          "icons": ["lucide-react"],
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
});
