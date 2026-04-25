import time

from aria.core.runtime import CLOUD_REQUEST_MIN_INTERVAL, CLOUD_REQUESTS_PER_MINUTE

class LLMChatRateLimitMixin:
    def _enforce_cloud_rate_limit(self, skip_min_interval: bool = False) -> None:
        if self.backend != "cloud":
            return
        while True:
            wait_for = 0.0
            now = time.monotonic()
            with self._cloud_request_lock:
                while self._cloud_request_times and now - self._cloud_request_times[0] >= 60.0:
                    self._cloud_request_times.popleft()
                if self._cloud_request_times and not skip_min_interval:
                    since_last = now - self._cloud_request_times[-1]
                    if since_last < CLOUD_REQUEST_MIN_INTERVAL:
                        wait_for = max(wait_for, CLOUD_REQUEST_MIN_INTERVAL - since_last)
                if len(self._cloud_request_times) >= CLOUD_REQUESTS_PER_MINUTE:
                    oldest_age = now - self._cloud_request_times[0]
                    wait_for = max(wait_for, 60.0 - oldest_age + 0.05)
                if wait_for <= 0:
                    self._cloud_request_times.append(now)
                    return
            if self._abort_event.is_set():
                return
            time.sleep(min(wait_for, 0.25) if wait_for > 0.25 else wait_for)

