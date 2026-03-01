"""
认证路由 - 登录接口
@author Color2333
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.auth import authenticate_user, create_access_token
from packages.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthStatusResponse(BaseModel):
    auth_enabled: bool


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    站点密码登录
    成功返回 JWT token
    """
    settings = get_settings()
    
    # 如果未配置密码，返回错误
    if not settings.auth_password:
        raise HTTPException(status_code=403, detail="Authentication is disabled")
    
    # 验证密码
    if not authenticate_user(request.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    
    # 生成 token
    access_token = create_access_token(data={"sub": "papermind-user"})
    return LoginResponse(access_token=access_token)


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status():
    """
    检查认证是否启用
    """
    settings = get_settings()
    return AuthStatusResponse(auth_enabled=bool(settings.auth_password))