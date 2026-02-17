/**
 * 统一 Markdown 渲染组件（含 LaTeX 支持）
 * @author Bamzc
 */
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

interface Props {
  children: string;
  className?: string;
}

/**
 * 带 GFM + LaTeX 的 Markdown 渲染
 */
const Markdown = memo(function Markdown({ children, className }: Props) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});

export default Markdown;
