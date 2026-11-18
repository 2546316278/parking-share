# -*- coding: utf-8 -*-
"""
车位状态检测核心。

处理流程：
    视频帧
      -> YOLOv8n 检测车辆（只保留 car / motorcycle / bus / truck）
      -> 计算每辆车与每个车位多边形的重叠面积占比（coverage）
      -> 贪心分配，保证一辆车只归属一个车位（避免一辆车把两个车位都判成占用）
      -> 覆盖率超过阈值的车位判为 occupied
      -> 滑动窗口平滑，输出稳定的 free / occupied

用法：
    # 单张图片
    python detector.py --source demo.jpg --calib ../../data/calibrations/demo.json --save out.jpg

    # 视频文件
    python detector.py --source ../../data/videos/parking.mp4 --calib ../../data/calibrations/parking.json

    # 本机摄像头
    python detector.py --source 0 --calib ../../data/calibrations/parking.json

    # 无窗口批量跑，输出每帧 JSON
    python detector.py --source ../../data/videos/parking.mp4 --calib ... --no-show --log result.jsonl
"""
import argparse
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

import config as cfg
from smoother import StatusSmoother
from utils import imread_unicode, imwrite_unicode, resolve_model


# ==================== 数据结构 ====================

@dataclass
class SpaceResult:
    space_number: str
    status: str               # free / occupied / unknown
    coverage: float           # 0.0 ~ 1.0
    bbox: Optional[List[int]] = None
    vehicle_class: Optional[str] = None


