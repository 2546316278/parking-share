# 目录结构与文件约定

> 目的：任何新文件都有唯一确定的去处，避免根目录越堆越乱。
> 新增目录或调整结构时，同步更新本文件。

---

## 一、顶层结构

```
shared-parking/
├── backend/                服务端全部代码
│   ├── vision/             视觉检测服务（Python，独立进程）
│   └── springboot/         业务后端（Java）
├── frontend/               前端
├── databases/              数据库脚本
├── docs/                   设计文档
├── experiments/            论文对比实验（不进主链路）
├── scripts/                一次性 / 维护脚本
├── tests/                  单元测试
├── weights/                YOLO 权重（不入库）
├── data/                   运行期数据
└── requirements/           依赖清单
```

---

## 二、各目录职责

| 目录 | 职责 | 运行方式 | 阶段 |
|---|---|---|---|
| `backend/vision/` | 车位状态检测（`detector.py`），独立进程 | 独立进程 | 1 |
| `backend/springboot/` | 业务接口：发布 / 预约 / 支付 / 核销 / 统计 | 独立进程 | 2-4 |
| `frontend/` | Vue 3：车位看板、预约页、管理后台 | `npm run dev` | 5 |
| `databases/` | 建表 / 初始化数据，`schema.sql` 是唯一建库入口 | 手动执行 | 2 |
| `experiments/` | 论文对比实验，**不进主链路** | 手动跑 | 6 |
| `scripts/` | 一次性脚本、维护工具，**不进主链路** | 手动跑 | 任意 |
| `tests/` | 单元测试 | `pytest` | 任意 |
| `docs/` | 设计文档 | — | — |
| `data/` | 运行期数据（大多不入库） | — | — |
| `weights/` | YOLO 权重（**不入库**） | — | — |

---

## 三、`backend/` 为什么这样分

```
backend/
├── vision/         独立进程：Python + YOLO，写 physical_status
└── springboot/     独立进程：Java，处理 HTTP 请求，读写 business_status
```

**两个服务必须分开跑，不能合并**，原因见 `docs/TECH_STACK.md` 决策 D1：

1. YOLOv8 是 Python 生态，无法在 JVM 内运行
2. 模型加载要几秒，塞进 Web 服务会拖慢启动
3. 模型实例不是线程安全的，检测线程和请求线程共用一个实例会崩
4. 检测服务崩了不应该让整个网站挂掉，反之亦然

所以 `backend/springboot/` 下**不放任何模型代码**，它只负责业务逻辑和数据库读写。
两者之间通过数据库字段通信，不直接调用函数。

### `backend/springboot/` 内部

```
springboot/
├── pom.xml
└── src/main/java/com/sharedparking/
    ├── ParkingApplication.java   启动类
    ├── common/                   通用响应封装（Result）
    ├── controller/               接口层，一个业务模块一个类
    ├── service/                  业务逻辑
    ├── mapper/                   数据访问（MyBatis-Plus）
    ├── entity/                   数据表映射
    ├── dto/                      出入参对象（SpaceVO 等）
    └── config/                   配置类
```

| 包 | 放什么 | 举例 |
|---|---|---|
| `common/` | 跨模块复用的基础类 | `Result`（统一响应）、后续的 `BizException` |
| `controller/` | HTTP 接口，只做参数接收与响应封装 | `SpaceController.java`、`OrderController.java` |
| `service/` | 可复用的业务逻辑，不碰 HTTP 层 | `BillingService`（计费）、`VerifyService`（核销） |
| `mapper/` | 数据访问接口，继承 `BaseMapper` | `SpaceMapper.java` |
| `entity/` | 数据表对应的实体类，字段与表一一对应 | `Space.java`、`Reservation.java` |
| `dto/` | 给前端看的出入参对象，不放数据库映射 | `SpaceVO.java`、后续的 `ReserveRequest` |
| `config/` | 配置类 | `JacksonConfig`（时间格式）、后续的 `MyBatisPlusConfig`（分页） |

