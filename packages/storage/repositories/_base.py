"""
基础查询类
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.orm import Session


class BaseQuery:
    """
    基础查询类 - 提供通用的查询方法减少重复代码
    """

    def __init__(self, session: Session):
        self.session = session

    def _paginate(self, query: Select, page: int, page_size: int) -> Select:
        """
        添加分页到查询

        Args:
            query: SQLAlchemy 查询对象
            page: 页码（从 1 开始）
            page_size: 每页大小

        Returns:
            添加了分页的查询对象
        """
        offset = (max(1, page) - 1) * page_size
        return query.offset(offset).limit(page_size)

    def _execute_paginated(
        self, query: Select, page: int = 1, page_size: int = 20
    ) -> tuple[list, int]:
        """
        执行分页查询，返回 (结果列表, 总数)

        Args:
            query: SQLAlchemy 查询对象
            page: 页码（从 1 开始）
            page_size: 每页大小

        Returns:
            (结果列表, 总数)
        """
        count_query = select(func.count()).select_from(query.alias())
        total = self.session.execute(count_query).scalar() or 0

        paginated_query = self._paginate(query, page, page_size)
        results = list(self.session.execute(paginated_query).scalars())

        return results, total