def load_calibration(path: str) -> dict:
    """加载车位标定文件，由 calibrate.py 生成。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "spaces" not in data or not data["spaces"]:
        raise ValueError("标定文件里没有车位数据，请先用 calibrate.py 标定")
    return data


# ==================== 检测器 ====================

class ParkingDetector(object):
    """封装模型加载、掩膜缓存与状态判定，便于被 worker 复用。"""

    def __init__(self, calib: dict, model_path: str = cfg.YOLO_MODEL,
                 conf: float = cfg.CONF_THRESHOLD):
        self.calib = calib
        self.spaces = calib["spaces"]
        self.conf = conf
        self.model = YOLO(resolve_model(model_path))
        self.smoother = StatusSmoother()

        self._masks: List[Tuple[np.ndarray, int]] = []
        self._mask_size: Optional[Tuple[int, int]] = None

        # 缓存最后一帧的结果，供上层随时读取
        self.last_results: List[SpaceResult] = []
        self.last_frame: Optional[np.ndarray] = None

    # ---------- 掩膜 ----------

    def _build_masks(self, height: int, width: int):
        """为每个车位生成二值掩膜并缓存面积，避免每帧重复填充多边形。"""
        self._masks = []
        for space in self.spaces:
            mask = np.zeros((height, width), np.uint8)
            pts = np.array(space["polygon"], dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
            self._masks.append((mask, int(cv2.countNonZero(mask))))
        self._mask_size = (height, width)

    # ---------- 车辆归属 ----------

    def _assign_vehicles(self, vehicles: List[dict]) -> Dict[int, Tuple[int, float]]:
        """
        计算车辆与车位的归属关系。

        返回 {车位下标: (车辆下标, 覆盖率)}。
        规则：按重叠率从高到低贪心分配，同一辆车只归属覆盖率最高的车位，
              同一车位只接受一辆车，避免一辆车把相邻两个车位都判成占用。
        """
        if not self._masks or not vehicles:
            return {}

        pairs = []
        for vi, veh in enumerate(vehicles):
            x1, y1, x2, y2 = veh["bbox"]
            if (x2 - x1) * (y2 - y1) < cfg.MIN_VEHICLE_AREA:
                continue
            for si, (mask, area) in enumerate(self._masks):
                if area <= 0:
                    continue
                patch = mask[y1:y2, x1:x2]
                if patch.size == 0:
                    continue
                inter = int(cv2.countNonZero(patch))
                if inter == 0:
                    continue
                coverage = inter / float(area)
                # 先收集所有存在重叠的候选，阈值判断留到排序之后
                if coverage >= 0.05:
                    pairs.append((coverage, vi, si))

        pairs.sort(key=lambda t: t[0], reverse=True)

        assigned: Dict[int, Tuple[int, float]] = {}
        used_vehicle = set()
        for coverage, vi, si in pairs:
            if coverage < cfg.COVERAGE_THRESHOLD:
                break
            if si in assigned or vi in used_vehicle:
                continue
            assigned[si] = (vi, coverage)
            used_vehicle.add(vi)

        return assigned

    # ---------- 主检测 ----------

    def detect(self, frame: np.ndarray, smooth: bool = True) -> List[SpaceResult]:
        """对一帧做检测，返回每个车位的状态。"""
        h, w = frame.shape[:2]
        if self._mask_size != (h, w):
            self._build_masks(h, w)

        # 1) 车辆检测
        pred = self.model(
            frame,
            imgsz=cfg.IMG_SIZE,
            conf=self.conf,
            classes=cfg.VEHICLE_CLASSES,
            verbose=False,
        )[0]

        vehicles = []
        if pred.boxes is not None and len(pred.boxes) > 0:
            xyxy = pred.boxes.xyxy.cpu().numpy().astype(int)
            confs = pred.boxes.conf.cpu().numpy()
            clss = pred.boxes.cls.cpu().numpy().astype(int)
            for box, conf, cls_id in zip(xyxy, confs, clss):
                x1, y1, x2, y2 = box
                # 裁剪到画面范围内，避免越界索引
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                vehicles.append({
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "conf": float(conf),
                    "class": cfg.CLASS_NAMES.get(int(cls_id), str(cls_id)),
                })

        # 2) 车辆 -> 车位归属
        assigned = self._assign_vehicles(vehicles)

        # 3) 生成每个车位的状态
        results: List[SpaceResult] = []
        for si, space in enumerate(self.spaces):
            if si in assigned:
                vi, coverage = assigned[si]
                raw_status = cfg.STATUS_OCCUPIED
                bbox = vehicles[vi]["bbox"]
                vclass = vehicles[vi]["class"]
            else:
                coverage = 0.0
                raw_status = cfg.STATUS_FREE
                bbox = None
                vclass = None

            status = self.smoother.update(space["space_number"], raw_status) if smooth else raw_status
            results.append(SpaceResult(
                space_number=space["space_number"],
                status=status,
                coverage=round(coverage, 3),
                bbox=bbox,
                vehicle_class=vclass,
            ))

        self.last_results = results
        self.last_frame = frame
        return results

    # ---------- 可视化 ----------

    def annotate(self, frame: np.ndarray, results: List[SpaceResult]) -> np.ndarray:
        """在画面上画出车位多边形、状态与车辆框。"""
        canvas = frame.copy()
        overlay = canvas.copy()

        for space, res in zip(self.spaces, results):
            pts = np.array(space["polygon"], dtype=np.int32)
            color = cfg.STATUS_COLOR.get(res.status, cfg.COLOR_UNKNOWN)
            cv2.fillPoly(overlay, [pts], color)

        canvas = cv2.addWeighted(overlay, 0.28, canvas, 0.72, 0)

        for space, res in zip(self.spaces, results):
            pts = np.array(space["polygon"], dtype=np.int32)
            color = cfg.STATUS_COLOR.get(res.status, cfg.COLOR_UNKNOWN)
            cv2.polylines(canvas, [pts], True, color, 2)

            # 标注文字放在多边形左上角，cv2.putText 不支持中文，统一用 ASCII
            anchor = pts[0]
            label = "%s %s %.2f" % (
                res.space_number,
                cfg.STATUS_TEXT.get(res.status, "UNK"),
                res.coverage,
            )
            cv2.putText(canvas, label, (int(anchor[0]) + 2, int(anchor[1]) + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, label, (int(anchor[0]) + 2, int(anchor[1]) + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

            if res.bbox:
                x1, y1, x2, y2 = res.bbox
                cv2.rectangle(canvas, (x1, y1), (x2, y2), cfg.COLOR_VEHICLE, 1)

        return canvas

    def summary(self, results: List[SpaceResult]) -> dict:
        """统计这一帧的空闲/占用数量，供日志与上报使用。"""
        free = sum(1 for r in results if r.status == cfg.STATUS_FREE)
        occupied = sum(1 for r in results if r.status == cfg.STATUS_OCCUPIED)
        return {
            "total": len(results),
            "free": free,
            "occupied": occupied,
            "unknown": len(results) - free - occupied,
        }


# ==================== 命令行入口 ====================

def parse_args():
    parser = argparse.ArgumentParser(description="车位状态检测")
    parser.add_argument("--source", required=True,
                        help="图片路径 / 视频路径 / 摄像头编号（如 0）")
    parser.add_argument("--calib", required=True, help="车位标定 JSON 路径")
    parser.add_argument("--model", default=cfg.YOLO_MODEL, help="YOLO 权重路径")
    parser.add_argument("--conf", type=float, default=cfg.CONF_THRESHOLD,
                        help="车辆检测置信度下限")
    parser.add_argument("--save", default=None, help="标注结果输出路径（图片或视频）")
    parser.add_argument("--log", default=None, help="逐帧结果写入 JSONL 文件")
    parser.add_argument("--no-show", action="store_true", help="不弹出预览窗口")
    parser.add_argument("--no-smooth", action="store_true", help="关闭时序平滑")
    parser.add_argument("--limit", type=int, default=0,
                        help="只处理前 N 帧（0 表示不限制），用于快速验证")
    return parser.parse_args()


def open_capture(source: str):
    """打开视频源，返回 (VideoCapture, 是否为摄像头)。"""
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
        return cap, True
    cap = cv2.VideoCapture(source)
    return cap, False


def main():
    args = parse_args()

    calib = load_calibration(args.calib)
    detector = ParkingDetector(calib, model_path=args.model, conf=args.conf)
    print("[init] 车位数量: %d, 模型: %s" % (len(detector.spaces), args.model))

    log_file = open(args.log, "w", encoding="utf-8") if args.log else None
    smooth = not args.no_smooth

    # ---------- 单张图片 ----------
    if not args.source.isdigit() and Path(args.source).is_file() \
            and Path(args.source).suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        frame = imread_unicode(args.source)
        if frame is None:
            print("[error] 无法读取图片: %s" % args.source)
            return

        t0 = time.time()
        results = detector.detect(frame, smooth=smooth)
        cost = (time.time() - t0) * 1000

        stats = detector.summary(results)
        print("[result] 耗时 %.1f ms | 总 %d 空 %d 占 %d"
              % (cost, stats["total"], stats["free"], stats["occupied"]))
        for r in results:
            print("   %-6s %-9s coverage=%.3f %s"
                  % (r.space_number, r.status, r.coverage,
                     ("<- " + r.vehicle_class) if r.vehicle_class else ""))

        annotated = detector.annotate(frame, results)
        if args.save:
            imwrite_unicode(args.save, annotated)
            print("[saved] %s" % args.save)

        if not args.no_show:
            cv2.imshow("parking detection", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        if log_file:
            log_file.write(json.dumps({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "cost_ms": round(cost, 1),
                "stats": stats,
                "spaces": [asdict(r) for r in results],
            }, ensure_ascii=False) + "\n")
            log_file.close()
        return

    # ---------- 视频 / 摄像头 ----------
    cap, is_camera = open_capture(args.source)
    if not cap.isOpened():
        print("[error] 无法打开视频源: %s" % args.source)
        return

    writer = None
    if args.save:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(args.save, fourcc, fps, (w, h))
        print("[init] 输出视频 %s (%dx%d @ %.1ffps)" % (args.save, w, h, fps))

    frame_id = 0
    t_start = time.time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            results = detector.detect(frame, smooth=smooth)
            annotated = detector.annotate(frame, results)

            stats = detector.summary(results)
            cv2.putText(annotated,
                        "frame %d  free %d / %d" % (frame_id, stats["free"], stats["total"]),
                        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(annotated,
                        "frame %d  free %d / %d" % (frame_id, stats["free"], stats["total"]),
                        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

            if writer is not None:
                writer.write(annotated)

            if log_file:
                log_file.write(json.dumps({
                    "frame": frame_id,
                    "stats": stats,
                    "spaces": [asdict(r) for r in results],
                }, ensure_ascii=False) + "\n")

            if frame_id % 30 == 0:
                print("[frame %5d] free %d / %d" % (frame_id, stats["free"], stats["total"]))

            if not args.no_show:
                cv2.imshow("parking detection", annotated)
                # q 或 ESC 退出
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break

            frame_id += 1
            if args.limit and frame_id >= args.limit:
                break
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        if log_file:
            log_file.close()
        if not args.no_show:
            cv2.destroyAllWindows()

    elapsed = time.time() - t_start
    if frame_id:
        print("[done] 共 %d 帧，耗时 %.1fs，平均 %.1f fps"
              % (frame_id, elapsed, frame_id / max(elapsed, 1e-6)))


if __name__ == "__main__":
    main()
