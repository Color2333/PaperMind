"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化 / 参考文献导入
@author Color2333
"""

from packages.ai.pipelines.paper_pipelines import PaperPipelines
from packages.ai.pipelines.reference_import import ReferenceImporter

__all__ = ["PaperPipelines", "ReferenceImporter"]
