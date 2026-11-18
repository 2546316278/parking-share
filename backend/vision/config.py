# -*- coding: utf-8 -*-
"""
视觉模块全局配置。

所有可调参数集中在这里，避免散落在各脚本中。
调参时只改这一个文件，便于在论文里说明实验设置。
"""
import os
from pathlib import Path

# ==================== 路径 ====================
# 本文件在 backend/vision/ 下，项目根 = 上两级
VISION_DIR = Path(__file__).resolve().parent
BACKEND_DIR = VISION_DIR.parent
BASE_DIR = BACKEND_DIR.parent

DATA_DIR = BASE_DIR / "data"
VIDEO_DIR = DATA_DIR / "videos"
CALIB_DIR = DATA_DIR / "calibrations"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SAMPLE_DIR = DATA_DIR / "samples"
WEIGHT_DIR = BASE_DIR / "weights"

for _d in (VIDEO_DIR, CALIB_DIR, SNAPSHOT_DIR, SAMPLE_DIR, WEIGHT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ==================== 检测参数 ====================
# 模型路径：可填 "yolov8n.pt"（自动下载）或本地权重绝对路径
YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
IMG_SIZE = 640
CONF_THRESHOLD = 0.35      # 车辆检测置信度下限
IOU_NMS = 0.45

# COCO 数据集中与车辆相关的类别编号
# 2=car 3=motorcycle 5=bus 7=truck
VEHICLE_CLASSES = [2, 3, 5, 7]
CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# ==================== 车位占用判定 ====================
# 车辆框落在车位多边形内的面积 / 车位多边形面积，超过该值判为占用
COVERAGE_THRESHOLD = 0.35
# 过滤过小的检测框（像素面积），避免把远处行人误判成车辆
MIN_VEHICLE_AREA = 400

# ==================== 时序平滑 ====================
SMOOTH_WINDOW = 5          # 滑动窗口长度（帧）
SMOOTH_MIN_VOTES = 3       # 窗口内至少几帧一致才确认状态切换

# ==================== 可视化配色（OpenCV 为 BGR 顺序） ====================
COLOR_FREE = (80, 200, 80)        # 绿：空闲
COLOR_OCCUPIED = (60, 60, 220)    # 红：占用
COLOR_UNKNOWN = (150, 150, 150)   # 灰：未知
COLOR_VEHICLE = (0, 200, 255)     # 橙：检测到的车辆框

# ==================== 状态常量 ====================
STATUS_FREE = "free"
STATUS_OCCUPIED = "occupied"
STATUS_UNKNOWN = "unknown"

STATUS_TEXT = {
    STATUS_FREE: "FREE",
    STATUS_OCCUPIED: "OCC",
    STATUS_UNKNOWN: "UNK",
}
STATUS_COLOR = {
    STATUS_FREE: COLOR_FREE,
    STATUS_OCCUPIED: COLOR_OCCUPIED,
    STATUS_UNKNOWN: COLOR_UNKNOWN,
}
