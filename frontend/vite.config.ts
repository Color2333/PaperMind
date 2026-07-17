/**
 * PaperMind Frontend - Vite Configuration
 * @author Color2333
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import svgr from "vite-plugin-svgr";
import viteCompression from "vite-plugin-compression";
import path from "path";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    svgr(),
    // 预生成 .gz 静态文件，让 nginx 的 gzip_static on 命中（此前 gzip_static 失效回退实时压缩）
    viteCompression({ algorithm: "gzip", ext: ".gz", threshold: 1024, deleteOriginFile: false }),
  ],
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
        // 合并 <40KB 的小 chunk，减少碎 chunk 产生的额外 HTTP 请求
        experimentalMinChunkSize: 40960,
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
          // 图谱（react-force-graph-2d 及其依赖链：之前 "force-graph" 子串不匹配 "react-force-graph-2d"，
          // 导致图谱代码散落到默认 chunk 无法跨页缓存。补全依赖链 + 删不存在的 @nivo/three 死规则）
          if (
            id.includes("node_modules/react-force-graph-2d") ||
            id.includes("node_modules/force-graph") ||
            id.includes("node_modules/react-kapsule") ||
            id.includes("node_modules/kapsule") ||
            id.includes("node_modules/canvas-color-tracker") ||
            id.includes("node_modules/accessor-fn") ||
            id.includes("node_modules/index-array-by") ||
            id.includes("node_modules/bezier-js") ||
            id.includes("node_modules/float-tooltip") ||
            id.includes("node_modules/@tweenjs") ||
            id.includes("node_modules/d3")
          ) {
            return "graph-vendor";
          }
          // DOMPurify
          if (id.includes("node_modules/dompurify/")) {
            return "dompurify";
          }
        },
      },
    },
    chunkSizeWarningLimit: 400,
  },
});
