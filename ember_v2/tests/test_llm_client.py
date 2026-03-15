"""
LLM Client Package 测试
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from ember_v2.packages.llm_client import (
    LLMClient,
    ModelSize,
    EmbeddingMode,
    ChatResponse,
    StreamChunk
)


class TestLLMClientInit:
    """测试 LLMClient 初始化"""
    
    def test_init_with_env_vars(self, monkeypatch):
        """测试从环境变量初始化"""
        monkeypatch.setenv("LARGE_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LARGE_LLM_API_KEY", "test-key")
        monkeypatch.setenv("LARGE_LLM_BASE_URL", "https://api.openai.com/v1")
        
        client = LLMClient()
        
        assert client._large_config.name == "gpt-4o"
        assert client._large_config.api_key == "test-key"
        assert client._large_config.base_url == "https://api.openai.com/v1"
    
    def test_init_with_config_file(self, tmp_path):
        """测试从配置文件初始化"""
        config_content = """
models:
  large:
    name: test-model
    api_key: test-key
    base_url: https://test.api
    timeout: 45
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        
        client = LLMClient(config_path=str(config_file))
        
        assert client.get_config_value("models.large.name") == "test-model"
        assert client.get_config_value("models.large.timeout") == 45


class TestLLMClientChat:
    """测试 LLMClient 聊天功能"""
    
    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI 客户端"""
        with patch("ember_v2.packages.llm_client.client.AsyncOpenAI") as mock:
            yield mock
    
    @pytest.mark.asyncio
    async def test_sync_chat_success(self, monkeypatch, mock_openai_client):
        """测试非流式聊天成功"""
        # 设置环境变量
        monkeypatch.setenv("LARGE_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LARGE_LLM_API_KEY", "test-key")
        monkeypatch.setenv("LARGE_LLM_BASE_URL", "https://api.openai.com/v1")
        
        # Mock 响应
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello, I'm your assistant."
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15
        mock_response.model = "gpt-4o"
        
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_client.return_value = mock_client
        
        client = LLMClient()
        result = await client.chat_sync([{"role": "user", "content": "Hello"}])
        
        assert result.success
        assert result.data.content == "Hello, I'm your assistant."
        assert result.data.usage.total_tokens == 15
    
    @pytest.mark.asyncio
    async def test_stream_chat_success(self, monkeypatch, mock_openai_client):
        """测试流式聊天成功"""
        monkeypatch.setenv("LARGE_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LARGE_LLM_API_KEY", "test-key")
        monkeypatch.setenv("LARGE_LLM_BASE_URL", "https://api.openai.com/v1")
        
        # Mock 流式响应
        async def mock_stream():
            chunks = [
                MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello", reasoning_content=None), finish_reason=None)]),
                MagicMock(choices=[MagicMock(delta=MagicMock(content=" world", reasoning_content=None), finish_reason=None)]),
                MagicMock(choices=[MagicMock(delta=MagicMock(content="", reasoning_content=None), finish_reason="stop")]),
            ]
            for chunk in chunks:
                yield chunk
        
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_openai_client.return_value = mock_client
        
        client = LLMClient()
        result = await client.chat_stream([{"role": "user", "content": "Hi"}])
        
        assert result.success
        
        # 收集流式输出
        collected = []
        async for chunk in result.data:
            collected.append(chunk)
        
        assert len(collected) >= 2
        assert collected[0].content == "Hello"
        assert collected[1].content == " world"
    
    @pytest.mark.asyncio
    async def test_small_chat(self, monkeypatch, mock_openai_client):
        """测试小模型调用"""
        monkeypatch.setenv("SMALL_LLM_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("SMALL_LLM_API_KEY", "test-key")
        monkeypatch.setenv("SMALL_LLM_BASE_URL", "https://api.openai.com/v1")
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Quick response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = None
        mock_response.model = "gpt-4o-mini"
        
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_client.return_value = mock_client
        
        client = LLMClient()
        result = await client.small_chat([{"role": "user", "content": "Quick question"}])
        
        assert result.success
        assert result.data.content == "Quick response"


class TestLLMClientEmbedding:
    """测试 LLMClient Embedding 功能"""
    
    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI 客户端"""
        with patch("ember_v2.packages.llm_client.client.AsyncOpenAI") as mock:
            yield mock
    
    @pytest.mark.asyncio
    async def test_api_embedding(self, monkeypatch, mock_openai_client):
        """测试 API Embedding"""
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        
        # Mock 响应
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3]),
            MagicMock(embedding=[0.4, 0.5, 0.6])
        ]
        
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        mock_openai_client.return_value = mock_client
        
        client = LLMClient()
        result = await client.embed(["hello", "world"], mode=EmbeddingMode.API)
        
        assert result.success
        assert len(result.data.embeddings) == 2
        assert result.data.embeddings[0] == [0.1, 0.2, 0.3]
    
    @pytest.mark.asyncio
    async def test_local_embedding(self, monkeypatch):
        """测试本地 Embedding"""
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        
        # Mock sentence_transformers
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[0.1, 0.2, 0.3]])
        
        with patch.dict(
            "sys.modules",
            {"sentence_transformers": MagicMock(SentenceTransformer=MagicMock(return_value=mock_model))}
        ):
            client = LLMClient()
            # 强制启用本地模式
            client._embedding_config.local_enabled = True
            
            result = await client.embed(["test"], mode=EmbeddingMode.LOCAL)
            
            assert result.success
            assert result.data.embeddings[0] == [0.1, 0.2, 0.3]


class TestPackageResponse:
    """测试 PackageResponse"""
    
    def test_success_response(self):
        """测试成功响应"""
        response = ChatResponse(content="test", model="gpt-4")
        from ember_v2.core.types import PackageResponse
        
        pkg_response = PackageResponse(success=True, data=response)
        
        assert pkg_response.is_ok()
        assert pkg_response.data.content == "test"
    
    def test_error_response(self):
        """测试错误响应"""
        from ember_v2.core.types import PackageResponse
        
        pkg_response = PackageResponse(success=False, error="API Error")
        
        assert not pkg_response.is_ok()
        assert pkg_response.error == "API Error"
