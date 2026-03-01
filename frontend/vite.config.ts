/**
 * PaperMind Frontend - Vite Configuration
 * @author Color2333
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import svgr from "vite-plugin-svgr";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss(), svgr()],
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
        manualChunks(id) {
          // React 核心
          if (id.includes("node_modules/react/") || id.includes("node_modules/react-dom/") || id.includes("node_modules/react-router-dom/") || id.includes("node_modules/scheduler/")) {
            return "react-vendor";
          }
          // KaTeX 单独切（体积最大，且只有 LaTeX 内容才用到）
          if (id.includes("node_modules/katex/")) {
            return "katex";
          }
          // Markdown 解析器（不含 katex）
          if (id.includes("node_modules/react-markdown/") || id.includes("node_modules/remark") || id.includes("node_modules/rehype") || id.includes("node_modules/unified/") || id.includes("node_modules/mdast") || id.includes("node_modules/hast") || id.includes("node_modules/micromark") || id.includes("node_modules/vfile") || id.includes("node_modules/bail/") || id.includes("node_modules/is-plain-obj/") || id.includes("node_modules/trough/") || id.includes("node_modules/extend/")) {
            return "markdown";
          }
          // 图标库
          if (id.includes("node_modules/lucide-react/")) {
            return "icons";
          }
          // D3 / 图谱
          if (id.includes("node_modules/d3") || id.includes("node_modules/@nivo") || id.includes("node_modules/force-graph") || id.includes("node_modules/three/")) {
            return "graph-vendor";
          }
          // DOMPurify
          if (id.includes("node_modules/dompurify/")) {
            return "dompurify";
          }
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
});
