"""学术写作助手路由（业务在 application/commands/writing.py）"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from packages.application.commands import writing as writing_commands
from packages.domain.exceptions import ValidationError
from packages.domain.schemas import (  # noqa: TC001 —— FastAPI 请求体运行期解析
    WritingMultimodalReq,
    WritingProcessReq,
    WritingRefineReq,
)

router = APIRouter()


@router.get("/writing/templates")
def writing_templates() -> dict:
    return {"items": writing_commands.list_templates()}


@router.post("/writing/process")
def writing_process(body: WritingProcessReq) -> dict:
    text = body.content.strip() or body.topic.strip()
    try:
        return writing_commands.process(action=body.action, text=text)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/writing/refine")
def writing_refine(body: WritingRefineReq) -> dict:
    try:
        return writing_commands.refine(messages=body.messages)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/writing/process-multimodal")
def writing_process_multimodal(body: WritingMultimodalReq) -> dict:
    try:
        return writing_commands.process_with_image(
            action=body.action, text=body.content.strip(), image_base64=body.image_base64
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
