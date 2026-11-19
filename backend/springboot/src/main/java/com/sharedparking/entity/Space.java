package com.sharedparking.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 车位实体，对应 spaces 表。
 *
 * 【重点】两类状态字段不能混用，见 docs/TECH_STACK.md 决策 D2：
 *   physical* 系列字段只有 Python 视觉进程能写，业务侧只读
 *   business* 系列字段只有业务进程能写，视觉侧不碰
 *
 * 不要为了方便在业务代码里改 physicalStatus —— 一旦两边都写，
 * 「预约了却被占」这个冲突就永远检测不出来了，整个系统的设计立不住。
 */
@Data
@TableName("spaces")
public class Space {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 车位编号，如 A01，全局唯一 */
    private String code;

    /** 归属业主，见决策 D6：车位属个人不属物业 */
    private Long ownerId;

    /** 区域，如 "A 区地下车库" */
    private String zoneName;

    /** 位置描述，帮访客找到车位 */
    private String locationDesc;

    /** 默认时租价（元/小时），发布时段时可用时段自己的价格覆盖 */
    private BigDecimal guidePrice;

    // ==================== 视觉进程写入，业务侧只读 ====================

    /** free / occupied / unknown。ENUM 存库，Java 侧用 String 接收最省事 */
    private String physicalStatus;

    /** 最近一次车位覆盖率 0~1，调试与论文统计用 */
    private BigDecimal physicalCoverage;

    /** 视觉状态最后更新时间。超过 60 秒没更新就应当作 unknown，防止用陈旧数据做判定 */
    private LocalDateTime physicalUpdatedAt;

    // ==================== 业务进程写入 ====================

    /** available / reserved / in_use / maintenance / disabled */
    private String businessStatus;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
