# -*- coding: utf-8 -*-
"""视觉模块通用工具。

detector.py（车位检测）和 plate.py（车牌识别）共用这几个函数，
避免同一段代码在两个文件里各写一遍。

注意：本模块只依赖 cv2 / numpy / config，不导入 torch 或 paddle，
      可以安全地被任一进程导入。
"""
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import config as cfg


def imread_unicode(path: str) -> Optional[np.ndarray]:
    """读取图片，兼容 Windows 中文路径（cv2.imread 不支持非 ASCII 路径）。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def imwrite_unicode(path: str, image: np.ndarray) -> bool:
    """保存图片，同样兼容中文路径。"""
    try:
        ext = Path(path).suffix or ".jpg"
        ok, buf = cv2.imencode(ext, image)
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception:
        return False


def resolve_model(path: str) -> str:
    """优先使用 weights/ 下的本地权重，找不到再交给 ultralytics 自动下载。"""
    p = Path(path)
    if p.is_absolute() and p.exists():
        return str(p)
    local = cfg.WEIGHT_DIR / p.name
    if local.exists():
        return str(local)
    if Path(p.name).exists():
        return str(Path(p.name).resolve())
    return path
