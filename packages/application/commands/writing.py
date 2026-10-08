"""学术写作命令（B8 后期，设计② WritingAssist）"""

from __future__ import annotations

from typing import Any

from packages.domain.exceptions import ValidationError


def list_templates() -> list[dict[str, Any]]:
    from packages.ai.writing_service import WritingService

    return WritingService.list_templates()


def process(action: str, text: str) -> dict[str, Any]:
    from packages.ai.writing_service import WritingService

    if not action:
        raise ValidationError("action is required")
    if not text:
        raise ValidationError("text/content is required")
    try:
        return WritingService().process(action, text)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def refine(messages: list[dict[str, Any]]) -> dict[str, Any]:
    from packages.ai.writing_service import WritingService

    if not messages:
        raise ValidationError("messages is required")
    try:
        return WritingService().refine(messages)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def process_with_image(*, action: str, text: str, image_base64: str) -> dict[str, Any]:
    from packages.ai.writing_service import WritingService

    if not image_base64:
        raise ValidationError("image_base64 is required")
    try:
        return WritingService().process_with_image(
            action=action, text=text, image_base64=image_base64
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
