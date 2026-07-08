"""
认知重构(PaperSenseMaking) AI 生成服务
驱动「理解 → 碰撞 → 重构」三幕的 LLM 生成，落库到 SensemakingSession。

@author Color2333
"""

from __future__ import annotations

import logging

from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import (
    build_act1_prompt,
    build_act2_prompt,
    build_act3_prompt,
)
from packages.config import get_settings
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import SensemakingSession, UserSchema
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)


class SensemakingService:
    """认知重构三幕 AI 生成"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm = LLMClient()
        self.pdf_extractor = PdfTextExtractor()

    # ---------- 公开入口 ----------

    def generate_act1(self, session_id: str) -> dict:
        """生成 Act1「理解」并落库，返回更新后的 session dict"""
        ctx = self._load_context(session_id, need_paper=True)
        prompt = build_act1_prompt(
            paper_title=ctx["paper_title"],
            paper_abstract=ctx["paper_abstract"],
            full_text=ctx["full_text"],
            user_schema=ctx["user_schema"],
        )
        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        parsed = result.parsed_json or {"summary": "生成失败，请重试", "key_findings": []}
        # 前端契约：act1 包 comprehension 包装层
        act1_data = {"comprehension": self._normalize_act1(parsed)}

        self._persist(
            session_id,
            act1_comprehension=act1_data,
            trace_result=result,
            trace_stage="sensemaking_act1",
            trace_digest=prompt,
            paper_id=ctx["paper_id"],
        )
        return self._session_dict(session_id)

    def generate_act2(self, session_id: str) -> dict:
        """生成 Act2「碰撞」并落库，返回更新后的 session dict"""
        ctx = self._load_context(session_id, need_paper=True, need_act1=True)
        prompt = build_act2_prompt(
            paper_title=ctx["paper_title"],
            paper_abstract=ctx["paper_abstract"],
            full_text=ctx["full_text"],
            user_schema=ctx["user_schema"],
            act1_result=ctx["act1"],
        )
        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        parsed = result.parsed_json or {"conflicts": [], "questions": []}
        # 前端契约：act2 包 collision 包装层
        act2_data = {"collision": self._normalize_act2(parsed)}

        self._persist(
            session_id,
            act2_collision=act2_data,
            trace_result=result,
            trace_stage="sensemaking_act2",
            trace_digest=prompt,
            paper_id=ctx["paper_id"],
        )
        return self._session_dict(session_id)

    def generate_act3(self, session_id: str) -> dict:
        """生成 Act3「重构」并落库，置 status=completed，返回更新后的 session dict"""
        from datetime import UTC, datetime

        ctx = self._load_context(session_id, need_act1=True, need_act2=True)
        prompt = build_act3_prompt(
            paper_title=ctx["paper_title"],
            user_schema=ctx["user_schema"],
            act1_result=ctx["act1"],
            act2_result=ctx["act2"],
        )
        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        parsed = result.parsed_json or {
            "before": "",
            "after": "",
            "delta": "",
            "one_change": "生成失败，请重试",
        }
        # 前端契约：act3 裸无包装层
        act3_data = self._normalize_act3(parsed)

        with session_scope() as session:
            session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
            if not session_obj:
                raise ValueError(f"Session {session_id} not found")
            session_obj.act3_reconstruction = act3_data
            session_obj.status = "completed"
            session_obj.completed_at = datetime.now(UTC)
            session.commit()
        self.llm.trace_result(
            result,
            stage="sensemaking_act3",
            prompt_digest=prompt[:500],
            paper_id=ctx["paper_id"],
        )
        return self._session_dict(session_id)

    # ---------- 内部工具 ----------

    def _load_context(
        self,
        session_id: str,
        *,
        need_paper: bool = False,
        need_act1: bool = False,
        need_act2: bool = False,
    ) -> dict:
        """从 DB 取 session、user_schema、paper，并提取全文"""
        with session_scope() as session:
            session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
            if not session_obj:
                raise ValueError(f"Session {session_id} not found")

            schema = session.query(UserSchema).filter_by(id=session_obj.user_schema_id).first()
            if not schema:
                raise ValueError(f"UserSchema {session_obj.user_schema_id} not found")

            ctx = {
                "session_id": session_id,
                "paper_id": session_obj.paper_id,
                "user_schema": {
                    "research_topics": schema.research_topics or [],
                    "academic_level": schema.academic_level,
                    "current_challenges": schema.current_challenges or [],
                    "beliefs": schema.beliefs or [],
                    "knowledge_gaps": schema.knowledge_gaps or [],
                },
                "act1": session_obj.act1_comprehension or {},
                "act2": session_obj.act2_collision or {},
            }

            if need_paper:
                paper_id = session_obj.paper_id
                try:
                    # paper_id 在 sensemaking 表无 FK，需自己校验存在性
                    import uuid

                    paper = PaperRepository(session).get_by_id(uuid.UUID(paper_id))
                    ctx["paper_title"] = paper.title
                    ctx["paper_abstract"] = paper.abstract or ""
                    ctx["pdf_path"] = paper.pdf_path
                except Exception as exc:
                    raise ValueError(f"Paper {session_obj.paper_id} not found: {exc}") from exc

        if need_paper:
            ctx["full_text"] = ""
            pdf_path = ctx.get("pdf_path")
            if pdf_path:
                ctx["full_text"] = self.pdf_extractor.extract_text(pdf_path, max_pages=12)

        if need_act1 and not ctx["act1"]:
            raise ValueError("Act1 尚未生成，请先生成 Act1")
        if need_act2 and not ctx["act2"]:
            raise ValueError("Act2 尚未生成，请先生成 Act2")

        return ctx

    def _persist(
        self,
        session_id: str,
        *,
        act1_comprehension: dict | None = None,
        act2_collision: dict | None = None,
        trace_result,
        trace_stage: str,
        trace_digest: str,
        paper_id: str,
    ) -> None:
        """落库 act 结果并 trace 成本"""
        with session_scope() as session:
            session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
            if not session_obj:
                raise ValueError(f"Session {session_id} not found")
            if act1_comprehension is not None:
                session_obj.act1_comprehension = act1_comprehension
            if act2_collision is not None:
                session_obj.act2_collision = act2_collision
            session.commit()
        self.llm.trace_result(
            trace_result,
            stage=trace_stage,
            prompt_digest=trace_digest[:500],
            paper_id=paper_id,
        )

    def _session_dict(self, session_id: str) -> dict:
        """返回前端期望的 session dict 结构"""
        with session_scope() as session:
            s = session.query(SensemakingSession).filter_by(id=session_id).first()
            if not s:
                raise ValueError(f"Session {session_id} not found")
            return {
                "id": s.id,
                "paper_id": s.paper_id,
                "user_schema_id": s.user_schema_id,
                "act1_comprehension": s.act1_comprehension,
                "act2_collision": s.act2_collision,
                "act3_reconstruction": s.act3_reconstruction,
                "status": s.status,
                "conversation_history": s.conversation_history,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "completed_at": s.completed_at,
            }

    @staticmethod
    def _normalize_act1(parsed: dict) -> dict:
        return {
            "summary": str(parsed.get("summary", "")),
            "key_findings": [str(f) for f in (parsed.get("key_findings") or [])],
        }

    @staticmethod
    def _normalize_act2(parsed: dict) -> dict:
        return {
            "conflicts": [str(c) for c in (parsed.get("conflicts") or [])],
            "questions": [str(q) for q in (parsed.get("questions") or [])],
        }

    @staticmethod
    def _normalize_act3(parsed: dict) -> dict:
        return {
            "before": str(parsed.get("before", "")),
            "after": str(parsed.get("after", "")),
            "delta": str(parsed.get("delta", "")),
            "one_change": str(parsed.get("one_change", "")),
        }
