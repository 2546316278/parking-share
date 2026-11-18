# -*- coding: utf-8 -*-
"""一次性脚本：合成一个 3 车位的测试场景，用于验证视觉链路是否跑通。

用途：在没有真实停车场素材时，快速确认「标定文件读取 -> 车辆检测 ->
      覆盖率判定 -> 标注输出」整条链路没有断。
注意：合成图只能验证"代码跑得通"，不能代表真实场景的精度。
      论文里的准确率数据必须用真实停车场画面跑出来。

用法：
    # 车辆素材默认取 data/samples/ 下第一张非 demo_ 开头的图片
    python scripts/make_demo.py

    # 指定车辆素材
    python scripts/make_demo.py --car "D:/停车场/night.png"

产物：
    data/samples/demo_parking.jpg        合成的 3 车位场景图
    data/calibrations/demo_parking.json  与之配套的车位标定文件
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "data" / "samples"
CALIB_DIR = BASE_DIR / "data" / "calibrations"

SLOT_W, SLOT_H = 620, 440       # 单个车位尺寸
PAD = 20                        # 车位间距 / 画布留白
IMG_SUFFIX = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def imread_unicode(path):
    """兼容 Windows 中文路径的读图。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(path, img):
    """兼容 Windows 中文路径的写图。"""
    ok, buf = cv2.imencode(Path(str(path)).suffix or ".jpg", img)
    if not ok:
        raise IOError("图片编码失败: %s" % path)
    buf.tofile(str(path))


def pick_car_image(explicit=None):
    """确定用作"车辆"的素材图。"""
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            sys.exit("找不到车辆素材图: %s" % p)
        return p

    candidates = [
        p for p in sorted(SAMPLE_DIR.iterdir())
        if p.suffix.lower() in IMG_SUFFIX and not p.name.startswith("demo_")
    ]
    if not candidates:
        sys.exit(
            "data/samples/ 下没有可用的车辆素材图。\n"
            "请把一张带车的照片放进去，或用 --car 指定路径。"
        )
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="合成 3 车位测试场景")
    parser.add_argument("--car", default=None,
                        help="车辆素材图路径（默认自动挑 data/samples/ 下的图）")
    args = parser.parse_args()

    car_src = pick_car_image(args.car)
    car_img = imread_unicode(car_src)
    if car_img is None:
        sys.exit("车辆素材图读取失败: %s" % car_src)

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    CALIB_DIR.mkdir(parents=True, exist_ok=True)

    canvas_w = SLOT_W * 3 + PAD * 4
    canvas_h = SLOT_H + PAD * 2
    canvas = np.full((canvas_h, canvas_w, 3), 110, np.uint8)

    # 白线框出 3 个车位
    for i in range(3):
        x0 = PAD + i * (SLOT_W + PAD)
        cv2.rectangle(canvas, (x0, PAD), (x0 + SLOT_W, PAD + SLOT_H), (240, 240, 240), 3)

    # 第 1、3 个车位放车，第 2 个留空
    car = cv2.resize(car_img, (SLOT_W - 40, SLOT_H - 60))
    for i in (0, 2):
        x0 = PAD + i * (SLOT_W + PAD) + 20
        y0 = PAD + 30
        canvas[y0:y0 + car.shape[0], x0:x0 + car.shape[1]] = car

    img_path = SAMPLE_DIR / "demo_parking.jpg"
    imwrite_unicode(img_path, canvas)

    spaces = []
    for i in range(3):
        x0 = PAD + i * (SLOT_W + PAD)
        spaces.append({
            "space_number": "A%02d" % (i + 1),
            "polygon": [
                [x0, PAD],
                [x0 + SLOT_W, PAD],
                [x0 + SLOT_W, PAD + SLOT_H],
                [x0, PAD + SLOT_H],
            ],
        })

    json_path = CALIB_DIR / "demo_parking.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "lot_name": "合成测试场景",
            "source": "synthetic",
            "image_size": [canvas.shape[0], canvas.shape[1]],
            "spaces": spaces,
        }, f, ensure_ascii=False, indent=2)

    print("车辆素材:", car_src)
    print("场景图  :", img_path)
    print("标定文件:", json_path)
    print("画布尺寸: %d x %d" % (canvas.shape[1], canvas.shape[0]))


if __name__ == "__main__":
    main()
