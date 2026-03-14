"""
DashScope Context Cache 管理器

将固定的 system prompt 预缓存到 DashScope，后续请求引用 cache_id，
cached token 费率约为正常输入 token 的 10%。

工作流程：
  1. 启动时调用 DashScope /api/v1/context/caches 创建缓存
  2. 每次 LLM 调用时：
     - 如果 system prompt 未变化 → 去掉 system message，extra_body 加 cache_id
     - 如果 system prompt 变化（含动态记忆）→ 降级，完整发送
  3. 缓存过期前 5 分钟自动重建
"""

import time
import threading
import logging
import urllib.request
import urllib.error
import json

logger = logging.getLogger(__name__)

# DashScope 原生 API（非 OpenAI 兼容模式）
_CACHE_CREATE_URL = "https://dashscope.aliyuncs.com/api/v1/context/caches"


class ContextCache:
    """管理单个 system prompt 对应的 DashScope Context Cache"""

    def __init__(self, api_key: str, model: str, system_prompt: str):
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._cache_id: str | None = None
        self._expire_time: float = 0.0
        self._lock = threading.Lock()
        self._enabled = False  # 只有成功创建后才为 True

        self._try_create()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def apply(self, messages: list[dict]) -> tuple[list[dict], dict]:
        """
        尝试对 messages 应用缓存。

        如果 messages[0] 是 system role 且内容与缓存一致：
          - 返回去掉 system 消息后的列表 + {"cache_id": "xxx"}
        否则降级，原样返回 + 空 extra。

        用法：
            messages, cache_extra = context_cache.apply(messages)
            client.chat.completions.create(
                ...,
                messages=messages,
                extra_body={"enable_thinking": False, **cache_extra},
            )
        """
        if not self._enabled:
            return messages, {}

        if not messages or messages[0].get("role") != "system":
            return messages, {}

        if messages[0].get("content") != self._system_prompt:
            # system prompt 含动态记忆，降级
            return messages, {}

        with self._lock:
            if self._is_expired():
                logger.info("[Cache] 缓存即将过期，重建中...")
                self._try_create()
            if not self._enabled:
                return messages, {}
            cache_id = self._cache_id

        return messages[1:], {"cache_id": cache_id}

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _is_expired(self) -> bool:
        return time.time() > self._expire_time - 300  # 提前 5 分钟重建

    def _try_create(self):
        """调用 DashScope 创建 Context Cache，失败时静默降级"""
        body = json.dumps({
            "model": self._model,
            "input": {
                "messages": [
                    {"role": "system", "content": self._system_prompt}
                ]
            },
            "parameters": {}
        }).encode("utf-8")

        req = urllib.request.Request(
            _CACHE_CREATE_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            output = data.get("output", {})
            cache_id = output.get("cache_id")
            expire_time = output.get("expired_time", 0)

            if cache_id:
                self._cache_id = cache_id
                self._expire_time = float(expire_time)
                self._enabled = True
                logger.info(
                    f"[Cache] ✅ Context cache 创建成功 "
                    f"cache_id={cache_id}, "
                    f"model={self._model}, "
                    f"system_prompt_len={len(self._system_prompt)} 字符"
                )
            else:
                self._enabled = False
                logger.warning(f"[Cache] ⚠️ 创建响应缺少 cache_id: {data}")

        except urllib.error.HTTPError as e:
            body_msg = e.read().decode("utf-8", errors="replace")
            self._enabled = False
            logger.warning(
                f"[Cache] ⚠️ HTTP {e.code} 创建失败，降级为无缓存模式: {body_msg[:200]}"
            )
        except Exception as e:
            self._enabled = False
            logger.warning(f"[Cache] ⚠️ 创建失败，降级为无缓存模式: {e}")
