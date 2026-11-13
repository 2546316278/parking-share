# -*- coding: utf-8 -*-
"""
车位状态时序平滑。

为什么需要它：
单帧检测会因为光照、遮挡、车辆进出过程中的中间状态而抖动，
导致车位状态在 free / occupied 之间反复跳变，业务层无法使用。

做法：对每个车位维护一个定长滑动窗口，窗口内多数投票决定当前状态，
并设置最小确认票数，避免刚出现 2 帧占用就把状态改掉。
"""
from collections import deque
from typing import Dict, Optional

from config import (
    SMOOTH_WINDOW,
    SMOOTH_MIN_VOTES,
    STATUS_UNKNOWN,
    STATUS_OCCUPIED,
    STATUS_FREE,
)


class StatusSmoother(object):
    """按车位编号维护独立的滑动窗口。"""

    def __init__(self, window: int = SMOOTH_WINDOW, min_votes: int = SMOOTH_MIN_VOTES):
        self.window = window
        self.min_votes = min_votes
        # space_number -> deque[str]
        self._buffers: Dict[str, deque] = {}
        # space_number -> 已经确认过的状态
        self._confirmed: Dict[str, str] = {}

    def update(self, space_number: str, raw_status: str) -> str:
        """喂入一帧的原始判定结果，返回平滑后的状态。"""
        buf = self._buffers.get(space_number)
        if buf is None:
            buf = deque(maxlen=self.window)
            self._buffers[space_number] = buf
        buf.append(raw_status)

        # 窗口还没填满时，直接采用最新一帧，保证首帧就能出结果
        if len(buf) < self.window:
            self._confirmed[space_number] = raw_status
            return raw_status

        # 统计窗口内各状态出现次数
        votes = {STATUS_FREE: 0, STATUS_OCCUPIED: 0, STATUS_UNKNOWN: 0}
        for s in buf:
            if s in votes:
                votes[s] += 1

        best_status: Optional[str] = None
        best_count = -1
        for status, count in votes.items():
            if count > best_count:
                best_status, best_count = status, count

        # 票数达到阈值才认为状态可信，否则沿用上一次确认的状态
        if best_status is not None and best_count >= self.min_votes:
            self._confirmed[space_number] = best_status
            return best_status

        return self._confirmed.get(space_number, STATUS_UNKNOWN)

    def reset(self):
        self._buffers.clear()
        self._confirmed.clear()
