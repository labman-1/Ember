"""
LLM Client Package
支持大/小模型的流式/非流式调用，以及 API/本地 Embedding
"""

import os
import asyncio
import logging
from typing import Optional, AsyncIterator, Union
from pathlib import Path

from openai import AsyncOpenAI

from ember_v2.core.package_base import BasePackage
from ember_v2.core.types import ModelConfig, PackageResponse, TokenUsage
from .types import (
    ModelSize,
    EmbeddingMode,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingResponse,
)

logger = logging.getLogger(__name__)


class LLMClient(BasePackage):
    """
    LLM 客户端 Package

    功能:
    - 大模型调用（流式/非流式）
    - 小模型调用（流式/非流式）
    - Embedding 生成（API/本地）

    配置优先级:
    1. 环境变量
    2. config.yaml 中的值
    """

    # 本地 Embedding 模型单例
    _local_embedding_model = None

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(config_path)

        # 从配置或环境变量初始化模型配置
        self._small_config = self._init_model_config("small")
        self._large_config = self._init_model_config("large")
        self._embedding_config = self._init_model_config("embedding")

        # 初始化 OpenAI 客户端
        self._small_client: Optional[AsyncOpenAI] = None
        self._large_client: Optional[AsyncOpenAI] = None
        self._embedding_client: Optional[AsyncOpenAI] = None

        self._logger.info(
            f"LLMClient initialized with large={self._large_config.name}, "
            f"small={self._small_config.name}"
        )

    def _init_model_config(self, model_type: str) -> ModelConfig:
        """
        初始化模型配置，优先从环境变量读取

        Args:
            model_type: 模型类型 (small, large, embedding)
        """
        env_prefix = model_type.upper()

        # 环境变量优先
        name = os.getenv(
            (
                f"{env_prefix}_LLM_MODEL"
                if model_type != "embedding"
                else f"{env_prefix}_MODEL"
            ),
            "",
        )
        api_key = os.getenv(
            (
                f"{env_prefix}_LLM_API_KEY"
                if model_type != "embedding"
                else f"{env_prefix}_API_KEY"
            ),
            "",
        )
        base_url = os.getenv(
            (
                f"{env_prefix}_LLM_BASE_URL"
                if model_type != "embedding"
                else f"{env_prefix}_BASE_URL"
            ),
            "",
        )

        # 如果环境变量为空，尝试从配置文件读取
        if not name:
            name = self.get_config_value(f"models.{model_type}.name", "")
        if not api_key:
            api_key = self.get_config_value(f"models.{model_type}.api_key", "")
        if not base_url:
            base_url = self.get_config_value(f"models.{model_type}.base_url", "")

        # 读取其他配置
        timeout = self.get_config_value(f"models.{model_type}.timeout", 30)
        max_retries = self.get_config_value(f"models.{model_type}.max_retries", 3)
        temperature = self.get_config_value(f"models.{model_type}.temperature", 0.7)

        # 本地模型配置（仅 embedding）
        local_enabled = self.get_config_value(
            f"models.{model_type}.local.enabled", False
        )
        local_model_name = self.get_config_value(
            f"models.{model_type}.local.model_name", "BAAI/bge-m3"
        )

        return ModelConfig(
            name=name,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            temperature=temperature,
            local_enabled=local_enabled,
            local_model_name=local_model_name,
        )

    def _get_client(self, model_size: ModelSize) -> AsyncOpenAI:
        """获取或创建对应大小的客户端"""
        if model_size == ModelSize.LARGE:
            if self._large_client is None:
                self._large_client = AsyncOpenAI(
                    api_key=self._large_config.api_key,
                    base_url=self._large_config.base_url,
                )
            return self._large_client
        else:
            if self._small_client is None:
                self._small_client = AsyncOpenAI(
                    api_key=self._small_config.api_key,
                    base_url=self._small_config.base_url,
                )
            return self._small_client

    def _get_embedding_client(self) -> AsyncOpenAI:
        """获取 Embedding 客户端"""
        if self._embedding_client is None:
            self._embedding_client = AsyncOpenAI(
                api_key=self._embedding_config.api_key,
                base_url=self._embedding_config.base_url,
            )
        return self._embedding_client

    # ==================== 聊天接口 ====================

    async def chat(
        self,
        messages: list[dict],
        model_size: ModelSize = ModelSize.LARGE,
        stream: bool = False,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        extra_body: Optional[dict] = None,
    ) -> PackageResponse[Union[ChatResponse, AsyncIterator[StreamChunk]]]:
        """
        统一的聊天接口

        Args:
            messages: 消息列表
            model_size: 模型大小
            stream: 是否流式输出
            temperature: 温度参数
            timeout: 超时时间
            extra_body: 额外请求体参数

        Returns:
            PackageResponse 包含 ChatResponse 或 AsyncIterator[StreamChunk]
        """
        config = (
            self._large_config if model_size == ModelSize.LARGE else self._small_config
        )
        client = self._get_client(model_size)

        temp = temperature if temperature is not None else config.temperature
        tout = timeout if timeout is not None else config.timeout
        extra = extra_body or {}

        # 默认关闭推理模式（针对某些模型）
        if "enable_thinking" not in extra:
            extra["enable_thinking"] = False

        try:
            if stream:
                return PackageResponse(
                    success=True,
                    data=self._stream_chat(client, config, messages, temp, extra),
                    metadata={"model": config.name, "stream": True},
                )
            else:
                response = await self._sync_chat(
                    client, config, messages, temp, tout, extra
                )
                return PackageResponse(
                    success=True,
                    data=response,
                    metadata={"model": config.name, "usage": response.usage},
                )
        except Exception as e:
            self._logger.error(f"Chat error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def _sync_chat(
        self,
        client: AsyncOpenAI,
        config: ModelConfig,
        messages: list[dict],
        temperature: float,
        timeout: int,
        extra_body: dict,
    ) -> ChatResponse:
        """非流式聊天"""
        for attempt in range(config.max_retries):
            try:
                response = await client.chat.completions.create(
                    model=config.name,
                    messages=messages,
                    temperature=temperature,
                    timeout=timeout,
                    extra_body=extra_body,
                    stream=False,
                )

                usage = None
                if response.usage:
                    usage = TokenUsage(
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                    )

                return ChatResponse(
                    content=response.choices[0].message.content or "",
                    usage=usage,
                    model=response.model,
                    finish_reason=response.choices[0].finish_reason or "",
                )
            except Exception as e:
                self._logger.error(
                    f"Sync chat attempt {attempt + 1}/{config.max_retries} failed: {e}"
                )
                if attempt == config.max_retries - 1:
                    raise

        raise RuntimeError("Max retries exceeded")

    async def _stream_chat(
        self,
        client: AsyncOpenAI,
        config: ModelConfig,
        messages: list[dict],
        temperature: float,
        extra_body: dict,
    ) -> AsyncIterator[StreamChunk]:
        """流式聊天生成器"""
        try:
            stream = await client.chat.completions.create(
                model=config.name,
                messages=messages,
                temperature=temperature,
                extra_body=extra_body,
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta

                # 处理推理内容（如果模型支持）
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield StreamChunk(content="", reasoning=reasoning)

                # 处理正常内容
                content = delta.content
                if content:
                    yield StreamChunk(content=content)

                # 处理结束
                if chunk.choices[0].finish_reason:
                    yield StreamChunk(
                        content="",
                        is_finished=True,
                        finish_reason=chunk.choices[0].finish_reason,
                    )
        except Exception as e:
            self._logger.error(f"Stream chat error: {e}")
            yield StreamChunk(content=f"[Error]: {str(e)}", is_finished=True)

    # ==================== 便捷方法 ====================

    async def chat_sync(
        self, messages: list[dict], model_size: ModelSize = ModelSize.LARGE, **kwargs
    ) -> PackageResponse[ChatResponse]:
        """非流式聊天的便捷方法"""
        result = await self.chat(messages, model_size, stream=False, **kwargs)
        return result  # type: ignore

    async def chat_stream(
        self, messages: list[dict], model_size: ModelSize = ModelSize.LARGE, **kwargs
    ) -> PackageResponse[AsyncIterator[StreamChunk]]:
        """流式聊天的便捷方法"""
        result = await self.chat(messages, model_size, stream=True, **kwargs)
        return result  # type: ignore

    async def small_chat(
        self, messages: list[dict], stream: bool = False, **kwargs
    ) -> PackageResponse[Union[ChatResponse, AsyncIterator[StreamChunk]]]:
        """小模型聊天的便捷方法"""
        return await self.chat(messages, ModelSize.SMALL, stream=stream, **kwargs)

    async def large_chat(
        self, messages: list[dict], stream: bool = False, **kwargs
    ) -> PackageResponse[Union[ChatResponse, AsyncIterator[StreamChunk]]]:
        """大模型聊天的便捷方法"""
        return await self.chat(messages, ModelSize.LARGE, stream=stream, **kwargs)

    # ==================== Embedding 接口 ====================

    async def embed(
        self,
        texts: list[str],
        mode: EmbeddingMode = EmbeddingMode.API,
        dimension: Optional[int] = None,
    ) -> PackageResponse[EmbeddingResponse]:
        """
        生成 Embedding

        Args:
            texts: 文本列表
            mode: Embedding 模式（API 或 本地）
            dimension: 输出维度（仅部分模型支持）

        Returns:
            PackageResponse 包含 EmbeddingResponse
        """
        try:
            if mode == EmbeddingMode.LOCAL or self._embedding_config.local_enabled:
                embeddings = await self._local_embed(texts)
                return PackageResponse(
                    success=True,
                    data=EmbeddingResponse(
                        embeddings=embeddings,
                        model=self._embedding_config.local_model_name,
                        dimension=len(embeddings[0]) if embeddings else 0,
                    ),
                )
            else:
                embeddings = await self._api_embed(texts, dimension)
                return PackageResponse(
                    success=True,
                    data=EmbeddingResponse(
                        embeddings=embeddings,
                        model=self._embedding_config.name,
                        dimension=dimension or len(embeddings[0]) if embeddings else 0,
                    ),
                )
        except Exception as e:
            self._logger.error(f"Embedding error: {e}")
            return PackageResponse(success=False, error=str(e))

    async def _api_embed(
        self, texts: list[str], dimension: Optional[int] = None
    ) -> list[list[float]]:
        """API Embedding"""
        client = self._get_embedding_client()

        params = {
            "model": self._embedding_config.name,
            "input": texts,
        }
        if dimension:
            params["dimensions"] = dimension

        response = await client.embeddings.create(**params)
        return [item.embedding for item in response.data]

    async def _local_embed(self, texts: list[str]) -> list[list[float]]:
        """
        本地 Embedding (Sentence Transformers - BGE-M3)

        使用 lazy loading 延迟加载模型
        """
        if LLMClient._local_embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._logger.info(
                    f"Loading local embedding model: {self._embedding_config.local_model_name}"
                )
                LLMClient._local_embedding_model = SentenceTransformer(
                    self._embedding_config.local_model_name
                )
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )

        # 在线程池中执行（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: LLMClient._local_embedding_model.encode(
                texts, normalize_embeddings=True
            ),
        )

        return embeddings.tolist()

    async def embed_single(
        self, text: str, mode: EmbeddingMode = EmbeddingMode.API
    ) -> PackageResponse[list[float]]:
        """单个文本 Embedding 的便捷方法"""
        result = await self.embed([text], mode)
        if result.success and result.data:
            return PackageResponse(success=True, data=result.data.embeddings[0])
        return PackageResponse(success=False, error=result.error)
