"""
翻译 API - 段落对照翻译
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.services.translate import translate_segments, translate_text

router = APIRouter(prefix="/translate", tags=["translate"])


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh"


class TranslateResponse(BaseModel):
    original: str
    translation: str


class SegmentTranslationItem(BaseModel):
    id: str
    type: str
    content: str
    translation: str | None = None


@router.post("/selection", response_model=TranslateResponse)
def translate_selection(req: TranslateRequest):
    try:
        translation = translate_text(req.text, req.target_lang)
        return TranslateResponse(original=req.text, translation=translation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/segments")
def translate_segments_endpoint(segments: list[SegmentTranslationItem], target_lang: str = "zh"):
    try:
        seg_dicts = [s.model_dump() for s in segments]
        results = translate_segments(seg_dicts, target_lang)
        return {"segments": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
