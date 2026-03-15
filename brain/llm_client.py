from openai import OpenAI
import logging
import re
import json
from json_repair import repair_json
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self.large_client = OpenAI(
            api_key=settings.LARGE_LLM.api_key,
            base_url=settings.LARGE_LLM.base_url,
        )
        self.small_client = OpenAI(
            api_key=settings.SMALL_LLM.api_key,
            base_url=settings.SMALL_LLM.base_url,
        )
        self.embedding_client = OpenAI(
            api_key=settings.EMBEDDING_MODEL.api_key,
            base_url=settings.EMBEDDING_MODEL.base_url,
        )

    def _extract_json(self, content):
        good_json_string = repair_json(content)
        data = json.loads(good_json_string)
        return data

    def _log_usage(self, usage, model_name: str):
        """记录 Token 消耗日志，兼容 OpenAI 和 Gemini 两种响应格式"""
        if usage is None:
            logger.debug("[LLM Usage] usage 为空")
            return

        # 调试日志：输出 usage 对象的所有属性
        usage_attrs = vars(usage) if hasattr(usage, '__dict__') else str(usage)
        logger.debug(f"[LLM Usage Debug] usage 对象: {usage_attrs}")

        # OpenAI 风格: prompt_tokens / completion_tokens
        p = getattr(usage, "prompt_tokens", None)
        c = getattr(usage, "completion_tokens", None)

        # Gemini 风格: prompt_token_count / candidates_token_count
        if p is None:
            p = getattr(usage, "prompt_token_count", None)
        if c is None:
            c = getattr(usage, "candidates_token_count", None)

        try:
            p = int(p) if p is not None else 0
            c = int(c) if c is not None else 0
        except (TypeError, ValueError):
            p, c = 0, 0

        logger.info(
            f"[LLM Usage] Model: {model_name} | Prompt: {p} | Completion: {c} | Total: {p + c}"
        )

        # 顺带记录缓存命中情况（如有）
        token_details = getattr(usage, "prompt_tokens_details", None)
        if token_details:
            logger.debug(f"[LLM Usage Debug] prompt_tokens_details: {token_details}")
            cached_tokens = getattr(token_details, "cached_tokens", 0)
            try:
                cached_tokens = int(cached_tokens)
            except (TypeError, ValueError):
                cached_tokens = 0
            if cached_tokens > 0:
                logger.info(f"[Cache] ✅ 缓存命中 {cached_tokens} token")
        else:
            logger.debug("[LLM Usage Debug] prompt_tokens_details 为空或不存在")

    def _apply_explicit_cache(self, messages: list[dict]) -> list[dict]:
        """
        对 system message 应用显式缓存。

        将 system message 改为 array 格式并添加 cache_control 参数，
        启用 DashScope 的显式缓存机制（5分钟 TTL）。

        使用场景：
          - SYSTEM_PROMPT 是固定不变的 → 每次请求可享受缓存加速
          - 返回结果会包含 usage.prompt_tokens_details.cached_tokens
          - cached token 费率约为正常输入 token 的 10%
        """
        if not messages or messages[0].get("role") != "system":
            return messages

        # 保留原始消息列表，只修改 system message
        messages = list(messages)  # 浅拷贝
        system_msg = dict(messages[0])  # 深拷贝 system message

        # 将 content 转为 array 格式（必须），并添加 cache_control
        system_msg["content"] = [{"type": "text", "text": system_msg["content"]}]
        system_msg["cache_control"] = {"type": "ephemeral"}

        messages[0] = system_msg
        logger.debug(
            f"[Cache] 已对 system message 应用显式缓存 "
            f"(prompt_len={len(system_msg['content'][0]['text'])} 字符)"
        )
        return messages

    def one_chat(self, model_config, messages, timeout=30):
        """单次对话，带超时和重试"""
        client = (
            self.large_client
            if model_config == settings.LARGE_LLM
            else self.small_client
        )

        # 应用显式缓存
        messages = self._apply_explicit_cache(messages)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=model_config.name,
                    messages=messages,
                    extra_body={"enable_thinking": False},
                    stream=False,
                    temperature=0.7,
                    timeout=timeout,
                )
                full_response = response.choices[0].message.content

                # 记录 Token 消耗（兼容 OpenAI / Gemini 格式）
                usage = getattr(response, "usage", None) or getattr(response, "usage_metadata", None)
                self._log_usage(usage, model_config.name)

                return full_response
            except Exception as e:
                logger.error(f"OneChat Error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return None
        return None

    def stream_chat(self, model_config, messages):
        client = (
            self.large_client
            if model_config == settings.LARGE_LLM
            else self.small_client
        )

        # 应用显式缓存
        messages = self._apply_explicit_cache(messages)

        try:
            response = client.chat.completions.create(
                model=model_config.name,
                messages=messages,
                extra_body={"enable_thinking": False},
                stream=True,
                temperature=0.7,
            )

            last_usage = None
            for chunk in response:
                # 从最后一个含 usage 的 chunk 记录（OpenAI stream_options 方式）
                if getattr(chunk, "usage", None):
                    last_usage = chunk.usage

                reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
                if reasoning:
                    yield f"{reasoning}"

                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content

            # 在流结束后记录 Token 消耗
            # 优先级：chunk.usage > response.usage（DashScope）> response.usage_metadata（Gemini）
            usage = last_usage or getattr(response, "usage", None) or getattr(response, "usage_metadata", None)
            self._log_usage(usage, model_config.name)

        except Exception as e:
            yield f"[Error]: {str(e)}"
            logger.error(f"Streaming Chat Error: {e}")

    def get_embedding(self, model_config, text: str):
        client = self.embedding_client
        try:
            response = client.embeddings.create(
                model=model_config.name,
                input=text,
                dimensions=1536,
            )
            embedding = response.data[0].embedding
            return embedding
        except Exception as e:
            logger.error(f"Get Embedding Error: {e}")
            return None
