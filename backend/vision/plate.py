# -*- coding: utf-8 -*-
"""入口车牌识别：先用 YOLO 定位车牌，再用 PaddleOCR 识别字符。

用于停车场入口抓拍——识别车牌号并记录入场时间，作为计费起点。

════════════════════════════════════════════════════════════════════
⚠ 下面的 import 顺序绝对不要调整
   torch 必须最先导入，paddle 紧随其后。
   反过来（先 paddle 再 torch）会让 torch 报
   `OSError: [WinError 127] 找不到指定的程序`，
   因为两个框架各自带了一套 MKL/DLL，加载顺序错了就冲突。
════════════════════════════════════════════════════════════════════

相对旧项目 backend/license_plate_recognizer.py 的修改：

1. 小尺寸车牌先放大再 OCR —— 高度不足 48px 时 PaddleOCR 会直接漏检，
   实测 79x30 的原图返回空串，放大 3 倍后能正确识别
2. 车牌号清洗与格式校验 —— 去掉 OCR 输出里的 "·"、全角字符，
   按中国车牌规则校验省份简称与字母位，过滤掉明显不是车牌的结果
3. 字符纠错 —— 车牌不使用字母 I、O，出现的一律按 1、0 处理
4. 多帧投票 —— 摄像头连续多帧识别到同一车牌才确认，压掉单帧误识别
5. 不再在模块导入时初始化模型 —— 旧代码末尾直接 `instance = Cls()`，
   一 import 就加载 6MB 权重并初始化 OCR，启动慢且无法测试
6. 中文路径兼容 —— 复用 utils.imread_unicode
7. 抓拍存证 —— 识别成功时把原图和标注图存到 data/snapshots/

用法：
    # 图片
    python plate.py --source ../../data/videos/gate.jpg --save out.jpg

    # 摄像头（按 s 抓拍存证，q 退出）
    python plate.py --source 0

    # 视频
    python plate.py --source ../../data/videos/gate.mp4 --limit 100
"""
import torch  # noqa: F401  必须最先导入，见文件头说明
from ultralytics import YOLO
from paddleocr import PaddleOCR

import argparse
import re
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

import config as cfg
from utils import imread_unicode, imwrite_unicode, resolve_model


# ==================== 车牌规则常量 ====================

# 31 个省级行政区简称（车牌首位只能是这些字）
PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"

# 车牌不使用字母 I 和 O，避免与数字 1、0 混淆
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

# 普通车牌 7 位：省 + 字母 + 5 位
# 新能源车牌 8 位：省 + 字母 + 6 位（小型车第 3 位是 D/F）
PLATE_PATTERN = re.compile(
    r"^[%s][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6}$" % PROVINCES
)

IMG_SUFFIX = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


# ==================== 数据结构 ====================

@dataclass
class PlateResult:
    """单块车牌的识别结果。"""
    plate_number: str = ""        # 校验通过的车牌号，无效时为空串
    raw_text: str = ""            # OCR 原始输出（清洗前）
    detect_conf: float = 0.0      # YOLO 检测置信度
    ocr_conf: float = 0.0         # OCR 字符置信度
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    valid: bool = False           # 是否符合中国车牌格式
    reason: str = ""              # 无效原因，便于调试

    def __str__(self):
        tag = self.plate_number if self.valid else "无效"
        return "%-10s det=%.2f ocr=%.2f %s" % (
            tag, self.detect_conf, self.ocr_conf,
            self.reason if not self.valid else ""
        )


# ==================== 车牌号清洗与校验 ====================

def clean_plate_text(text: str) -> str:
    """清洗 OCR 输出：去分隔符、全角转半角、纠正 I/O 混淆。

    PaddleOCR 对车牌常输出 "皖A·12345" 这种带间隔号的形式，
    有时还会把数字 0 认成字母 O、数字 1 认成字母 I。
    """
    if not text:
        return ""

    # 全角字母数字转半角（部分 OCR 结果会带全角字符）
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    t = "".join(out).upper()

    # 去掉间隔号、点、横杠、空白等分隔符
    t = re.sub(r"[·•\.\-\s_/\\|]", "", t)

    # 只保留汉字、字母、数字
    t = re.sub(r"[^A-Z0-9\u4e00-\u9fa5]", "", t)

    if len(t) < 2:
        return t

    # 首位是省份汉字，从第 2 位起不该出现 I、O
    head, body = t[0], t[1:]
    body = body.replace("I", "1").replace("O", "0")

    return head + body


