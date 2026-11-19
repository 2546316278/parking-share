# 数据库设计说明

`schema.sql` 是**唯一的建库入口**，不要手工在 Navicat / Workbench 里点表格建字段——
所有结构变更都必须落回这个文件，否则换机重装时数据结构就丢了。

---

## 一、怎么建库

```bash
# 本机 MySQL 是 5.7.24，客户端在 D:\mys\mysql-5.7.24-winx64\bin\
cd D:\shared-parking
"D:/mys/mysql-5.7.24-winx64/bin/mysql.exe" -uroot -p1234 --default-character-set=utf8mb4 < databases/schema.sql
```

`--default-character-set=utf8mb4` 不能省。本机 MySQL 服务端默认字符集是 `latin1`，
不加这个参数执行脚本里的中文注释和种子数据会变问号。

验证：

```bash
"D:/mys/mysql-5.7.24-winx64/bin/mysql.exe" -uroot -p1234 --default-character-set=utf8mb4 -e "USE shared_parking; SHOW TABLES;"
```

预期输出 7 张表：`users` / `spaces` / `space_slots` / `reservations` / `orders` / `space_status_log` / `conflict_records`。

> ⚠️ 脚本开头有 `DROP TABLE`，**重复执行会清空全部业务数据**。生产环境别直接跑。

---

## 二、表关系

```
users (业主/访客/管理员)
  │
  ├─1:N─→ spaces            业主拥有多个车位        (spaces.owner_id)
  │          │
  │          └─1:N─→ space_slots   车位被发布多个可预约时段
  │                        │
  │                        └─1:N─→ reservations   一个时段可被预约（实际只会被约走一次）
  │                                      │
  ├─1:N─→ reservations (visitor_id)      ├─1:1─→ orders
  │                                      │
  └─1:N─→ orders (payer_id)              └─1:N─→ conflict_records
                                                  
spaces ─1:N─→ space_status_log    车位状态变化流水
```

外键全部真实生效（InnoDB），删用户会连带失败，这是故意的——防止误删业主导致车位成孤儿。

---

## 三、核心设计：双状态字段

`spaces` 表有两个状态字段，**永远不要合并成一个**（决策 D2）：

| 字段 | 谁写 | 取值 | 回答的问题 |
|---|---|---|---|
| `physical_status` | **只有**视觉进程 | `free` / `occupied` / `unknown` | 摄像头看到的是什么 |
| `business_status` | **只有**业务进程 | `available` / `reserved` / `in_use` / `maintenance` / `disabled` | 按预约规则应该是什么 |

两个字段不一致时，就是系统要处理的冲突：

| physical | business | 含义 | 对应冲突类型 |
|---|---|---|---|
| `occupied` | `reserved` | 预约了但停进来的是别的车 | `occupied_by_other` |
| `free` | `in_use` | 到了预约时间人没来 | `no_show` |
| `free` | `reserved` | 预约时段内车位空着 | `no_show` |
| `occupied` | `available` | 没被预约却被占了（临停或业主自用） | 不告警，属正常 |
| `unknown` | 任意 | 视觉服务挂了或超时未上报 | 需监控 |

`physical_updated_at` 超过阈值（建议 60 秒）没更新，`physical_status` 就应当作废视为 `unknown`，
不要让陈旧数据继续参与冲突判定。

---

## 四、常用查询

```sql
-- 当前可预约的车位（业务可用 + 物理空闲）
SELECT s.code, s.zone_name, s.guide_price, s.physical_coverage
FROM spaces s
WHERE s.business_status = 'available'
  AND s.physical_status = 'free'
  AND s.physical_updated_at > DATE_SUB(NOW(), INTERVAL 60 SECOND);

-- 某车位未来 7 天的已发布时段
SELECT id, start_time, end_time, price_per_hour, status
FROM space_slots
WHERE space_id = 1
  AND start_time > NOW()
  AND start_time < DATE_ADD(NOW(), INTERVAL 7 DAY)
ORDER BY start_time;

-- 待处理的预约冲突（定时任务扫这张表）
SELECT c.id, c.conflict_type, s.code, r.reservation_no, c.detail, c.detected_at
FROM conflict_records c
JOIN spaces s ON s.id = c.space_id
JOIN reservations r ON r.id = c.reservation_id
WHERE c.handled = 0
ORDER BY c.detected_at;

-- 某车位今天的状态变化（排查状态抖动）
SELECT detected_at, physical_status, coverage, source
FROM space_status_log
WHERE space_id = 1
  AND detected_at >= CURDATE()
ORDER BY detected_at;

-- 业主收入统计
SELECT u.real_name AS owner, s.code, COUNT(o.id) AS order_count, SUM(o.amount) AS total
FROM orders o
JOIN reservations r ON r.id = o.reservation_id
JOIN spaces s ON s.id = r.space_id
JOIN users u ON u.id = s.owner_id
WHERE o.status = 'completed'
GROUP BY u.real_name, s.code;
```

