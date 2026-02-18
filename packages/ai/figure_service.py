"""
图表/公式智能识别与解读服务
从 PDF 中提取 Figure/Table/公式区域，送 Vision 模型解读
@author Bamzc
"""
from __future__ import annotations

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.db import session_scope
from packages.storage.models import ImageAnalysis
from packages.storage.repositories import PromptTraceRepository

logger = logging.getLogger(__name__)

VISION_PROMPT_FIGURE = """\
你是一个学术论文图表解读专家。请仔细分析这张图片，它来自一篇学术论文的第 {page} 页。

请提供以下内容（中文回答）：
1. **图表类型**：这是什么类型的图表（架构图/流程图/折线图/柱状图/表格/公式/示意图等）
2. **核心内容**：图表展示了什么信息，主要结论是什么
3. **关键数据**：如果有数据，提取关键数值和趋势
4. **方法解读**：如果是架构图或流程图，描述各模块的作用和数据流向
5. **学术意义**：这张图在论文中可能的作用和重要性

{caption_hint}

请用简洁专业的语言回答，使用 Markdown 格式。"""

VISION_PROMPT_TABLE = """\
你是一个学术论文表格解读专家。请仔细分析这张表格图片，它来自一篇学术论文的第 {page} 页。

请提供以下内容（中文回答）：
1. **表格内容**：表格展示了什么数据/对比
2. **关键发现**：最重要的数据点和结论
3. **对比分析**：不同方法/模型之间的性能差异
4. **最优结果**：表中最好的结果是什么，用什么方法达到的

{caption_hint}

请用简洁专业的语言回答，使用 Markdown 格式。"""


@dataclass
class ExtractedFigure:
    """从 PDF 中提取的图片"""
    page_number: int
    image_index: int
    image_bytes: bytes
    image_type: str  # figure / table / equation
    caption: str
    bbox: dict | None


@dataclass
class FigureAnalysis:
    """图表解读结果"""
    page_number: int
    image_index: int
    image_type: str
    caption: str
    description: str
    bbox: dict | None


