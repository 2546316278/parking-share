# -*- coding: utf-8 -*-
"""临时脚本：合成一个 3 车位的测试场景，用于验证检测链路是否跑通。
   仅用于代码自测，不代表真实场景精度。"""
import json
import numpy as np
import cv2

SRC = "D:/停车场/night.png"
OUT_DIR = "D:/shared-parking/data"

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
print("源图", w, h)

SLOT_W, SLOT_H = 620, 440
PAD = 20
canvas = np.full((SLOT_H + PAD * 2, SLOT_W * 3 + PAD * 4, 3), 110, np.uint8)

# 白线画出 3 个车位
for i in range(3):
    x0 = PAD + i * (SLOT_W + PAD)
    cv2.rectangle(canvas, (x0, PAD), (x0 + SLOT_W, PAD + SLOT_H), (240, 240, 240), 3)

# 第 1、3 个车位贴车，第 2 个留空
car = cv2.resize(img, (SLOT_W - 40, SLOT_H - 60))
for i in (0, 2):
    x0 = PAD + i * (SLOT_W + PAD) + 20
    y0 = PAD + 30
    canvas[y0:y0 + car.shape[0], x0:x0 + car.shape[1]] = car

cv2.imwrite(OUT_DIR + "/demo_parking.jpg", canvas)

spaces = []
for i in range(3):
    x0 = PAD + i * (SLOT_W + PAD)
    spaces.append({
        "space_number": "A%02d" % (i + 1),
        "polygon": [[x0, PAD], [x0 + SLOT_W, PAD], [x0 + SLOT_W, PAD + SLOT_H], [x0, PAD + SLOT_H]],
    })

with open(OUT_DIR + "/calibrations/demo_parking.json", "w", encoding="utf-8") as f:
    json.dump({
        "lot_name": "合成测试场景",
        "source": "synthetic",
        "image_size": [canvas.shape[0], canvas.shape[1]],
        "spaces": spaces,
    }, f, ensure_ascii=False, indent=2)

print("已生成:", OUT_DIR + "/demo_parking.jpg", canvas.shape)