判断规则：**能被两个以上接口调用的逻辑，就抽到 `service/`**；只服务一个接口的直接写在 controller 里。

**entity 与 dto 的区别**：entity 是数据库表的镜像，字段全是英文枚举值；dto 是给前端看的，
可以加中文描述字段（如 `displayStatus`）和计算字段（如 `physicalStale`）。
不要让 controller 直接返回 entity —— 字段一多，前端就得自己翻译一遍枚举，每个页面重复写。

---

## 四、`data/` 内部约定

| 子目录 | 放什么 | 入库 | 说明 |
|---|---|---|---|
| `videos/` | 你拍的停车场视频 / 原图 | ❌ | 体积大；丢了重新拍 |
| `calibrations/` | 标定产物 `<场景名>.json` | ❌ | 可重新标定；换机后要重做 |
| `snapshots/` | 检测截图（核销取证用） | ❌ | 运行期自动生成 |
| `samples/` | 代码自测用的合成图 | ✅ | 体积小，保证 clone 后可跑通 |

`data/` 放在**项目根**而不是 `backend/` 下，因为视觉服务和后端都要读它（截图、标定），放任何一方里面都会让另一方绕路。

**判断规则**：能用一条命令重新生成的，一律不入库；只有"重新获取需要人工成本"且"体积小"的才入库。

---

## 五、命名约定

| 类型 | 规则 | 示例 |
|---|---|---|
| Python 模块 | 小写 + 下划线 | `detector.py`、`smoother.py` |
| 类 | 大驼峰 | `ParkingDetector`、`StatusSmoother` |
| 函数 / 变量 | 小写下划线 | `_assign_vehicles`、`coverage` |
| 常量 | 全大写 | `COVERAGE_THRESHOLD` |
| 标定文件 | 与场景同名 | `parking_lot_a.json`、`demo_parking.json` |
| 车位编号 | 区域字母 + 两位数字 | `A01`、`B12` |
| 数据库表 | 小写下划线，复数 | `spaces`、`reservations`、`space_status_log` |

数据库**表名和字段名统一用英文**，界面文案和注释用中文。混用会导致 SQL 里到处要反引号。

---

## 六、`scripts/` 与 `experiments/` 的区别

这两个目录都"不进主链路"，但性质不同：

- `scripts/` —— **工具性**。合成测试图、批量重命名、数据迁移。跑完就结束，不产出论文数据。
- `experiments/` —— **论证性**。跑对比实验、生成图表、产出论文里要引用的数字。结果必须可复现，脚本开头要写明"这个实验回答什么问题"。

`experiments/outputs/` 里的产物不入库，但生成它们的脚本必须入库。

---

## 七、不入库清单（`.gitignore` 已覆盖）

```
.env                        密钥
data/videos/*               视频
data/snapshots/*            截图
data/calibrations/*.json    标定结果
weights/*.pt                模型权重
experiments/outputs/*       实验产物
*.jsonl                     检测日志
.idea/ .vscode/             IDE 配置
venv/ .venv/                虚拟环境
```

---

## 八、新增代码时该放哪

| 你想做的事 | 放哪 |
|---|---|
| 加一个检测后处理算法 | `backend/vision/` |
| 加一个业务接口 | `backend/springboot/.../controller/` |
| 加一段可复用的业务逻辑（如计费） | `backend/springboot/.../service/` |
| 加一张表的实体类 | `backend/springboot/.../entity/` |
| 给前端加一个返回结构 | `backend/springboot/.../dto/` |
| 加建表语句 | `databases/` |
| 加一个前端页面 | `frontend/src/views/` |
| 验证某个算法比另一个准 | `experiments/` |
| 临时合成一张测试图 | `scripts/` |

**不要**在项目根目录直接写 `.py` 文件。根目录只放 `README.md`、`requirements.txt`、`.gitignore`、`.env.example` 这四个配置类文件。
