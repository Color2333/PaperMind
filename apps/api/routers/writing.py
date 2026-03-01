"""学术写作助手路由
@author Color2333
"""

from fastapi import APIRouter, HTTPException

from packages.domain.schemas import WritingMultimodalReq, WritingProcessReq, WritingRefineReq

router = APIRouter()


@router.get("/writing/templates")
def writing_templates() -> dict:
    """获取所有写作模板列表"""
    from packages.ai.writing_service import WritingService

    return {"items": WritingService.list_templates()}


@router.post("/writing/process")
def writing_process(body: WritingProcessReq) -> dict:
    """执行写作操作"""
    from packages.ai.writing_service import WritingService

    action = body.action
    text = body.content.strip() or body.topic.strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    if not text:
        raise HTTPException(status_code=400, detail="text/content is required")
    try:
        return WritingService().process(action, text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/writing/refine")
def writing_refine(body: WritingRefineReq) -> dict:
    """基于对话历史多轮微调"""
    from packages.ai.writing_service import WritingService

    messages = body.messages
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")
    try:
        return WritingService().refine(messages)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/writing/process-multimodal")
def writing_process_multimodal(body: WritingMultimodalReq) -> dict:
    """多模态写作操作（图片 + 文本）"""
    from packages.ai.writing_service import WritingService

    if not body.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    try:
        return WritingService().process_with_image(
            action=body.action,
            text=body.content.strip(),
            image_base64=body.image_base64,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
