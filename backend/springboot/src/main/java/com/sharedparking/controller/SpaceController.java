package com.sharedparking.controller;

import com.sharedparking.common.Result;
import com.sharedparking.dto.SpaceVO;
import com.sharedparking.service.SpaceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 车位查询接口。
 *
 * 全部是 GET，只读，不涉及写库 —— 写车位状态是 Python 视觉进程的职责（决策 D2）。
 *
 *   GET /api/spaces                     全部车位
 *   GET /api/spaces?onlyAvailable=true  只返回当前真正可约的
 *   GET /api/spaces/A01                 按编号查单个
 */
@RestController
@RequestMapping("/api/spaces")
public class SpaceController {

    private final SpaceService spaceService;

    public SpaceController(SpaceService spaceService) {
        this.spaceService = spaceService;
    }

    @GetMapping
    public Result<List<SpaceVO>> list(
            @RequestParam(defaultValue = "false") boolean onlyAvailable) {
        List<SpaceVO> spaces = onlyAvailable
                ? spaceService.listAvailable()
                : spaceService.listAll();
        return Result.ok(spaces);
    }

    @GetMapping("/{code}")
    public Result<SpaceVO> detail(@PathVariable String code) {
        SpaceVO space = spaceService.findByCode(code);
        if (space == null) {
            return Result.fail(1002, "车位不存在: " + code);
        }
        return Result.ok(space);
    }
}
