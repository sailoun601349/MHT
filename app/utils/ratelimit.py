# -*- coding: utf-8 -*-
"""内存限流：滑动窗口 + 登录失败锁定（重启清零，个人项目够用）"""
import threading
import time


class SlidingWindowLimiter:
    """滑动窗口限流：每个 key 在窗口内最多 limit 次。"""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._records = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            ts = self._records.setdefault(key, [])
            while ts and ts[0] <= now - self.window:
                ts.pop(0)
            if len(ts) >= self.limit:
                return False
            ts.append(now)
            return True


class LoginThrottle:
    """登录保护：连续失败 max_fails 次，锁定 lock_minutes 分钟。"""

    def __init__(self, max_fails: int = 5, lock_minutes: int = 10):
        self.max_fails = max_fails
        self.lock_seconds = lock_minutes * 60
        self._state = {}
        self._lock = threading.Lock()

    def _get(self, ip: str):
        now = time.time()
        st = self._state.get(ip, {"fails": 0, "until": 0})
        if st["until"] <= now:
            st = {"fails": 0, "until": 0}
        return st

    def is_locked(self, ip: str) -> bool:
        with self._lock:
            return self._get(ip)["until"] > time.time()

    def record_fail(self, ip: str) -> None:
        with self._lock:
            st = self._get(ip)
            st["fails"] += 1
            if st["fails"] >= self.max_fails:
                st["until"] = time.time() + self.lock_seconds
            self._state[ip] = st

    def reset(self, ip: str) -> None:
        with self._lock:
            self._state.pop(ip, None)
