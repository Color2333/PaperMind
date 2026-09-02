"""
pm CLI 可执行入口（PyInstaller 打包 / python -m apps.cli 双用）
@author Color2333
"""

from apps.cli.main import app

if __name__ == "__main__":
    app(prog_name="pm")
