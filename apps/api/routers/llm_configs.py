"""
LLM 模型管理路由 - 配置管理 + 场景化切换
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.storage.db import session_scope
from packages.storage.repositories import LLMConfigRepository

router = APIRouter(prefix="/llm-configs", tags=["llm-configs"])


class LLMConfigItem(BaseModel):
    id: str
    name: str
    provider: str
    api_base_url: str | None
    model_skim: str
    model_deep: str
    model_vision: str | None
    model_embedding: str
    model_fallback: str
    is_active: bool


class LLMConfigCreate(BaseModel):
    name: str = Field(..., description="配置名称")
    provider: str = Field(..., description="提供商：zhipu/openai/anthropic/siliconflow")
    api_key: str = Field(..., description="API Key")
    api_base_url: str | None = Field(None, description="自定义 API Base URL")
    model_skim: str = Field(..., description="粗读/简单任务模型")
    model_deep: str = Field(..., description="精读/复杂任务模型")
    model_vision: str | None = Field(None, description="视觉模型")
    model_embedding: str = Field(..., description="嵌入模型")
    model_fallback: str = Field(..., description="降级备用模型")


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model_skim: str | None = None
    model_deep: str | None = None
    model_vision: str | None = None
    model_embedding: str | None = None
    model_fallback: str | None = None


class LLMConfigActivate(BaseModel):
    config_id: str


class LLMConfigList(BaseModel):
    configs: list[LLMConfigItem]
    active_id: str | None


class LLMConfigDetail(BaseModel):
    config: LLMConfigItem


@router.get("", response_model=LLMConfigList)
def list_configs():
    """获取所有 LLM 配置列表"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        configs = repo.list_all()
        active_cfg = repo.get_active()
        return LLMConfigList(
            configs=[
                LLMConfigItem(
                    id=c.id,
                    name=c.name,
                    provider=c.provider,
                    api_base_url=c.api_base_url,
                    model_skim=c.model_skim,
                    model_deep=c.model_deep,
                    model_vision=c.model_vision,
                    model_embedding=c.model_embedding,
                    model_fallback=c.model_fallback,
                    is_active=c.is_active,
                )
                for c in configs
            ],
            active_id=active_cfg.id if active_cfg else None,
        )


@router.get("/{config_id}", response_model=LLMConfigDetail)
def get_config(config_id: str):
    """获取单个配置详情"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        try:
            cfg = repo.get_by_id(config_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return LLMConfigDetail(
            config=LLMConfigItem(
                id=cfg.id,
                name=cfg.name,
                provider=cfg.provider,
                api_base_url=cfg.api_base_url,
                model_skim=cfg.model_skim,
                model_deep=cfg.model_deep,
                model_vision=cfg.model_vision,
                model_embedding=cfg.model_embedding,
                model_fallback=cfg.model_fallback,
                is_active=cfg.is_active,
            )
        )


@router.post("", response_model=LLMConfigDetail)
def create_config(req: LLMConfigCreate):
    """创建新的 LLM 配置"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        cfg = repo.create(
            name=req.name,
            provider=req.provider,
            api_key=req.api_key,
            api_base_url=req.api_base_url,
            model_skim=req.model_skim,
            model_deep=req.model_deep,
            model_vision=req.model_vision,
            model_embedding=req.model_embedding,
            model_fallback=req.model_fallback,
        )
        session.commit()
        return LLMConfigDetail(
            config=LLMConfigItem(
                id=cfg.id,
                name=cfg.name,
                provider=cfg.provider,
                api_base_url=cfg.api_base_url,
                model_skim=cfg.model_skim,
                model_deep=cfg.model_deep,
                model_vision=cfg.model_vision,
                model_embedding=cfg.model_embedding,
                model_fallback=cfg.model_fallback,
                is_active=cfg.is_active,
            )
        )


@router.patch("/{config_id}", response_model=LLMConfigDetail)
def update_config(config_id: str, req: LLMConfigUpdate):
    """更新配置"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        try:
            cfg = repo.update(
                config_id,
                name=req.name,
                provider=req.provider,
                api_key=req.api_key,
                api_base_url=req.api_base_url,
                model_skim=req.model_skim,
                model_deep=req.model_deep,
                model_vision=req.model_vision,
                model_embedding=req.model_embedding,
                model_fallback=req.model_fallback,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        session.commit()
        return LLMConfigDetail(
            config=LLMConfigItem(
                id=cfg.id,
                name=cfg.name,
                provider=cfg.provider,
                api_base_url=cfg.api_base_url,
                model_skim=cfg.model_skim,
                model_deep=cfg.model_deep,
                model_vision=cfg.model_vision,
                model_embedding=cfg.model_embedding,
                model_fallback=cfg.model_fallback,
                is_active=cfg.is_active,
            )
        )


@router.delete("/{config_id}")
def delete_config(config_id: str):
    """删除配置（不能删除当前激活的配置）"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        cfg = repo.get_by_id(config_id)
        if cfg.is_active:
            raise HTTPException(status_code=400, detail="不能删除当前激活的配置")
        repo.delete(config_id)
        session.commit()
        return {"message": "删除成功"}


@router.post("/activate", response_model=LLMConfigDetail)
def activate_config(req: LLMConfigActivate):
    """激活指定配置"""
    with session_scope() as session:
        repo = LLMConfigRepository(session)
        try:
            cfg = repo.activate(req.config_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        session.commit()
        return LLMConfigDetail(
            config=LLMConfigItem(
                id=cfg.id,
                name=cfg.name,
                provider=cfg.provider,
                api_base_url=cfg.api_base_url,
                model_skim=cfg.model_skim,
                model_deep=cfg.model_deep,
                model_vision=cfg.model_vision,
                model_embedding=cfg.model_embedding,
                model_fallback=cfg.model_fallback,
                is_active=cfg.is_active,
            )
        )
