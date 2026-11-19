package com.sharedparking.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.sharedparking.entity.Space;
import org.apache.ibatis.annotations.Mapper;

/**
 * 车位数据访问。
 *
 * 继承 BaseMapper 后单表增删改查全部自带，不用写 XML：
 *   selectList(null)                 查全部
 *   selectById(1L)                   主键查
 *   selectOne(new LambdaQueryWrapper<Space>().eq(Space::getCode, "A01"))
 *   insert / updateById / deleteById
 *
 * 只有多表关联统计（如「某业主名下所有车位的订单总额」）才需要手写 SQL，
 * 到时候在本接口里加 @Select 注解或另建 XML。
 */
@Mapper
public interface SpaceMapper extends BaseMapper<Space> {
}
