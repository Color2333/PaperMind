"""生成产物命令（B7；写路径，B8 起统一命令面）"""

from __future__ import annotations


def save_generated_content(
    session,
    *,
    content_type: str,
    title: str,
    markdown: str,
    keyword: str | None = None,
    paper_id: str | None = None,
    metadata_json: dict | None = None,
) -> str:
    """写入 generated_contents，返回 id"""
    from packages.storage.repositories import GeneratedContentRepository

    gc = GeneratedContentRepository(session).create(
        content_type=content_type,
        title=title,
        markdown=markdown,
        keyword=keyword,
        paper_id=paper_id,
        metadata_json=metadata_json,
    )
    return gc.id
