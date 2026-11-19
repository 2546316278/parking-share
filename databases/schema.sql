-- ============================================================================
--  共享车位预约分配系统 · 建库建表脚本
-- ----------------------------------------------------------------------------
--  唯一入口，重复执行会清空全部业务数据：
--      mysql -uroot -p < databases/schema.sql
--
--  目标环境：MySQL 5.7.24（本机实际版本）
--  兼容性说明：
--    · 字符集统一 utf8mb4 / utf8mb4_general_ci（5.7 不支持 0900_ai_ci）
--    · 不写 CHECK 约束 —— 5.7 会解析但静默忽略，写了等于骗自己；
--      时间区间合法性改由应用层 + 触发器保证，见文末第 8 节
--    · 时间字段统一 DATETIME 而非 TIMESTAMP（无 2038 上限，不随会话时区跳动）
--      连接时必须带 serverTimezone=Asia/Shanghai，否则 CURRENT_TIMESTAMP 落库会偏 8 小时
--
--  表清单（按依赖顺序）：
--    users             用户（业主 / 访客 / 管理员）
--    spaces            车位（含 physical_status 与 business_status 双状态）
--    space_slots       业主发布的可预约时段
--    reservations      预约单
--    orders            订单（模拟支付）
--    space_status_log  车位状态变化日志（视觉进程写入）
--    conflict_records  预约冲突记录（自动核销的依据）
-- ============================================================================

CREATE DATABASE IF NOT EXISTS shared_parking
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_general_ci;

USE shared_parking;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS conflict_records;
DROP TABLE IF EXISTS space_status_log;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS reservations;
DROP TABLE IF EXISTS space_slots;
DROP TABLE IF EXISTS spaces;
DROP TABLE IF EXISTS users;

SET FOREIGN_KEY_CHECKS = 1;