---

## 五、时段重叠必须由应用层校验

唯一键 `uk_slots_space_time (space_id, start_time, end_time)` 只能拦住**完全相同**的两条记录。
`8:00-12:00` 和 `10:00-14:00` 这种部分重叠，数据库拦不住——MySQL 没有 PostgreSQL 的
排他约束（`EXCLUDE USING gist`）。

预约接口里必须这样写，否则并发下会卖出两个重叠时段：

```sql
-- 在同一个事务里，先把车位行锁住
SELECT id FROM spaces WHERE id = ? FOR UPDATE;

-- 再检查是否已有重叠的预约
SELECT COUNT(*) FROM reservations
WHERE space_id = ?
  AND status IN ('pending','confirmed','active')
  AND start_time < ?   -- 新预约的 end_time
  AND end_time   > ?   -- 新预约的 start_time
  FOR UPDATE;
```

`start_time < 新end AND end_time > 新start` 是标准的区间重叠判定式，记住它。

第一阶段不用 Redis 分布式锁，靠 InnoDB 行锁即可（决策 D3）。压测显示瓶颈后再优化。

---

## 六、MySQL 5.7 的三个坑

1. **CHECK 约束是假的**。5.7 会解析 `CHECK (...)` 但直接忽略，不报错也不生效。
   所以脚本里改用触发器保证 `end_time > start_time`，已验证：插入倒序时间会抛
   `ERROR 1644: space_slots: end_time 必须晚于 start_time`。

2. **默认字符集是 latin1**。每次连库都要带 `--default-character-set=utf8mb4`，
   JDBC 连接串里也要 `characterEncoding=utf8&useUnicode=true`。

3. **时区**。`CURRENT_TIMESTAMP` 用的是会话时区，`@@time_zone` 现在是 `SYSTEM`。
   JDBC 必须带 `serverTimezone=Asia/Shanghai`，否则 `created_at` 落库会差 8 小时。

> 5.7.24 已于 2023 年 10 月停止支持，毕业设计阶段不折腾升级；如果后面要上 8.0，
> 把 `utf8mb4_general_ci` 改成 `utf8mb4_0900_ai_ci` 并把触发器换回 CHECK 约束即可。

---

## 七、种子数据

脚本第 9 节插入了开发自测数据：

| 账号 | 密码 | 角色 | 说明 |
|---|---|---|---|
| `admin` | `123456` | 管理员 | |
| `owner01` | `123456` | 业主 | 拥有 A01、A02 |
| `owner02` | `123456` | 业主 | 拥有 A03 |
| `visitor01` | `123456` | 访客 | |

车位 `A01` / `A02` / `A03` 与合成测试图 `data/samples/demo_parking.jpg` 里的三个车位一一对应，
方便视觉检测结果直接对照着写库调试。

**上线前必须删掉第 9 节**，并把所有密码改掉。

---

## 八、和代码怎么对接

| 层 | 位置 | 职责 |
|---|---|---|
| 建表 | `databases/schema.sql` | 唯一入口 |
| 实体类 | `backend/springboot/.../entity/` | 一表一类，字段名用驼峰对应下划线 |
| 数据访问 | `backend/springboot/.../mapper/` | MyBatis-Plus，简单查询用内置方法 |
| 视觉写入 | `backend/vision/` 直连 MySQL | 只写 `spaces.physical_*` 和 `space_status_log` |

视觉服务不经过 Spring Boot 写库（决策 D1），两条进程各写各的字段，靠数据库字段通信。

字段名规划（MyBatis-Plus 默认驼峰映射，无需逐个 `@TableField`）：

| 数据库 | Java 实体 |
|---|---|
| `physical_status` | `physicalStatus` |
| `physical_coverage` | `physicalCoverage` |
| `business_status` | `businessStatus` |
| `space_id` | `spaceId` |
