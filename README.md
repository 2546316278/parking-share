# 基于视觉车位状态检测的共享车位预约分配系统

用摄像头画面自动判断每个车位是否被占用，业主把闲置时段发布出来，访客在线预约，
系统通过视觉检测对预约做自动核销——解决"业主手动标记状态不及时、预约了车位却被占"的问题。

> 技术选型见 [docs/TECH_STACK.md](docs/TECH_STACK.md)　目录与文件约定见 [docs/STRUCTURE.md](docs/STRUCTURE.md)

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 项目骨架、环境、技术栈定稿 | ✅ 完成 |
| 1 | 视觉检测链路（标定 + 车辆检测 + 状态判定） | ✅ 基础链路跑通，待真实素材验证 |
| 2 | 数据库设计与状态写入 | ⬜ 待做 |
| 3 | 业务接口（发布 / 预约 / 支付） | ⬜ 待做 |
| 4 | 自动核销与超时处理 | ⬜ 待做 |
| 5 | 前端看板与统计 | ⬜ 待做 |
| 6 | 对比实验与论文图表 | ⬜ 待做 |

## 目录结构

```
shared-parking/
├── vision/                视觉服务（独立进程）
│   ├── config.py          所有可调参数，调参只改这一个文件
│   ├── calibrate.py       车位 ROI 标定工具
│   ├── detector.py        车辆检测 + 占用判定 + 标注输出
│   └── smoother.py        状态时序平滑
├── server/                Flask 业务后端
│   ├── models/            数据表 ORM 模型
│   ├── routes/            接口蓝图
│   └── services/          可复用业务逻辑（计费、核销等）
├── web/                   Vue 3 前端
├── experiments/           论文对比实验，不进主链路
│   └── outputs/           实验产物（不入库）
├── scripts/               一次性 / 维护脚本，不进主链路
├── tests/                 单元测试
├── sql/                   建表脚本，schema.sql 为唯一入口
├── docs/
│   ├── TECH_STACK.md      技术栈与选型决策
│   └── STRUCTURE.md       目录与文件约定
├── weights/               YOLO 权重（不入库）
├── data/
│   ├── videos/            你拍的停车场素材（不入库）
│   ├── calibrations/      标定结果 JSON（不入库）
│   ├── snapshots/         检测截图，核销取证用（不入库）
│   └── samples/           自测用合成图（入库）
├── requirements/
│   ├── vision.txt         视觉组（环境已预装，勿直接装）
│   ├── server.txt         服务组
│   └── dev.txt            实验与测试组
└── requirements.txt       汇总入口（只装 server + dev）
```

## 环境

- Python 3.9.24（conda 环境 `yolov8_env`）
- torch 2.6.0+cu118 / ultralytics 8.3.237 / opencv 4.6.0 / numpy 1.26.4
- 装依赖：`pip install -r requirements.txt`（只含服务组与实验组）
- 视觉组依赖已在环境里，装法见 `requirements/vision.txt` 里的注释

```bash
conda activate yolov8_env
```

## 快速开始

### 0. 链路自测（可选，不依赖真实素材）

合成一张 3 车位测试图，验证整条链路没断：

```bash
python scripts/make_demo.py
cd vision
python detector.py --source ../data/samples/demo_parking.jpg \
                   --calib ../data/calibrations/demo_parking.json \
                   --save ../data/samples/demo_result.jpg
```

预期输出：A01 占用、A02 空闲、A03 占用。

### 1. 标定车位（用真实素材）

把停车场视频或图片放进 `data/videos/`，然后逐个框出车位：

```bash
cd vision
python calibrate.py --source ../data/videos/parking.mp4 --at 3
```

操作：左键点四个角 → 右键闭合 → 全部画完按 `s` 保存 → `q` 退出。
结果写入 `data/calibrations/<源文件名>.json`。

> 一次标定长期有效，摄像头位置不能动。换摄像头 / 换机位后必须重新标定。

### 2. 跑检测

```bash
cd vision

# 单张图片
python detector.py --source ../data/videos/lot.jpg --calib ../data/calibrations/lot.json --save out.jpg

# 视频（弹窗预览，按 q 退出）
python detector.py --source ../data/videos/parking.mp4 --calib ../data/calibrations/parking.json

# 摄像头
python detector.py --source 0 --calib ../data/calibrations/parking.json

# 无窗口批量跑，输出逐帧结果
python detector.py --source ../data/videos/parking.mp4 --calib ... --no-show --log result.jsonl
```

## 核心判定逻辑

1. YOLOv8n 只检测车辆（COCO 的 car / motorcycle / bus / truck），不直接检测"空车位"
2. 算每辆车落在每个车位多边形内的**面积占比**（coverage）
3. **贪心分配**：一辆车只归属覆盖率最高的车位，避免一辆车把相邻两个车位都判成占用
4. coverage 超过 0.35 判为占用
5. **5 帧滑动窗口投票**，连续 3 帧一致才切换状态，压掉单帧抖动

可调参数集中在 `vision/config.py` 的 `COVERAGE_THRESHOLD` 与 `SMOOTH_*`。

## 注意事项

- `cv2.putText` 不支持中文，画面标注统一用 ASCII（编号 + OCC/FREE + 覆盖率）
- Windows 中文路径需用 `np.fromfile` + `cv2.imdecode` 读取，`detector.py` 里已封装 `imread_unicode`
- `numpy` 固定在 1.26.4，不要升级到 2.x（与 torch 2.6 存在兼容问题）
- 模型权重放在 `weights/`，不纳入版本控制，换机需另行下载
- `data/` 下的视频、标定结果、截图都不入库，换机需重新获取
