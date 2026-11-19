# 业务后端（Spring Boot）

共享车位预约系统的业务服务：车位发布、预约、模拟支付、自动核销、订单统计。

**不加载任何视觉模型。** 车位状态由 `backend/vision/` 的 Python 进程写入数据库，本服务只读。

## 技术栈

| 项 | 版本 | 说明 |
|---|---|---|
| Spring Boot | 3.3.5 | 需要 JDK 17+ |
| JDK | 22.0.1 | 本机 `JAVA_HOME` 指向 `C:\Program Files\Java\jdk-22` |
| Maven | 3.9.16 | 构建工具 |
| MySQL | 5.7.24 | 本机 `D:\mys\mysql-5.7.24-winx64`，root/1234 |
| MyBatis-Plus | 3.5.7 | `mybatis-plus-spring-boot3-starter`，注意不是给 SB2 的那个 artifactId |

## 目录

```
springboot/
├── pom.xml
└── src/main/
    ├── java/com/sharedparking/
    │   ├── ParkingApplication.java   启动类
    │   ├── common/                   通用响应封装（Result）
    │   ├── controller/               接口层，一个业务模块一个类
    │   ├── service/                  业务逻辑
    │   ├── mapper/                   数据访问（MyBatis-Plus BaseMapper）
    │   ├── entity/                   数据表映射，一表一类
    │   ├── dto/                      出入参对象（SpaceVO 等）
    │   └── config/                   配置类（Jackson 时间格式）
    └── resources/
        └── application.yml           端口、数据源、MyBatis-Plus、日志
```

## 启动

```bash
cd backend\springboot

# 开发模式
mvn spring-boot:run

# 或打包后运行
mvn -DskipTests package
java -jar target/shared-parking-0.0.1-SNAPSHOT.jar
```

默认端口 8080。启动后访问 `http://localhost:8080/api/health` 应返回：

```json
{"status":"UP","service":"shared-parking-backend","time":"2026-11-19 15:00:37"}
```

## ⚠️ JDK 版本陷阱

本机 `PATH` 里有个 JDK 8 排在前面，所以直接敲 `java -version` 会显示：

```
java version "1.8.0_201"
```

但 `JAVA_HOME` 指向的是 JDK 22，Maven 读 `JAVA_HOME`，所以 **`mvn` 构建用的是 JDK 22，没问题**。

问题出在运行 jar 的时候——用 `java -jar` 会走 PATH 里的 JDK 8，Spring Boot 3 需要 JDK 17+，直接报 `UnsupportedClassVersionError`。

两种解决办法，任选：

```bash
# 办法一：显式指定 JDK 22
"C:\Program Files\Java\jdk-22\bin\java.exe" -jar target\shared-parking-0.0.1-SNAPSHOT.jar

# 办法二：把 JDK 22 的 bin 挪到 PATH 最前面，或者用 mvn spring-boot:run 启动
```

## 当前接口

| 方法 | 路径 | 说明 | 返回示例 |
|---|---|---|---|
| GET | `/api/health` | 健康检查 | `{"status":"UP",...}` |
| GET | `/api/spaces` | 全部车位 | `Result<List<SpaceVO>>` |
| GET | `/api/spaces?onlyAvailable=true` | 当前真正可约的车位 | 过滤掉占用 / 已预约 / 视觉数据过期的 |
| GET | `/api/spaces/{code}` | 按编号查，如 `/api/spaces/A01` | 找不到返回 `code=1002` |

响应统一格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "code": "A01",
    "displayStatus": "已占用",
    "physicalStatus": "occupied",
    "physicalCoverage": 0.4010,
    "physicalUpdatedAt": "2026-11-19 15:51:38",
    "physicalStale": false,
    "businessStatus": "available"
  }
}
```

`displayStatus` 是后端算好的中文综合状态（已占用 / 空闲可约 / 已预约 / 使用中 / 维护中 / 状态未知），
前端直接显示，不要自己拿 `physicalStatus` 再判断一遍。

## 状态判定规则

`SpaceVO.resolveDisplayStatus()` 的优先级顺序不能调换：

```
维护中 / 已停用  >  使用中  >  已预约  >  视觉数据过期  >  已占用  >  空闲可约
```

**视觉数据过期**指 `physical_updated_at` 超过 60 秒没更新（`physicalStale=true`）。
这时无论库里存的是 free 还是 occupied 都不可信——Python 进程可能已经挂了，
最后一次写的 free 会让系统误以为车位空着。所以过期一律显示"状态未知"，
并且 `?onlyAvailable=true` 会把这类车位排除掉。

## 阶段进度

- [x] 骨架 + `/api/health`
- [x] 接 MySQL 5.7，MyBatis-Plus 跑通
- [x] 车位查询接口（`Space` / `SpaceMapper` / `SpaceService` / `SpaceVO`）
- [ ] 业主发布时段（`space_slots`）
- [ ] 预约下单（含时段重叠校验 + 行锁）
- [ ] 模拟支付（`orders` 状态机）
- [ ] 自动核销与冲突记录（`conflict_records`）
- [ ] 订单统计

## 与视觉服务的约定

- 表结构以 `databases/schema.sql` 为唯一来源，两边都不得私改
- 字符集必须是 `utf8mb4`，本机 MySQL 服务端默认 latin1，连接串必须带 `characterEncoding=UTF-8`
- 时区统一 `Asia/Shanghai`，Java 连接串要写 `serverTimezone=Asia/Shanghai`，
  否则 `CURRENT_TIMESTAMP` 落库会差 8 小时，直接影响计费
- 视觉进程只写 `spaces.physical_*` 与 `space_status_log`，本服务只写 `spaces.business_status` 及业务表，两边不交叉
- 本服务**永远不主动调用视觉进程**，只读它留下的字段（决策 D1）
