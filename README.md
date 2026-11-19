# 基于视觉车位状态检测的共享车位预约分配系统

用摄像头画面自动判断每个车位是否被占用，业主把闲置时段发布出来，访客在线预约，
系统通过视觉检测对预约做自动核销——解决"业主手动标记状态不及时、预约了车位却被占"的问题。

> 技术选型见 [docs/TECH_STACK.md](docs/TECH_STACK.md)　目录与文件约定见 [docs/STRUCTURE.md](docs/STRUCTURE.md)

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 项目骨架、环境、技术栈定稿 | ✅ 完成 |
| 1 | 视觉检测链路（标定 + 车辆检测 + 状态判定） | ✅ 基础链路跑通，待真实素材验证 |
| 2 | 数据库设计与状态写入 | 🟡 7 张表已建（`databases/schema.sql`），待接入 Spring Boot |
| 3 | 业务接口（发布 / 预约 / 支付） | ⬜ 待做 |
| 4 | 自动核销与超时处理 | ⬜ 待做 |
| 5 | 前端看板与统计 | ⬜ 待做 |
| 6 | 对比实验与论文图表 | ⬜ 待做 |

## 目录结构

```
shared-parking/
├── backend/               服务端全部代码
│   ├── vision/            视觉服务（Python，独立进程）
│   │   ├── config.py      所有可调参数，调参只改这一个文件
│   │   ├── calibrate.py   车位 ROI 标定工具
│   │   ├── detector.py    车辆检测 + 占用判定 + 标注输出
│   │   ├── smoother.py    车位状态时序平滑
│   │   └── utils.py       中文路径读写、模型路径解析
│   └── springboot/        业务后端（Java，独立进程）
│       ├── pom.xml
│       └── src/main/java/com/sharedparking/
│           ├── controller/    接口层
│           ├── service/       业务逻辑（计费、核销）
│           ├── mapper/        数据访问
│           ├── entity/        数据表映射
│           └── config/        配置类
├── frontend/              Vue 3 前端
├── databases/             建表脚本，schema.sql 为唯一入口，设计说明见 README.md
├── experiments/           论文对比实验，不进主链路
│   └── outputs/           实验产物（不入库）
├── scripts/               一次性 / 维护脚本，不进主链路
├── tests/                 单元测试
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

**视觉服务（Python）**

- Python 3.9.24（conda 环境 `yolov8_env`）
- torch 2.6.0+cu118 / ultralytics 8.3.237 / opencv 4.6.0 / numpy 1.26.4
- 装依赖：`pip install -r requirements.txt`（只含服务组与实验组）
- 视觉组依赖已在环境里，装法见 `requirements/vision.txt` 里的注释

```bash
conda activate yolov8_env
```

**业务后端（Java）**

- JDK 22（`C:\Program Files\Java\jdk-22`）
- Maven 3.9+
- MySQL 8.x（阶段 2 接入，字符集必须 utf8mb4）

> Python 和 Java 是两个独立进程，各自用各自的终端启动，互不依赖。

## 快速开始

### 0. 链路自测（可选，不依赖真实素材）

合成一张 3 车位测试图，验证整条链路没断：

```bash
python scripts/make_demo.py
cd backend\vision
python detector.py --source ..\..\data\samples\demo_parking.jpg ^
                   --calib ..\..\data\calibrations\demo_parking.json ^
                   --save ..\..\data\samples\demo_result.jpg
```

预期输出：A01 占用、A02 空闲、A03 占用。

### 1. 标定车位（用真实素材）

把停车场视频或图片放进 `data\videos\`，然后逐个框出车位：

```bash
cd backend\vision
python calibrate.py --source ..\..\data\videos\parking.mp4 --at 3
```

操作：左键点四个角 → 右键闭合 → 全部画完按 `s` 保存 → `q` 退出。
结果写入 `data/calibrations/<源文件名>.json`。

> 一次标定长期有效，摄像头位置不能动。换摄像头 / 换机位后必须重新标定。

### 2. 跑检测

```bash
cd backend\vision

# 单张图片
python detector.py --source ..\..\data\videos\lot.jpg --calib ..\..\data\calibrations\lot.json --save out.jpg

# 视频（弹窗预览，按 q 退出）
python detector.py --source ..\..\data\videos\parking.mp4 --calib ..\..\data\calibrations\parking.json

# 摄像头
python detector.py --source 0 --calib ..\..\data\calibrations\parking.json

# 无窗口批量跑，输出逐帧结果
python detector.py --source ..\..\data\videos\parking.mp4 --calib ... --no-show --log result.jsonl
```

### 3. 建库

```bash
cd D:\shared-parking
"D:/mys/mysql-5.7.24-winx64/bin/mysql.exe" -uroot -p1234 --default-character-set=utf8mb4 < databases/schema.sql
```

7 张表 + 种子数据，`--default-character-set=utf8mb4` 不能省（服务端默认 latin1，不加会乱码）。
表结构、双状态字段用法、常用查询见 [databases/README.md](databases/README.md)。

### 4. 启动业务后端

```bash
cd backend\springboot
mvn -DskipTests package

# 注意：不要直接用 java，PATH 里的 java 可能是 JDK 8
"C:/Program Files/Java/jdk-22/bin/java.exe" -jar target/shared-parking-backend-1.0.0.jar
```

验证：浏览器打开 http://localhost:8080/api/health ，应返回 `{"status":"UP",...}`。

> ⚠️ **JDK 版本陷阱**：PATH 里 `C:\Program Files\Common Files\Oracle\Java\javapath` 指向 JDK 8 且排在前面，
> 直接敲 `java -jar` 会报 `UnsupportedClassVersionError`。Maven 读 `JAVA_HOME`（JDK 22）所以编译正常，
> 但运行时必须用绝对路径或先把 JDK 22 的 bin 调到 PATH 前面。详见 `backend/springboot/README.md`。

## 核心判定逻辑

1. YOLOv8n 只检测车辆（COCO 的 car / motorcycle / bus / truck），不直接检测"空车位"
2. 算每辆车落在每个车位多边形内的**面积占比**（coverage）
3. **贪心分配**：一辆车只归属覆盖率最高的车位，避免一辆车把相邻两个车位都判成占用
4. coverage 超过 0.35 判为占用
5. **5 帧滑动窗口投票**，连续 3 帧一致才切换状态，压掉单帧抖动

可调参数集中在 `backend/vision/config.py` 的 `COVERAGE_THRESHOLD` 与 `SMOOTH_*`。

## 注意事项

- `cv2.putText` 不支持中文，画面标注统一用 ASCII（编号 + OCC/FREE + 覆盖率）
- Windows 中文路径需用 `np.fromfile` + `cv2.imdecode` 读取，`detector.py` 里已封装 `imread_unicode`
- `numpy` 固定在 1.26.4，不要升级到 2.x（与 torch 2.6 存在兼容问题）
- 模型权重放在 `weights/`，不纳入版本控制，换机需另行下载
- `data/` 下的视频、标定结果、截图都不入库，换机需重新获取
