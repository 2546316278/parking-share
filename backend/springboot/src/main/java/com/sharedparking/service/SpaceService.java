package com.sharedparking.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.sharedparking.dto.SpaceVO;
import com.sharedparking.entity.Space;
import com.sharedparking.mapper.SpaceMapper;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 车位业务逻辑。
 *
 * 目前只有查询，所以逻辑很薄。放在 service 层而不是直接写 controller，
 * 是因为后面「可预约车位筛选」「业主车位管理」都要复用这里的查询，
 * 而且冲突判定（阶段 4）也会依赖它。
 */
@Service
public class SpaceService {

    private final SpaceMapper spaceMapper;

    public SpaceService(SpaceMapper spaceMapper) {
        this.spaceMapper = spaceMapper;
    }

    /** 全部车位，按编号排序。A01 / A02 / A03 自然顺序 */
    public List<SpaceVO> listAll() {
        List<Space> spaces = spaceMapper.selectList(
                new LambdaQueryWrapper<Space>().orderByAsc(Space::getCode)
        );
        return spaces.stream().map(SpaceVO::from).toList();
    }

    /**
     * 当前真正可预约的车位。
     *
     * 三个条件缺一不可：
     *   1. business_status = available  业主没在维修、没被别人约走
     *   2. physical_status = free       摄像头确认空着
     *   3. physical_updated_at 是新鲜的 视觉进程还活着
     *
     * 第 3 条最容易被忽略：如果 Python 进程挂了，physical_status 会一直停留在
     * 最后一次的 free，此时把车位放出去预约，访客到了会发现被占。
     * 所以必须查时间戳，不能只查状态值。
     */
    public List<SpaceVO> listAvailable() {
        List<Space> spaces = spaceMapper.selectList(
                new LambdaQueryWrapper<Space>()
                        .eq(Space::getBusinessStatus, "available")
                        .eq(Space::getPhysicalStatus, "free")
                        .ge(Space::getPhysicalUpdatedAt, LocalDateTime.now().minusSeconds(60))
                        .orderByAsc(Space::getCode)
        );
        return spaces.stream().map(SpaceVO::from).toList();
    }

    /** 按编号查单个车位，找不到返回 null */
    public SpaceVO findByCode(String code) {
        Space space = spaceMapper.selectOne(
                new LambdaQueryWrapper<Space>().eq(Space::getCode, code)
        );
        return space == null ? null : SpaceVO.from(space);
    }
}