def validate_plate(text: str) -> Tuple[bool, str]:
    """校验车牌号是否符合中国车牌格式，返回 (是否有效, 原因)。"""
    if not text:
        return False, "空字符串"

    if text[0] not in PROVINCES:
        return False, "首位不是省份简称: %s" % text[0]

    if len(text) < 7:
        return False, "长度不足 7 位: %d" % len(text)

    if len(text) > 8:
        return False, "长度超过 8 位: %d" % len(text)

    if not PLATE_PATTERN.match(text):
        if text[1] not in LETTERS:
            return False, "第 2 位不是合法字母: %s" % text[1]
        return False, "不符合车牌格式"

    return True, ""


# ==================== 多帧投票 ====================

class PlateVoter:
    """摄像头场景下的多帧投票。

    单帧 OCR 偶尔会把 X 认成 K、8 认成 B，连续多帧稳定出现的才是真车牌。
    做法和车位状态的 smoother 一样，只不过这里投的是字符串。
    """

    def __init__(self, window: int = 8, min_votes: int = 3):
        self.window = window
        self.min_votes = min_votes
        self._buf = deque(maxlen=window)
        self._confirmed = ""      # 上一次确认的车牌，票数不足时沿用

    def feed(self, plate_number: str) -> Optional[str]:
        """喂入一帧结果。票数够则返回确认车牌，否则返回 None。"""
        if not plate_number:
            return None

        self._buf.append(plate_number)

        # 窗口没满时先不确认，避免开局误判
        if len(self._buf) < min(self.window, self.min_votes):
            return None

        counter = Counter(self._buf)
        plate, votes = counter.most_common(1)[0]

        if votes >= self.min_votes:
            self._confirmed = plate
            return plate

        return None

    def reset(self):
        self._buf.clear()
        self._confirmed = ""

    @property
    def confirmed(self) -> str:
        return self._confirmed


# ==================== 识别器 ====================

