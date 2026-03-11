#!/usr/bin/env python3
"""
PaperMind 开发环境一键初始化脚本

功能：
- 检查 Python 版本
- 创建虚拟环境
- 安装依赖
- 复制环境变量配置
- 初始化数据库

使用方法：
    python scripts/dev_setup.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


# 颜色输出
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def print_step(step: str):
    """打印步骤信息"""
    print(f"\n{Colors.BLUE}▶ {step}{Colors.NC}")


def print_success(msg: str):
    """打印成功信息"""
    print(f"{Colors.GREEN}✓ {msg}{Colors.NC}")


def print_error(msg: str):
    """打印错误信息"""
    print(f"{Colors.RED}✗ {msg}{Colors.NC}", file=sys.stderr)


def print_warning(msg: str):
    """打印警告信息"""
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")


def run_command(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    """运行命令并返回结果"""
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def check_python_version():
    """检查 Python 版本"""
    print_step("检查 Python 版本")

    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print_error(f"Python 版本过低: {version.major}.{version.minor}")
        print_error("需要 Python 3.11 或更高版本")
        sys.exit(1)

    print_success(f"Python 版本: {version.major}.{version.minor}.{version.micro}")


def create_venv(project_root: Path):
    """创建虚拟环境"""
    venv_path = project_root / ".venv"

    print_step("创建虚拟环境")

    if venv_path.exists():
        print_warning("虚拟环境已存在，跳过创建")
        return

    run_command([sys.executable, "-m", "venv", str(venv_path)])
    print_success(f"虚拟环境创建成功: {venv_path}")


def install_dependencies(project_root: Path):
    """安装依赖"""
    print_step("安装 Python 依赖")

    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"  # Windows

    # 升级 pip
    run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])

    # 安装项目依赖
    run_command([str(venv_python), "-m", "pip", "install", "-e", ".[llm,pdf]"])

    print_success("依赖安装完成")


def setup_env_file(project_root: Path):
    """设置环境变量文件"""
    print_step("配置环境变量")

    env_example = project_root / ".env.example"
    env_file = project_root / ".env"

    if env_file.exists():
        print_warning(".env 文件已存在，跳过复制")
        return

    if not env_example.exists():
        print_error(".env.example 文件不存在")
        sys.exit(1)

    shutil.copy(env_example, env_file)
    print_success(".env 文件已创建")
    print_warning("请编辑 .env 文件，填写必要的配置项（如 LLM API Key）")


def init_database(project_root: Path):
    """初始化数据库"""
    print_step("初始化数据库")

    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"  # Windows

    bootstrap_script = project_root / "scripts" / "local_bootstrap.py"

    if not bootstrap_script.exists():
        print_warning("local_bootstrap.py 不存在，跳过数据库初始化")
        return

    result = run_command([str(venv_python), str(bootstrap_script)], check=False)

    if result.returncode == 0:
        print_success("数据库初始化完成")
    else:
        print_warning("数据库初始化失败，可能已存在")


def main():
    """主函数"""
    print(f"""
{Colors.BLUE}╔══════════════════════════════════════════╗
║     PaperMind 开发环境初始化             ║
╚══════════════════════════════════════════╝{Colors.NC}
""")

    # 获取项目根目录
    project_root = Path(__file__).parent.parent.absolute()
    os.chdir(project_root)

    # 执行初始化步骤
    check_python_version()
    create_venv(project_root)
    install_dependencies(project_root)
    setup_env_file(project_root)
    init_database(project_root)

    print(f"""
{Colors.GREEN}╔══════════════════════════════════════════╗
║          初始化完成！                    ║
╚══════════════════════════════════════════╝{Colors.NC}

下一步：
  1. 编辑 .env 文件，填写 LLM API Key
  2. 激活虚拟环境：
     - macOS/Linux: source .venv/bin/activate
     - Windows: .venv\\Scripts\\activate
  3. 启动后端：
     uvicorn apps.api.main:app --reload --port 8000
  4. 启动前端：
     cd frontend && npm install && npm run dev

API 文档: http://localhost:8000/docs
""")


if __name__ == "__main__":
    main()
