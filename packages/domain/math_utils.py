"""
向量数学工具函数
@author Bamzc
"""
import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度 [0, 1]"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cosine_distance(a: list[float], b: list[float]) -> float:
    """余弦距离 [0, 2]"""
    return 1.0 - cosine_similarity(a, b)
