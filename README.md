# 基于视觉车位状态检测的共享车位预约分配系统

用摄像头画面自动判断每个车位是否被占用，业主把闲置时段发布出来，访客在线预约，
系统通过视觉检测对预约做自动核销——解决"业主手动标记状态不及时、预约了车位却被占"的问题。

> 技术选型见 [docs/TECH_STACK.md](docs/TECH_STACK.md)

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 项目骨架、环境、技术栈定稿 | ✅ 完成 |
| 1 | 视觉检测链路（标定 + 车辆检测 + 状态判定） | ✅ 基础链路跑通 |
| 2 | 数据库设计与状态写入 | ⬜ 待做 |
| 3 | 业务接口（发布 / 预约 / 支付） | ⬜ 待做 |
| 4 | 自动核销与超时处理 | ⬜ 待做 |
| 5 | 前端看板与统计 | ⬜ 待做 |
| 6 | 对比实验与论文图表 | ⬜ 待做 |

## 目录结构

```
shared-parking/
├── vision/                 视觉服务（独立进程）
│   ├── config.py           所有可调参数
│   ├── calibrate.py        车位 ROI 标定工具
│   ├── detector.py         车辆检测 + 占用判定
│   └── smoother.py         状态时序平滑
├── server/                 Flask 业务后端（待建）
├── web/                    Vue 3 前端（待建）
├── experiments/            论文对比实验（待建）
├── models/                 YOLO 权重
├── data/
│   ├── videos/             测试视频（不入库）
│   ├── calibrations/       标定结果 JSON
│   └── snapshots/          检测截图（核销取证用，不入库）
├── docs/
│   └── TECH_STACK.md       技术栈与选型决策
└── requirements.txt
```

## 环境

- Python 3.9.24（conda 环境 `yolov8_env`）
- torch 2.6.0+cu118 / ultralytics 8.3.237 / opencv 4.6.0
- 新增依赖：`APScheduler`、`PyJWT`

```bash
conda activate yolov8_env
```

## 快速开始

### 1. 标定车位

准备一张停车场画面（视频会取指定秒数的帧），逐个框出车位：

```bash
cd vision
python calibrate.py --source ../data/videos/parking.mp4 --at 3
```

操作：左键点四个角 → 右键闭合 → 全部画完按 `s` 保存 → `q` 退出。
结果写入 `data/calibrations/<源文件名>.json`。

### 2. 跑检测

```bash
cd vision

# 单张图片
python detector.py --source demo.jpg --calib ../data/calibrations/demo.json --save out.jpg

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
- 模型权重 `models/yolov8n.pt` 不纳入版本控制，换机需另行下载