-- ============================================================================
--  1. users —— 用户
-- ----------------------------------------------------------------------------
--  业主与访客共用一张表，用 role 区分。任务书范围不含人脸 / 车牌身份识别，
--  所以登录只走账号密码，见决策 D7。
-- ============================================================================
CREATE TABLE users (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username      VARCHAR(50)     NOT NULL                COMMENT '登录名',
    password_hash VARCHAR(100)    NOT NULL                COMMENT 'BCrypt 哈希，禁止存明文',
    real_name     VARCHAR(50)     NOT NULL                COMMENT '真实姓名',
    phone         VARCHAR(20)     NOT NULL                COMMENT '手机号，用于联系挪车',
    role          ENUM('owner','visitor','admin') NOT NULL DEFAULT 'visitor'
                                                          COMMENT 'owner=业主 visitor=访客 admin=管理员',
    enabled       TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '0=禁用',
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_username (username),
    UNIQUE KEY uk_users_phone (phone),
    KEY idx_users_role (role)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '用户表';


-- ============================================================================
--  2. spaces —— 车位
-- ----------------------------------------------------------------------------
--  【核心设计】双状态字段，不可合并，见决策 D2：
--
--    physical_status  视觉进程唯一写入口（free / occupied / unknown）
--                     回答"摄像头看到的是什么"
--    business_status  业务进程唯一写入口（available / reserved / in_use / ...）
--                     回答"按预约规则应该是什么"
--
--  两者不一致就是需要处理的冲突，例如：
--    physical=occupied + business=reserved  → 被别的车占了（occupied_by_other）
--    physical=free     + business=in_use    → 预约了没来（no_show）
--  这正是本系统自动核销逻辑的处理对象，也是论文的设计亮点。
-- ============================================================================
CREATE TABLE spaces (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code                VARCHAR(20)     NOT NULL           COMMENT '车位编号，如 A01（全局唯一）',
    owner_id            BIGINT UNSIGNED NOT NULL           COMMENT '归属业主，见决策 D6：车位属个人不属物业',
    zone_name           VARCHAR(50)     DEFAULT NULL       COMMENT '区域，如 A 区地下车库',
    location_desc       VARCHAR(200)    DEFAULT NULL       COMMENT '位置描述，帮访客找到车位',
    guide_price         DECIMAL(10,2)   NOT NULL DEFAULT 5.00
                                                           COMMENT '业主默认时租价（元/小时），发布时段时可覆盖',
    physical_status     ENUM('free','occupied','unknown') NOT NULL DEFAULT 'unknown'
                                                           COMMENT '【视觉进程写】当前物理占用状态',
    physical_coverage   DECIMAL(5,4)    DEFAULT NULL       COMMENT '最近一次最高的车位覆盖率，0~1，调试与论文用',
    physical_updated_at DATETIME        DEFAULT NULL       COMMENT '视觉状态最后更新时间，超时视为 unknown',
    business_status     ENUM('available','reserved','in_use','maintenance','disabled')
                                        NOT NULL DEFAULT 'available'
                                                           COMMENT '【业务进程写】按预约规则的状态',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_spaces_code (code),
    KEY idx_spaces_owner (owner_id),
    KEY idx_spaces_query (business_status, physical_status),
    CONSTRAINT fk_spaces_owner FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '车位表（双状态字段，见决策 D2）';


-- ============================================================================
--  3. space_slots —— 业主发布的可预约时段
-- ----------------------------------------------------------------------------
--  业主把私车位的闲置时段拿出来发布，访客只能在已发布时段内预约。
--  未发布的时段，车位即便物理空闲也不对外开放 —— 这是"共享"模式的立论基础。
--
--  关于时段重叠：唯一键只能拦住完全相同的 (space_id, start_time, end_time)，
--  部分重叠（如 8:00-12:00 与 10:00-14:00）必须由应用层在事务内校验，
--  见 docs 中的预约接口流程。不要试图用数据库唯一键解决重叠问题。
-- ============================================================================
CREATE TABLE space_slots (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    space_id       BIGINT UNSIGNED NOT NULL,
    start_time     DATETIME        NOT NULL                COMMENT '可预约开始时间',
    end_time       DATETIME        NOT NULL                COMMENT '可预约结束时间，必须晚于 start_time',
    price_per_hour DECIMAL(10,2)   NOT NULL                COMMENT '本时段时租价，优先于 spaces.guide_price',
    status         ENUM('open','booked','closed','expired') NOT NULL DEFAULT 'open'
                                                           COMMENT 'open=可约 booked=已约走 closed=业主撤回 expired=已过期',
    remark         VARCHAR(200)    DEFAULT NULL            COMMENT '业主备注，如"仅限小型车"',
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_slots_space_time (space_id, start_time, end_time),
    KEY idx_slots_status_time (status, start_time, end_time),
    KEY idx_slots_space (space_id, start_time),
    CONSTRAINT fk_slots_space FOREIGN KEY (space_id) REFERENCES spaces (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '业主发布的可预约时段';


-- ============================================================================
--  4. reservations —— 预约单
-- ----------------------------------------------------------------------------
--  状态机：
--      pending ──→ confirmed ──→ active ──→ completed
--         │            │           │
--         └────────────┴───────────┴──→ cancelled / violated
--
--  写入时机：访客抢位（pending）、支付成功（confirmed）、到点入场（active）、
--            正常出库（completed）、超时未到或车位被占（violated）
-- ============================================================================
CREATE TABLE reservations (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reservation_no VARCHAR(32)     NOT NULL                COMMENT '业务单号，如 R20261119093000001',
    slot_id        BIGINT UNSIGNED NOT NULL                COMMENT '占用的时段',
    space_id       BIGINT UNSIGNED NOT NULL                COMMENT '冗余车位 id，避免列表查询层层 join',
    visitor_id     BIGINT UNSIGNED NOT NULL                COMMENT '预约人',
    visitor_plate  VARCHAR(16)     DEFAULT NULL            COMMENT '访客手填车牌，仅作现场找位标识；系统不做车牌识别，见决策 D7',
    start_time     DATETIME        NOT NULL                COMMENT '预约进入时间',
    end_time       DATETIME        NOT NULL                COMMENT '预约离开时间',
    amount         DECIMAL(10,2)   NOT NULL DEFAULT 0.00   COMMENT '按预约时长预估价',
    status         ENUM('pending','confirmed','active','completed','cancelled','violated')
                                   NOT NULL DEFAULT 'pending',
    cancelled_at   DATETIME        DEFAULT NULL,
    cancel_reason  VARCHAR(200)    DEFAULT NULL,
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_reservations_no (reservation_no),
    KEY idx_res_slot (slot_id),
    KEY idx_res_visitor (visitor_id, status),
    KEY idx_res_space_time (space_id, start_time, end_time),
    KEY idx_res_status_time (status, start_time),
    CONSTRAINT fk_res_slot    FOREIGN KEY (slot_id)    REFERENCES space_slots (id),
    CONSTRAINT fk_res_space   FOREIGN KEY (space_id)   REFERENCES spaces (id),
    CONSTRAINT fk_res_visitor FOREIGN KEY (visitor_id) REFERENCES users (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '预约单';


-- ============================================================================
--  5. orders —— 订单（模拟支付）
-- ----------------------------------------------------------------------------
--  不接真实支付渠道，但状态机按真实流程设计，见决策 D4：
--      pending ──→ paid ──→ in_use ──→ completed
--         │          │
--         └──────────┴──→ cancelled / refunded / violated
--
--  一个预约单对应一个订单（1:1），订单号与预约单号分开，便于对账。
-- ============================================================================
CREATE TABLE orders (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_no       VARCHAR(32)     NOT NULL                COMMENT '订单号，如 O20261119093000001',
    reservation_id BIGINT UNSIGNED NOT NULL                COMMENT '关联预约单',
    payer_id       BIGINT UNSIGNED NOT NULL                COMMENT '付款人',
    amount         DECIMAL(10,2)   NOT NULL                COMMENT '实付金额（元）',
    status         ENUM('pending','paid','in_use','completed','cancelled','refunded','violated')
                                   NOT NULL DEFAULT 'pending',
    payment_method VARCHAR(20)     DEFAULT NULL            COMMENT '模拟支付固定填 mock',
    paid_at        DATETIME        DEFAULT NULL,
    completed_at   DATETIME        DEFAULT NULL,
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_orders_no (order_no),
    UNIQUE KEY uk_orders_reservation (reservation_id),
    KEY idx_orders_payer (payer_id, status),
    CONSTRAINT fk_orders_reservation FOREIGN KEY (reservation_id) REFERENCES reservations (id),
    CONSTRAINT fk_orders_payer       FOREIGN KEY (payer_id)       REFERENCES users (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '订单表（模拟支付，见决策 D4）';


-- ============================================================================
--  6. space_status_log —— 车位状态变化日志
-- ----------------------------------------------------------------------------
--  只记录【状态发生变化】的时刻，不是每帧都写。
--  视觉服务连续检测到 10 帧 occupied 也只写 1 条，避免日志表被刷爆。
--
--  这张表同时承担三个用途：
--    1. 自动核销的判定依据（预约时段内 physical 是否真的变成 occupied）
--    2. 论文的准确率统计（人工标注真值 vs 系统判定）
--    3. 故障排查（某车位状态来回跳，说明阈值或光照有问题）
-- ============================================================================
CREATE TABLE space_status_log (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    space_id        BIGINT UNSIGNED NOT NULL,
    physical_status ENUM('free','occupied','unknown') NOT NULL,
    coverage        DECIMAL(5,4)    DEFAULT NULL           COMMENT '触发本次变化时的覆盖率',
    source          ENUM('vision','manual','system') NOT NULL DEFAULT 'vision',
    snapshot_path   VARCHAR(255)    DEFAULT NULL           COMMENT '取证截图相对路径，如 snapshots/20261119_0930_A01.jpg',
    detected_at     DATETIME        NOT NULL               COMMENT '视觉端的检测时刻，非入库时刻',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_log_space_time (space_id, detected_at),
    KEY idx_log_detected (detected_at),
    CONSTRAINT fk_log_space FOREIGN KEY (space_id) REFERENCES spaces (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '车位状态变化日志（状态跳变才写）';


-- ============================================================================
--  7. conflict_records —— 预约冲突记录
-- ----------------------------------------------------------------------------
--  本系统的核心创新点：预约了车位却被别人占了，系统能自己发现。
--  判定逻辑（阶段 4 实现）：
--
--    occupied_by_other  预约时段内 physical=occupied，但入场记录不是预约人 → 车位被占
--    no_show            预约时段开始 N 分钟后 physical 仍为 free      → 预约人没来
--    overstay           预约结束时间已过，physical 仍为 occupied      → 超时未走
--    detected_free      预约进行中 physical 长时间 free               → 车辆提前离场
--
--  handled=0 的记录由定时任务扫，处理完置 1 并写 handle_note。
-- ============================================================================
CREATE TABLE conflict_records (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reservation_id BIGINT UNSIGNED NOT NULL,
    space_id       BIGINT UNSIGNED NOT NULL,
    conflict_type  ENUM('occupied_by_other','no_show','overstay','detected_free') NOT NULL,
    detail         VARCHAR(300)    DEFAULT NULL            COMMENT '冲突详情，如"预约 A01 09:00-11:00，09:05 检测到 occupied 但无入场记录"',
    snapshot_path  VARCHAR(255)    DEFAULT NULL            COMMENT '冲突时刻的取证截图',
    detected_at    DATETIME        NOT NULL,
    handled        TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '0=待处理 1=已处理',
    handle_note    VARCHAR(200)    DEFAULT NULL            COMMENT '处理结论，如"已退款并释放车位"',
    handled_at     DATETIME        DEFAULT NULL,
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conflict_res_type (reservation_id, conflict_type),
    KEY idx_conflict_pending (handled, detected_at),
    KEY idx_conflict_space (space_id),
    CONSTRAINT fk_conflict_res   FOREIGN KEY (reservation_id) REFERENCES reservations (id),
    CONSTRAINT fk_conflict_space FOREIGN KEY (space_id)       REFERENCES spaces (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '预约冲突记录（自动核销依据）';


-- ============================================================================
--  8. 时间区间合法性（替代 CHECK 约束）
-- ----------------------------------------------------------------------------
--  MySQL 5.7 不支持 CHECK，用触发器兜住最基础的一条：end_time 必须晚于 start_time。
--  时段重叠的校验逻辑较复杂（要跨行比较），放应用层事务里做，不在这里用触发器。
--
--  注意：触发器会让批量导入变慢，且报错信息不直观。如果你觉得调试麻烦，
--        可以注释掉这两段，只靠应用层校验 —— 但那样脏数据就能直接进库了。
-- ============================================================================
DROP TRIGGER IF EXISTS trg_slots_time_check_ins;
DROP TRIGGER IF EXISTS trg_slots_time_check_upd;
DROP TRIGGER IF EXISTS trg_res_time_check_ins;
DROP TRIGGER IF EXISTS trg_res_time_check_upd;

DELIMITER $$

CREATE TRIGGER trg_slots_time_check_ins BEFORE INSERT ON space_slots
FOR EACH ROW
BEGIN
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'space_slots: end_time 必须晚于 start_time';
    END IF;
END$$

CREATE TRIGGER trg_slots_time_check_upd BEFORE UPDATE ON space_slots
FOR EACH ROW
BEGIN
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'space_slots: end_time 必须晚于 start_time';
    END IF;
END$$

CREATE TRIGGER trg_res_time_check_ins BEFORE INSERT ON reservations
FOR EACH ROW
BEGIN
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reservations: end_time 必须晚于 start_time';
    END IF;
END$$

CREATE TRIGGER trg_res_time_check_upd BEFORE UPDATE ON reservations
FOR EACH ROW
BEGIN
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reservations: end_time 必须晚于 start_time';
    END IF;
END$$

DELIMITER ;


-- ============================================================================
--  9. 种子数据（开发自测用，上线前删掉本节）
-- ----------------------------------------------------------------------------
--  密码统一为 123456 的 BCrypt 哈希。生产环境必须改。
-- ============================================================================
INSERT INTO users (username, password_hash, real_name, phone, role) VALUES
('admin',   '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '系统管理员', '13900000000', 'admin'),
('owner01', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '张业主',     '13900000001', 'owner'),
('owner02', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '李业主',     '13900000002', 'owner'),
('visitor01', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '王访客',   '13900000003', 'visitor');

-- 三个车位对应合成测试图 demo_parking.jpg 里的 A01 / A02 / A03
INSERT INTO spaces (code, owner_id, zone_name, location_desc, guide_price, physical_status, business_status) VALUES
('A01', 2, 'A 区地下车库', '入口左手第一个', 5.00, 'unknown', 'available'),
('A02', 2, 'A 区地下车库', 'A01 右侧相邻',   5.00, 'unknown', 'available'),
('A03', 3, 'A 区地下车库', 'A02 右侧相邻',   6.00, 'unknown', 'available');

-- 一条未来时段，便于联调预约接口时直接有数据
INSERT INTO space_slots (space_id, start_time, end_time, price_per_hour, status, remark) VALUES
(1, DATE_ADD(NOW(), INTERVAL 1 HOUR), DATE_ADD(NOW(), INTERVAL 4 HOUR), 5.00, 'open', '仅限小型车'),
(2, DATE_ADD(NOW(), INTERVAL 1 HOUR), DATE_ADD(NOW(), INTERVAL 4 HOUR), 5.00, 'open', NULL),
(3, DATE_ADD(NOW(), INTERVAL 2 HOUR), DATE_ADD(NOW(), INTERVAL 6 HOUR), 6.00, 'open', '车位较窄，SUV 慎停');


-- ============================================================================
--  10. 建库后自检
-- ----------------------------------------------------------------------------
--  执行完可以跑这几条确认没建错：
--
--    SHOW TABLES;
--    SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES
--      WHERE TABLE_SCHEMA = 'shared_parking';
--
--    -- 双状态字段是否都在
--    DESC spaces;
--
--    -- 触发器是否生效（这条应该报错：end_time 早于 start_time）
--    INSERT INTO space_slots (space_id, start_time, end_time, price_per_hour)
--      VALUES (1, '2026-11-19 10:00:00', '2026-11-19 09:00:00', 5.00);
-- ============================================================================
