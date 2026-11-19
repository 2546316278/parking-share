# 业务后端（Spring Boot）

共享车位预约系统的业务服务：车位发布、预约、模拟支付、自动核销、订单统计。

**不加载任何视觉模型。** 车位状态由 `backend/vision/` 的 Python 进程写入数据库，本服务只读。

## 技术栈

| 项 | 版本 | 说明 |
|---|---|---|
| Spring Boot | 3.3.5 | 需要 JDK 17+ |
| JDK | 22.0.1 | 本机 `JAVA_HOME` 指向 `C:\Program Files\Java\jdk-22` |
| Maven | 3.9.16 | 构建工具 |
| MySQL | 8.0.x | 阶段 2 接入 |
| MyBatis-Plus | 3.5.7 | 阶段 2 接入，见 `pom.xml` 注释块 |

## 目录

```
springboot/
├── pom.xml
└── src/main/
    ├── java/com/sharedparking/
    │   ├── ParkingApplication.java   启动类
    │   ├── controller/               接口层，一个业务模块一个类
    │   ├── service/                  业务逻辑
    │   ├── mapper/                   数据访问（MyBatis）
    │   ├── entity/                   数据表映射
    │   └── config/                   配置类
    └── resources/
        └── application.yml           端口、数据源、日志
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

## 当前状态

只有一个 `/api/health` 接口，用于验证环境能跑通。

业务接口等阶段 2 数据库设计完成后开始写，顺序是：

1. `databases/schema.sql` 建表（业主、车位、可预约时段、预约、订单）
2. 对应的 `entity/` + `mapper/`
3. `controller/` 接口
4. 与 `backend/vision/` 的状态字段对接

## 与视觉服务的约定

- 表结构以 `databases/schema.sql` 为唯一来源，两边都不得私改
- 字符集必须是 `utf8mb4`
- 时区统一 `Asia/Shanghai`，Java 连接串要写 `serverTimezone=Asia/Shanghai`
- 视觉进程只写车位物理状态，本服务只写业务状态，两边不交叉
