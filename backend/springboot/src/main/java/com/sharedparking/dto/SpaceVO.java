package com.sharedparking.dto;

import com.sharedparking.entity.Space;
import lombok.Data;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 车位视图对象，给前端用的展示结构。
 *
 * 为什么不让前端直接拿实体：实体里全是英文枚举值（free / occupied / available），
 * 前端要做一堆 if-else 才能显示中文，而且每个页面都得重复一遍。
 * 把翻译逻辑收在后端一处，前端拿到 statusText 直接渲染。
 */
@Data
public class SpaceVO {

    /** 视觉数据超过这个秒数没更新，就认为失效 */
    private static final long STALE_SECONDS = 60;

    private Long id;
    private String code;
    private String zoneName;
    private String locationDesc;
    private BigDecimal guidePrice;

    /** 物理占用状态原值：free / occupied / unknown */
    private String physicalStatus;

    /** 最近一次覆盖率，0~1 */
    private BigDecimal physicalCoverage;

    private LocalDateTime physicalUpdatedAt;

    /** 视觉数据是否已过期。true 表示 Python 进程可能挂了，不要信这个状态 */
    private Boolean physicalStale;

    /** 业务状态原值：available / reserved / in_use / maintenance / disabled */
    private String businessStatus;

    /**
     * 综合状态中文描述，前端直接显示这个字段。
     * 判定优先级：业务维护状态 > 预约/使用中 > 物理占用 > 空闲
     */
    private String displayStatus;

    public static SpaceVO from(Space space) {
        SpaceVO vo = new SpaceVO();
        vo.setId(space.getId());
        vo.setCode(space.getCode());
        vo.setZoneName(space.getZoneName());
        vo.setLocationDesc(space.getLocationDesc());
        vo.setGuidePrice(space.getGuidePrice());
        vo.setPhysicalStatus(space.getPhysicalStatus());
        vo.setPhysicalCoverage(space.getPhysicalCoverage());
        vo.setPhysicalUpdatedAt(space.getPhysicalUpdatedAt());
        vo.setBusinessStatus(space.getBusinessStatus());

        boolean stale = isStale(space.getPhysicalUpdatedAt());
        vo.setPhysicalStale(stale);
        vo.setDisplayStatus(resolveDisplayStatus(space.getPhysicalStatus(), space.getBusinessStatus(), stale));
        return vo;
    }

    /** 视觉状态是否过期。没被视觉进程写过（null）也算过期 */
    private static boolean isStale(LocalDateTime updatedAt) {
        if (updatedAt == null) {
            return true;
        }
        return Duration.between(updatedAt, LocalDateTime.now()).getSeconds() > STALE_SECONDS;
    }

    /**
     * 综合状态判定。顺序不能调换：
     * 车位在维修，哪怕摄像头看到空着也不能约，所以 maintenance 优先级最高。
     */
    private static String resolveDisplayStatus(String physical, String business, boolean stale) {
        if ("maintenance".equals(business)) {
            return "维护中";
        }
        if ("disabled".equals(business)) {
            return "已停用";
        }
        if ("in_use".equals(business)) {
            return "使用中";
        }
        if ("reserved".equals(business)) {
            return "已预约";
        }
        if (stale) {
            return "状态未知";
        }
        if ("occupied".equals(physical)) {
            return "已占用";
        }
        if ("free".equals(physical)) {
            return "空闲可约";
        }
        return "状态未知";
    }
}
