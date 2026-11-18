# 目录结构与文件约定

> 目的：任何新文件都有唯一确定的去处，避免根目录越堆越乱。
> 新增目录或调整结构时，同步更新本文件。

---

## 一、顶层目录职责

| 目录 | 职责 | 运行方式 | 阶段 |
|---|---|---|---|
| `vision/` | 视觉检测服务：读视频帧 → 检测车辆 → 判定车位状态 → 写库 | 独立进程 | 1 |
| `server/` | Flask 业务后端：发布 / 预约 / 支付 / 核销 / 统计接口 | 独立进程 | 2-4 |
| `web/` | Vue 3 前端：车位看板、预约页面、管理后台 | `npm run dev` | 5 |
| `experiments/` | 论文对比实验，**不进主链路** | 手动跑 | 6 |
| `scripts/` | 一次性脚本、维护工具，**不进主链路** | 手动跑 | 任意 |
| `tests/` | 单元测试 | `pytest` | 任意 |
| `sql/` | 建表 / 初始化脚本，`schema.sql` 是唯一建库入口 | 手动执行 | 2 |
| `docs/` | 设计文档 | — | — |
| `data/` | 运行期数据（大多不入库） | — | — |
| `weights/` | YOLO 权重文件（**不入库**） | — | — |
| `requirements/` | 依赖清单，按组拆分 | — | — |

---

## 二、`data/` 内部约定

| 子目录 | 放什么 | 入库 | 说明 |
|---|---|---|---|
| `videos/` | 你拍的停车场视频 / 原图 | ❌ | 体积大；文件丢了重新拍即可 |
| `calibrations/` | 标定产物 `<场景名>.json` | ❌ | 可重新标定；换机后要重做 |
| `snapshots/` | 检测截图（预约核销时留作取证） | ❌ | 运行期自动生成 |
| `samples/` | 代码自测用的合成图 / 样例图 | ✅ | 体积小，保证 clone 后可跑通 |

**判断规则**：能用一条命令重新生成的，一律不入库；只有"重新获取需要人工成本"且"体积小"的才入库。

---

## 三、命名约定

| 类型 | 规则 | 示例 |
|---|---|---|
| Python 模块 | 小写 + 下划线 | `detector.py`、`license_plate.py` |
| 类 | 大驼峰 | `ParkingDetector`、`StatusSmoother` |
| 函数 / 变量 | 小写下划线 | `_assign_vehicles`、`coverage` |
| 常量 | 全大写 | `COVERAGE_THRESHOLD` |
| 标定文件 | 与场景同名 | `parking_lot_a.json`、`demo_parking.json` |
| 车位编号 | 区域字母 + 两位数字 | `A01`、`B12` |
| 数据库表 | 小写下划线，复数 | `spaces`、`reservations`、`space_status_log` |

数据库**表名和字段名统一用英文**，界面文案和注释用中文。混用会导致 SQL 里到处要反引号。

---

## 四、`scripts/` 与 `experiments/` 的区别

这两个目录都"不进主链路"，但性质不同：

- `scripts/` —— **工具性**。合成测试图、批量重命名、数据迁移。跑完就结束，不产出论文数据。
- `experiments/` —— **论证性**。跑对比实验、生成图表、产出论文里要引用的数字。结果必须可复现，脚本开头要写明"这篇实验回答什么问题"。

`experiments/outputs/` 里的产物不入库，但生成它们的脚本必须入库。

---

## 五、不入库清单（`.gitignore` 已覆盖）

```
.env                密钥
data/videos/*       视频
data/snapshots/*    截图
data/calibrations/*.json  标定结果
weights/*.pt        模型权重
experiments/outputs/*
*.jsonl             检测日志
```

---

## 六、新增代码时该放哪

| 你想做的事 | 放哪 |
|---|---|
| 加一个检测后处理算法 | `vision/` |
| 加一个业务接口 | `server/routes/` |
| 加一段可复用的业务逻辑（如计费） | `server/services/` |
| 加一张表的 ORM 模型 | `server/models/` |
| 加一个前端页面 | `web/src/views/` |
| 验证某个算法比另一个准 | `experiments/` |
| 临时合成一张测试图 | `scripts/` |

**不要**在项目根目录直接写 `.py` 文件。根目录只放 `README.md`、`requirements.txt`、`.gitignore`、`.env.example` 这四个配置类文件。
