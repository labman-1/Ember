from openai import OpenAI
import logging
import re
import json
from json_repair import repair_json
from config.settings import settings
from brain.context_cache import ContextCache

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

        # 可选：DashScope Context Cache，将固定 system prompt 缓存以节省 token
        self._cache: ContextCache | None = None
        if settings.ENABLE_CONTEXT_CACHE:
            self._cache = ContextCache(
                api_key=settings.LARGE_LLM.api_key,
                model=settings.LARGE_LLM.name,
                system_prompt=settings.SYSTEM_PROMPT,
            )
            if not self._cache.enabled:
                logger.warning("[Cache] Context cache 初始化失败，已降级为无缓存模式")

    def _extract_json(self, content):
        good_json_string = repair_json(content)
        data = json.loads(good_json_string)
        return data

    def one_chat(self, model_config, messages, timeout=30):
        """单次对话，带超时和重试"""
        client = (
            self.large_client
            if model_config == settings.LARGE_LLM
            else self.small_client
        )

        messages, cache_extra = (
            self._cache.apply(messages) if self._cache else (messages, {})
        )

        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=model_config.name,
                    messages=messages,
                    extra_body={"enable_thinking": False, **cache_extra},
                    stream=False,
                    temperature=0.7,
                    timeout=timeout,
                )
                full_response = response.choices[0].message.content
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

        messages, cache_extra = (
            self._cache.apply(messages) if self._cache else (messages, {})
        )

        try:
            response = client.chat.completions.create(
                model=model_config.name,
                messages=messages,
                extra_body={"enable_thinking": False, **cache_extra},
                stream=True,
                temperature=0.7,
            )

            for chunk in response:
                reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
                if reasoning:
                    yield f"{reasoning}"

                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content

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