class FigureService:
    """图表提取与 Vision 解读"""

    def __init__(self) -> None:
        self.llm = LLMClient()

    def extract_figures(
        self, pdf_path: str, max_figures: int = 20,
    ) -> list[ExtractedFigure]:
        """从 PDF 提取图片区域"""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        try:
            import fitz  # type: ignore
        except ImportError:
            logger.warning("PyMuPDF not installed, cannot extract figures")
            return []

        doc = fitz.open(pdf_path)
        figures: list[ExtractedFigure] = []

        for page_idx in range(len(doc)):
            if len(figures) >= max_figures:
                break

            page = doc.load_page(page_idx)
            page_text = page.get_text("text")
            images = page.get_images(full=True)

            for img_idx, img_info in enumerate(images):
                if len(figures) >= max_figures:
                    break

                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                except Exception:
                    continue

                # 过滤太小的图片（可能是 icon/logo）
                if pix.width < 100 or pix.height < 80:
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    continue

                # 转 PNG bytes
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img_bytes = pix.tobytes("png")

                # 尝试提取 caption
                caption = self._extract_caption(page_text, page_idx + 1, img_idx)

                # 推断类型
                img_type = self._infer_type(caption, page_text)

                figures.append(ExtractedFigure(
                    page_number=page_idx + 1,
                    image_index=img_idx,
                    image_bytes=img_bytes,
                    image_type=img_type,
                    caption=caption,
                    bbox=None,
                ))

        doc.close()

        # 如果直接提取图片数量不足，尝试对包含 Figure/Table 的页面做整页截图
        if len(figures) == 0:
            figures = self._extract_page_renders(pdf_path, max_figures)

        return figures

    def _extract_page_renders(
        self, pdf_path: str, max_pages: int = 10,
    ) -> list[ExtractedFigure]:
        """对包含图表内容的页面做整页高分辨率渲染"""
        try:
            import fitz  # type: ignore
        except ImportError:
            return []

        doc = fitz.open(pdf_path)
        figures: list[ExtractedFigure] = []

        for page_idx in range(min(len(doc), max_pages + 2)):
            if len(figures) >= max_pages:
                break

            page = doc.load_page(page_idx)
            page_text = page.get_text("text").lower()

            # 只渲染包含图表/公式的页面
            has_figure = bool(re.search(
                r"(figure\s*\d|fig\.\s*\d|table\s*\d|tab\.\s*\d"
                r"|equation\s*\d|algorithm\s*\d)",
                page_text, re.IGNORECASE,
            ))
            if not has_figure and page_idx > 1:
                continue

            # 高分辨率渲染
            mat = fitz.Matrix(2.0, 2.0)  # 2x 缩放
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")

            caption = self._extract_caption(page.get_text("text"), page_idx + 1, 0)
            img_type = self._infer_type(caption, page.get_text("text"))

            figures.append(ExtractedFigure(
                page_number=page_idx + 1,
                image_index=0,
                image_bytes=img_bytes,
                image_type=img_type,
                caption=caption or f"Page {page_idx + 1}",
                bbox=None,
            ))

        doc.close()
        return figures

    @staticmethod
    def _extract_caption(page_text: str, page_num: int, img_idx: int) -> str:
        """从页面文本中提取图表 caption"""
        patterns = [
            r"(Figure\s*\d+[.:]\s*[^\n]{10,120})",
            r"(Fig\.\s*\d+[.:]\s*[^\n]{10,120})",
            r"(Table\s*\d+[.:]\s*[^\n]{10,120})",
            r"(Tab\.\s*\d+[.:]\s*[^\n]{10,120})",
            r"(Algorithm\s*\d+[.:]\s*[^\n]{10,120})",
        ]
        found: list[str] = []
        for pat in patterns:
            found.extend(re.findall(pat, page_text, re.IGNORECASE))
        if found:
            # 返回与 img_idx 对应或第一个
            idx = min(img_idx, len(found) - 1)
            return found[idx].strip()
        return ""

    @staticmethod
    def _infer_type(caption: str, page_text: str) -> str:
        """推断图表类型"""
        lower = (caption or "").lower()
        if "table" in lower or "tab." in lower:
            return "table"
        if "algorithm" in lower:
            return "algorithm"
        if "equation" in lower or "formula" in lower:
            return "equation"
        return "figure"

    def analyze_figure(self, figure: ExtractedFigure) -> FigureAnalysis:
        """用 Vision 模型解读单张图表"""
        b64 = base64.b64encode(figure.image_bytes).decode("utf-8")
        caption_hint = f"图表标题: {figure.caption}" if figure.caption else "未检测到标题"

        if figure.image_type == "table":
            prompt = VISION_PROMPT_TABLE.format(page=figure.page_number, caption_hint=caption_hint)
        else:
            prompt = VISION_PROMPT_FIGURE.format(page=figure.page_number, caption_hint=caption_hint)

        result: LLMResult = self.llm.vision_analyze(
            image_base64=b64,
            prompt=prompt,
            stage="vision_figure",
            max_tokens=1024,
        )

        # 记录 token 消耗
        try:
            with session_scope() as session:
                cfg = self.llm._config()
                PromptTraceRepository(session).create(
                    stage="vision_figure",
                    provider=self.llm.provider,
                    model=cfg.model_vision or cfg.model_deep,
                    prompt_digest=f"page={figure.page_number} caption={figure.caption[:100]}",
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
        except Exception:
            pass

        description = self._clean_markdown_fences(result.content)

        return FigureAnalysis(
            page_number=figure.page_number,
            image_index=figure.image_index,
            image_type=figure.image_type,
            caption=figure.caption,
            description=description,
            bbox=figure.bbox,
        )

    @staticmethod
    def _clean_markdown_fences(text: str) -> str:
        """去除 LLM 输出中多余的 markdown code fence 包裹"""
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            # 去掉首行 ```markdown / ```json 等
            if lines[0].startswith("```"):
                lines = lines[1:]
            # 去掉末行 ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return stripped

    def analyze_paper_figures(
        self,
        paper_id: UUID,
        pdf_path: str,
        max_figures: int = 10,
    ) -> list[FigureAnalysis]:
        """提取并解读论文中的所有图表，结果存库"""
        figures = self.extract_figures(pdf_path, max_figures=max_figures)
        if not figures:
            logger.info("No figures found in %s", pdf_path)
            return []

        def _analyze_one(fig: ExtractedFigure) -> FigureAnalysis | None:
            try:
                analysis = self.analyze_figure(fig)
                logger.info(
                    "Analyzed %s on page %d: %s",
                    fig.image_type, fig.page_number,
                    analysis.description[:80],
                )
                return analysis
            except Exception as exc:
                logger.warning(
                    "Failed to analyze figure on page %d: %s",
                    fig.page_number, exc,
                )
                return None

        results: list[FigureAnalysis] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_analyze_one, fig): fig
                for fig in figures
            }
            for future in as_completed(futures):
                r = future.result()
                if r is not None:
                    results.append(r)
        results.sort(key=lambda a: (a.page_number, a.image_index))

        # 存入数据库
        self._save_analyses(paper_id, results)
        return results

    @staticmethod
    def _save_analyses(paper_id: UUID, analyses: list[FigureAnalysis]) -> None:
        """将解读结果持久化"""
        with session_scope() as session:
            # 清除该论文旧的解读
            session.execute(
                ImageAnalysis.__table__.delete().where(
                    ImageAnalysis.paper_id == str(paper_id)
                )
            )
            for a in analyses:
                session.add(ImageAnalysis(
                    id=str(uuid4()),
                    paper_id=str(paper_id),
                    page_number=a.page_number,
                    image_index=a.image_index,
                    image_type=a.image_type,
                    caption=a.caption,
                    description=a.description,
                    bbox_json=a.bbox,
                ))

    @classmethod
    def get_paper_analyses(cls, paper_id: UUID) -> list[dict]:
        """获取论文已有的图表解读"""
        with session_scope() as session:
            from sqlalchemy import select
            q = (
                select(ImageAnalysis)
                .where(ImageAnalysis.paper_id == str(paper_id))
                .order_by(ImageAnalysis.page_number, ImageAnalysis.image_index)
            )
            rows = list(session.execute(q).scalars())
            return [
                {
                    "id": r.id,
                    "page_number": r.page_number,
                    "image_index": r.image_index,
                    "image_type": r.image_type,
                    "caption": r.caption,
                    "description": cls._clean_markdown_fences(r.description or ""),
                }
                for r in rows
            ]
