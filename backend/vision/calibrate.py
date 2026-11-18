# -*- coding: utf-8 -*-
"""
车位 ROI 标定工具。

作用：
在停车场摄像头画面上，用鼠标逐个框出车位区域，导出为 JSON。
检测脚本与前端平面图都读这份 JSON，做到"标定一次，多处复用"。

操作：
    鼠标左键   添加多边形顶点
    鼠标右键   闭合当前车位（也可按回车）
    回车       闭合当前车位
    b          撤销上一个顶点
    u          撤销上一个车位
    s          保存到文件
    q / ESC    退出

用法：
    python calibrate.py --source ../../data/videos/parking.mp4 --at 3
    python calibrate.py --source demo.jpg --prefix B --start 10
    python calibrate.py --source demo.jpg --load ../../data/calibrations/demo.json
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

import config as cfg
from detector import imread_unicode

WINDOW = "calibrate - L:add  R:close  b:undo pt  u:undo space  s:save  q:quit"

# 交互状态集中在一个字典里，避免到处写 global
STATE = {
    "base": None,          # 底图
    "points": [],          # 当前正在画的多边形顶点
    "spaces": [],          # 已完成的 [{"space_number":..., "polygon":...}]
    "mouse": (0, 0),       # 当前鼠标位置，用于画橡皮筋线
    "prefix": "A",         # 车位编号前缀
    "next_idx": 1,         # 下一个编号
    "output": None,        # 保存路径
    "meta": {},            # 附加元信息
}


def add_point(x: int, y: int):
    STATE["points"].append((x, y))


def close_space():
    """把当前顶点集闭合为一个车位。"""
    pts = STATE["points"]
    if len(pts) < 3:
        print("[warn] 至少需要 3 个顶点，当前 %d 个" % len(pts))
        return
    number = "%s%02d" % (STATE["prefix"], STATE["next_idx"])
    STATE["spaces"].append({
        "space_number": number,
        "polygon": [[int(x), int(y)] for x, y in pts],
    })
    STATE["next_idx"] += 1
    STATE["points"] = []
    print("[ok] 已添加车位 %s，累计 %d 个" % (number, len(STATE["spaces"])))


def undo_space():
    if STATE["spaces"]:
        removed = STATE["spaces"].pop()
        STATE["next_idx"] = max(1, STATE["next_idx"] - 1)
        print("[undo] 移除车位 %s" % removed["space_number"])


def on_mouse(event, x, y, flags, param):
    STATE["mouse"] = (x, y)
    if event == cv2.EVENT_LBUTTONDOWN:
        add_point(x, y)
    elif event == cv2.EVENT_RBUTTONDOWN:
        close_space()


def render() -> np.ndarray:
    """重绘画布：底图 + 已完成车位 + 正在画的多边形 + 提示。"""
    img = STATE["base"].copy()

    # 已完成的车位：半透明填充 + 绿边 + 编号
    overlay = img.copy()
    for space in STATE["spaces"]:
        pts = np.array(space["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], (0, 255, 0))
    img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)

    for space in STATE["spaces"]:
        pts = np.array(space["polygon"], dtype=np.int32)
        cv2.polylines(img, [pts], True, (0, 255, 0), 2)
        anchor = pts[0]
        cv2.putText(img, space["space_number"], (int(anchor[0]) + 2, int(anchor[1]) + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, space["space_number"], (int(anchor[0]) + 2, int(anchor[1]) + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)

    # 正在画的多边形：橙色折线 + 橡皮筋线
    pts = STATE["points"]
    if pts:
        if len(pts) >= 2:
            cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, (0, 200, 255), 2)
        for p in pts:
            cv2.circle(img, p, 4, (0, 200, 255), -1)
        cv2.line(img, pts[-1], STATE["mouse"], (0, 200, 255), 1, cv2.LINE_AA)

    # 顶部状态栏
    hud = "spaces=%d  points=%d  next=%s%02d" % (
        len(STATE["spaces"]), len(pts), STATE["prefix"], STATE["next_idx"])
    cv2.rectangle(img, (0, 0), (img.shape[1], 34), (30, 30, 30), -1)
    cv2.putText(img, hud, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def save():
    if not STATE["spaces"]:
        print("[warn] 还没有标定任何车位，无法保存")
        return
    payload = {
        "lot_name": STATE["meta"].get("lot_name", ""),
        "source": STATE["meta"].get("source", ""),
        "image_size": [int(STATE["base"].shape[0]), int(STATE["base"].shape[1])],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "spaces": STATE["spaces"],
    }
    out = Path(STATE["output"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("[saved] %s（共 %d 个车位）" % (out, len(STATE["spaces"])))


def load_base(source: str, at_second: float) -> np.ndarray:
    """读取底图：图片直接读，视频取指定秒数的帧。"""
    path = Path(source)
    suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    if path.suffix.lower() in suffixes:
        frame = imread_unicode(str(path))
        if frame is None:
            raise RuntimeError("无法读取图片: %s" % source)
        return frame

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("无法打开视频: %s" % source)
    if at_second > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, at_second * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("读取视频帧失败: %s" % source)
    return frame


def parse_args():
    parser = argparse.ArgumentParser(description="车位 ROI 标定")
    parser.add_argument("--source", required=True, help="图片或视频路径")
    parser.add_argument("--at", type=float, default=0.0, help="视频取第几秒的帧")
    parser.add_argument("--output", default=None,
                        help="输出 JSON 路径，默认 data/calibrations/<源文件名>.json")
    parser.add_argument("--prefix", default="A", help="车位编号前缀，默认 A")
    parser.add_argument("--start", type=int, default=1, help="起始编号，默认 1")
    parser.add_argument("--lot-name", default="", help="停车场名称")
    parser.add_argument("--load", default=None, help="载入已有标定文件继续编辑")
    return parser.parse_args()


def main():
    args = parse_args()

    base = load_base(args.source, args.at)
    h, w = base.shape[:2]
    print("[info] 底图尺寸 %dx%d" % (w, h))

    # 直接使用原图作为底图。WINDOW_NORMAL 允许自由拉伸窗口，
    # OpenCV 会自动把窗口坐标换算回图像坐标，因此无需手动缩放。
    STATE["base"] = base
    STATE["prefix"] = args.prefix
    STATE["next_idx"] = args.start
    STATE["meta"] = {"lot_name": args.lot_name, "source": str(args.source)}

    if args.output:
        STATE["output"] = args.output
    else:
        STATE["output"] = str(cfg.CALIB_DIR / (Path(args.source).stem + ".json"))

    if args.load:
        with open(args.load, "r", encoding="utf-8") as f:
            old = json.load(f)
        STATE["spaces"] = old.get("spaces", [])
        STATE["next_idx"] = len(STATE["spaces"]) + args.start
        print("[load] 已载入 %d 个车位" % len(STATE["spaces"]))

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW, on_mouse)

    print("[hint] 左键点四个角 -> 右键闭合。按 s 保存，q 退出。")

    while True:
        cv2.imshow(WINDOW, render())

        key = cv2.waitKey(30) & 0xFF
        if key in (13, 10):
            close_space()
        elif key == ord("b"):
            if STATE["points"]:
                STATE["points"].pop()
        elif key == ord("u"):
            undo_space()
        elif key == ord("s"):
            save()
        elif key in (ord("q"), 27):
            if STATE["spaces"]:
                save()
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