class PlateReader:
    """车牌识别器。

    刻意不在 __init__ 之外做任何模型加载，也不定义全局实例，
    这样 import 本模块不会花几秒去加载权重。
    """

    def __init__(self,
                 model_path: str = None,
                 conf: float = None,
                 ocr_conf: float = None,
                 use_gpu: Optional[bool] = None):
        self.model_path = resolve_model(model_path or cfg.PLATE_MODEL)
        self.conf = cfg.PLATE_CONF if conf is None else conf
        self.ocr_conf = cfg.PLATE_OCR_CONF if ocr_conf is None else ocr_conf

        self.model = YOLO(self.model_path)
        self._fallback_used = False   # 本轮是否用了兜底阈值，便于调试

        if use_gpu is None:
            use_gpu = self._detect_gpu()

        self.ocr = PaddleOCR(
            use_angle_cls=False,   # 车牌已由 YOLO 摆正，不需要方向分类
            lang="ch",
            show_log=False,
            use_gpu=use_gpu,
        )
        self.use_gpu = use_gpu

    @staticmethod
    def _detect_gpu() -> bool:
        """自动判断能不能用 GPU，避免像旧代码那样硬编码 use_gpu=True。"""
        try:
            import paddle
            if not paddle.device.is_compiled_with_cuda():
                return False
            return paddle.device.cuda.device_count() > 0
        except Exception:
            return False

    # ---------- 核心 ----------

    def read(self, frame: np.ndarray) -> List[PlateResult]:
        """对一帧画面做车牌检测 + 识别，返回所有车牌结果。"""
        if frame is None or frame.size == 0:
            return []

        det = self.model(frame, conf=self.conf, verbose=False)[0]

        # 兜底：第一轮一个车牌都没检到，说明这张图比较困难
        # （倾斜、模糊、逆光、车牌占比小），降一档阈值再试。
        # 误检的风险由后面的车牌格式校验挡住——不是车牌格式的直接丢弃
        if len(det.boxes) == 0:
            det = self.model(frame, conf=cfg.PLATE_CONF_FALLBACK, verbose=False)[0]
            if len(det.boxes) > 0:
                self._fallback_used = True

        results = []

        for box in det.boxes:
            x1, y1, x2, y2 = box.xyxy.cpu().numpy().astype(int)[0]

            # 框向外扩一点：YOLO 的框通常贴得很紧，
            # 边缘字符容易被切掉，留 3% 余量
            pad_x = max(2, int((x2 - x1) * 0.03))
            pad_y = max(2, int((y2 - y1) * 0.03))
            cx1, cy1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            cx2, cy2 = min(frame.shape[1], x2 + pad_x), min(frame.shape[0], y2 + pad_y)

            crop = frame[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue

            # 宽高比过滤：低阈值兜底时 YOLO 有时会把整个车身框成车牌，
            # 实测出现过 720x436 的框（宽高比 1.7）。真车牌宽高比在
            # 2.0（双层）到 3.2（单层）之间，留些余量后取 1.6~6.0
            ch, cw = crop.shape[:2]
            ratio = cw / max(ch, 1)
            if not (cfg.PLATE_ASPECT_MIN <= ratio <= cfg.PLATE_ASPECT_MAX):
                continue

            raw_text, ocr_conf = self._ocr_crop(crop)

            # OCR 没出结果时，用 CLAHE 增强对比度再试一次。
            # 实测有车牌在正常放大下 OCR 返回空串，增强后能识别出大部分字符
            if not raw_text:
                raw_text, ocr_conf = self._ocr_crop(crop, enhance=True)

            plate = clean_plate_text(raw_text)
            valid, reason = validate_plate(plate)

            results.append(PlateResult(
                plate_number=plate if valid else "",
                raw_text=raw_text,
                detect_conf=float(box.conf),
                ocr_conf=ocr_conf,
                bbox=(int(x1), int(y1), int(x2), int(y2)),
                valid=valid,
                reason=reason,
            ))

        return results

    def _ocr_crop(self, crop: np.ndarray, enhance: bool = False) -> Tuple[str, float]:
        """对车牌区域做 OCR。

        两个关键优化：
        1. 高度不足时先放大 —— PaddleOCR 的文本检测网络对过矮的文本
           几乎必然漏检，实测 79x30 的车牌图直接返回空结果
        2. enhance=True 时先做 CLAHE 对比度增强并强制放大 —— 用于
           第一次 OCR 返回空的兜底重试
        """
        h, w = crop.shape[:2]
        scale = 1.0

        if h < cfg.PLATE_MIN_HEIGHT:
            scale = min(cfg.PLATE_SCALE_MAX, cfg.PLATE_MIN_HEIGHT / max(h, 1))

        img = crop

        if enhance:
            # 灰度 + 限制对比度自适应直方图均衡，能把逆光、阴影下的
            # 车牌字符拉出来
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            scale = max(scale, 3.0)

        if scale > 1.01:
            img = cv2.resize(img, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)

        raw = self.ocr.ocr(img, cls=False)

        if not raw or not raw[0]:
            return "", 0.0

        # 双层车牌 OCR 会返回两行，按纵向位置拼起来
        lines = []
        for item in raw[0]:
            try:
                text = item[1][0]
                confidence = float(item[1][1])
                top_y = item[0][0][1]
            except (IndexError, TypeError, ValueError):
                continue
            if confidence >= self.ocr_conf:
                lines.append((top_y, text, confidence))

        if not lines:
            return "", 0.0

        lines.sort(key=lambda x: x[0])
        merged = "".join(t for _, t, _ in lines)
        avg_conf = sum(c for _, _, c in lines) / len(lines)

        return merged, avg_conf

    # ---------- 标注 ----------

    def annotate(self, frame: np.ndarray, results: List[PlateResult]) -> np.ndarray:
        """把识别结果画到画面上。cv2.putText 不支持中文，只画编号和置信度。"""
        canvas = frame.copy()

        for idx, r in enumerate(results, 1):
            x1, y1, x2, y2 = r.bbox
            color = (80, 200, 80) if r.valid else (60, 60, 220)

            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)

            tag = "P%d %.2f" % (idx, r.detect_conf)
            cv2.putText(canvas, tag, (x1, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        if results:
            valid = [r for r in results if r.valid]
            head = valid[0].plate_number if valid else "NO VALID PLATE"
            cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 34), (32, 32, 32), -1)
            cv2.putText(canvas, head, (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        return canvas

    # ---------- 存证 ----------

    @staticmethod
    def save_snapshot(frame: np.ndarray, annotated: np.ndarray,
                      plate_number: str) -> Optional[str]:
        """把抓拍原图和标注图存下来，作为入场凭证。"""
        try:
            cfg.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_plate = plate_number or "UNKNOWN"

            raw_path = cfg.SNAPSHOT_DIR / ("%s_%s_raw.jpg" % (stamp, safe_plate))
            ann_path = cfg.SNAPSHOT_DIR / ("%s_%s_ann.jpg" % (stamp, safe_plate))

            imwrite_unicode(str(raw_path), frame)
            imwrite_unicode(str(ann_path), annotated)

            return str(raw_path)
        except Exception:
            return None


# ==================== 命令行 ====================

def summarize(results: List[PlateResult]) -> str:
    """把结果整理成一行可读文本。"""
    if not results:
        return "未检测到车牌"

    parts = []
    for r in results:
        if r.valid:
            parts.append(r.plate_number)
        else:
            parts.append("无效(%s)" % (r.reason or "格式不符"))
    return " | ".join(parts)


def parse_args():
    parser = argparse.ArgumentParser(description="入口车牌识别")
    parser.add_argument("--source", required=True, help="图片/视频路径，或摄像头编号 0")
    parser.add_argument("--model", default=None, help="车牌检测权重，默认 weights/LP-detection.pt")
    parser.add_argument("--conf", type=float, default=None, help="检测置信度下限")
    parser.add_argument("--save", default=None, help="标注结果输出路径")
    parser.add_argument("--no-show", action="store_true", help="不弹窗")
    parser.add_argument("--no-snapshot", action="store_true", help="不保存抓拍图")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 帧")
    return parser.parse_args()


def main():
    args = parse_args()

    reader = PlateReader(model_path=args.model, conf=args.conf)
    print("[init] 车牌模型: %s | OCR GPU: %s" % (reader.model_path, reader.use_gpu))

    source = args.source
    is_image = (not source.isdigit()
                and Path(source).is_file()
                and Path(source).suffix.lower() in IMG_SUFFIX)

    # ---------- 单张图片 ----------
    if is_image:
        frame = imread_unicode(source)
        if frame is None:
            print("[error] 无法读取图片: %s" % source)
            return

        t0 = time.time()
        results = reader.read(frame)
        cost = (time.time() - t0) * 1000

        print("[result] 耗时 %.1f ms | 检测到 %d 块车牌" % (cost, len(results)))
        for r in results:
            print("   %s" % r)
        print("[车牌] %s" % summarize(results))

        annotated = reader.annotate(frame, results)
        if args.save:
            imwrite_unicode(args.save, annotated)
            print("[saved] %s" % args.save)

        if not args.no_snapshot:
            valid = [r for r in results if r.valid]
            if valid:
                path = reader.save_snapshot(frame, annotated, valid[0].plate_number)
                if path:
                    print("[snapshot] %s" % path)

        if not args.no_show:
            cv2.imshow("plate reader", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return

    # ---------- 视频 / 摄像头 ----------
    src = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print("[error] 无法打开视频源: %s" % source)
        return

    is_camera = isinstance(src, int)
    voter = PlateVoter(cfg.PLATE_VOTE_WINDOW, cfg.PLATE_VOTE_MIN)
    writer = None

    if args.save:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    frame_id = 0
    last_log = ""
    print("[hint] 摄像头模式：按 s 抓拍存证，按 q 退出" if is_camera else "[hint] 按 q 退出")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_id += 1
        if args.limit and frame_id > args.limit:
            break

        results = reader.read(frame)
        annotated = reader.annotate(frame, results)

        # 多帧投票：只有稳定出现的车牌才认为确认
        confirmed = None
        for r in results:
            if r.valid:
                confirmed = voter.feed(r.plate_number)
                if confirmed:
                    break

        if confirmed and confirmed != last_log:
            print("[确认] %s  (第 %d 帧)" % (confirmed, frame_id))
            last_log = confirmed

        if confirmed:
            cv2.putText(annotated, "CONFIRMED", (10, annotated.shape[0] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 200, 80), 2)

        if writer is not None:
            writer.write(annotated)

        if not args.no_show:
            cv2.imshow("plate reader", annotated)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            if key == ord("s"):
                plate = confirmed or (results[0].plate_number if results and results[0].valid else "")
                path = reader.save_snapshot(frame, annotated, plate)
                print("[抓拍] %s -> %s" % (plate or "未识别", path))

    cap.release()
    if writer is not None:
        writer.release()
    cv2.destroyAllWindows()
    print("[done] 共处理 %d 帧" % frame_id)


if __name__ == "__main__":
    main()
