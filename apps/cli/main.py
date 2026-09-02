"""
PaperMind CLI 入口 —— pm 命令
登录（设备码授权 / 令牌粘贴）、登出、身份查看、连通性体检。

安装：pipx install /path/to/PaperMind  （或 uv tool install -e /path/to/PaperMind）
@author Color2333
"""

from __future__ import annotations

import time
import webbrowser

import typer

from apps.cli.client import ApiClient, ApiError
from apps.cli.config import (
    Config,
    clear_config,
    config_file,
    load_config,
    resolve_server_url,
    resolve_token,
    save_config,
)

app = typer.Typer(
    help="PaperMind CLI —— 命令行访问你的 PaperMind 实例",
    no_args_is_help=True,
    add_completion=False,
)

__version__ = "0.1.0"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pm {__version__}")
        raise typer.Exit


@app.callback()
def _main(
    version: bool | None = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True, help="显示版本"
    ),
) -> None:
    """PaperMind CLI"""


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


def _client(require_token: bool = True) -> ApiClient:
    server = resolve_server_url()
    if not server:
        _fail("未配置服务地址。先执行: pm login --server https://your-server.com")
    token = resolve_token()
    if require_token and not token:
        _fail("未登录。先执行: pm login")
    return ApiClient(server or "", token)


@app.command()
def login(
    token: str | None = typer.Option(
        None, "--token", help="直接粘贴已有令牌（SSH 等无浏览器环境用）"
    ),
    server: str | None = typer.Option(None, "--server", help="PaperMind 服务地址"),
    client_name: str = typer.Option("pm-cli", "--name", help="设备名称（授权页展示用）"),
) -> None:
    """登录 PaperMind（默认走设备码授权，类似 gh auth login）"""
    server_url = resolve_server_url(server)
    if not server_url:
        _fail("缺少服务地址，请加 --server https://your-server.com 或设置 PAPERMIND_SERVER_URL")

    if token:
        raw = token.strip()
        client = ApiClient(server_url, raw)
        try:
            me = client.me()
        except ApiError as e:
            _fail(f"令牌验证失败：{e.message}")
        _save_and_greet(server_url, raw, client_name, me)
        return

    # 设备码授权流程
    client = ApiClient(server_url)
    try:
        start = client.device_start(client_name)
    except ApiError as e:
        _fail(f"发起授权失败：{e.message}")

    typer.echo()
    typer.secho("  1. 在浏览器中打开并登录：", bold=True)
    typer.secho(f"     {start['verification_url']}", fg=typer.colors.CYAN)
    typer.secho("  2. 确认设备码：", bold=True)
    typer.secho(f"     {start['user_code']}", fg=typer.colors.CYAN, bold=True)
    typer.echo()

    if typer.confirm("现在打开浏览器？", default=True):
        webbrowser.open(start["verification_url"])

    typer.echo("等待授权中（按 Ctrl+C 取消）...")
    interval = max(1, int(start.get("interval", 5)))
    deadline = time.monotonic() + max(30, int(start.get("expires_in", 900)))
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            poll = client.device_poll(start["device_code"])
        except ApiError as e:
            if e.status_code == 429:
                continue  # 轮询过快，下一个间隔重试
            _fail(f"轮询失败：{e.message}")
        status = poll.get("status")
        if status == "pending":
            continue
        if status == "approved" and poll.get("access_token"):
            authed = ApiClient(server_url, poll["access_token"])
            _save_and_greet(server_url, poll["access_token"], client_name, authed.me())
            return
        if status == "denied":
            _fail("授权被拒绝。")
        if status in ("expired", "delivered"):
            _fail("授权请求已过期，请重新执行 pm login。")
    _fail("等待授权超时，请重新执行 pm login。")


def _save_and_greet(server_url: str, token: str, client_name: str, me: dict) -> None:
    path = save_config(Config(server_url=server_url, token=token, client_name=client_name))
    _ok(f"✓ 已登录：{me.get('token_name') or me.get('sub') or 'papermind-user'}")
    scopes = ", ".join(me.get("scopes") or ["read", "write"])
    typer.echo(f"  权限: {scopes}")
    typer.echo(f"  配置: {path}")


@app.command()
def logout() -> None:
    """登出：吊销远端令牌并清除本地配置"""
    cfg = load_config()
    if not cfg:
        typer.echo("本地没有登录配置。")
        return
    client = ApiClient(cfg.server_url, cfg.token)
    try:
        me = client.me()
        token_id = me.get("token_id")
        if token_id:
            client.revoke_token(token_id)
            _ok("✓ 已吊销服务端令牌")
    except ApiError:
        typer.secho("! 服务端吊销失败（令牌可能已失效），继续清除本地配置", fg=typer.colors.YELLOW)
    clear_config()
    _ok(f"✓ 本地配置已清除（{config_file()}）")


@app.command()
def whoami() -> None:
    """查看当前登录身份与权限"""
    client = _client()
    try:
        me = client.me()
    except ApiError as e:
        if e.status_code == 401:
            _fail("令牌无效或已过期，请重新执行 pm login")
        _fail(e.message)
    typer.echo(f"服务:   {client.base_url}")
    typer.echo(f"身份:   {me.get('auth_method')}")
    if me.get("token_name"):
        typer.echo(f"令牌:   {me['token_name']} ({me.get('token_prefix')}…)")
    if me.get("scopes"):
        typer.echo(f"权限:   {', '.join(me['scopes'])}")


@app.command()
def doctor() -> None:
    """连通性体检：服务可达性、认证状态、令牌有效性"""
    server = resolve_server_url()
    if not server:
        _fail("未配置服务地址。先执行: pm login --server https://your-server.com")
    typer.echo(f"目标: {server}")

    client = ApiClient(server)
    try:
        client.health()
        _ok("✓ /health 正常")
    except ApiError as e:
        _fail(f"✗ /health 不可达：{e.message}")

    token = resolve_token()
    if not token:
        typer.secho("✗ 未登录（执行 pm login）", fg=typer.colors.RED)
        raise typer.Exit(1)
    authed = ApiClient(server, token)
    try:
        me = authed.me()
        _ok(f"✓ 认证有效：{me.get('auth_method')}，权限 {', '.join(me.get('scopes') or [])}")
    except ApiError as e:
        if e.status_code == 401:
            _fail("✗ 令牌无效或已吊销，请重新执行 pm login")
        _fail(f"✗ 认证检查失败：{e.message}")


if __name__ == "__main__":
    app()
