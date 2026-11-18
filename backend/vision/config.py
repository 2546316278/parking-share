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

# ==================== 车牌识别（入口抓拍） ====================
# 车牌检测权重：区分单层 / 双层车牌的 YOLOv8 模型
PLATE_MODEL = os.getenv("PLATE_MODEL", "LP-detection.pt")
PLATE_CONF = 0.35          # 车牌检测置信度下限
# 兜底阈值：第一轮没检到车牌时，降到此值重试。
# CCPD 里倾斜、模糊、逆光的样本在 0.35 下常被判为 0 个目标，
# 降到 0.12 能救回来，误检由车牌格式校验负责过滤
PLATE_CONF_FALLBACK = 0.12
PLATE_OCR_CONF = 0.55      # OCR 字符置信度下限，低于此值的行直接丢弃

# 车牌宽高比过滤。中国单层车牌 440x140 ≈ 3.14，双层车牌接近 2.0。
# 低阈值兜底容易把整个车身框成"车牌"（实测出现过 720x436 的框），
# 宽高比落在区间外的直接判为误检
PLATE_ASPECT_MIN = 1.6
PLATE_ASPECT_MAX = 6.0

# 车牌裁剪图高度低于该值时先放大再送 OCR。
# 实测 79x30 的车牌小图 PaddleOCR 直接返回空串，放大后正常
PLATE_MIN_HEIGHT = 48
PLATE_SCALE_MAX = 4.0      # 最大放大倍数，再大反而变糊

# 摄像头场景的多帧投票：窗口内至少 min_votes 帧识别到同一车牌才确认
PLATE_VOTE_WINDOW = 8
PLATE_VOTE_MIN = 3

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
