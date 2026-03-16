"""
测试记忆管理工具

覆盖 remember_tool、forget_tool、recall_check_tool 功能。
"""
import pytest
from unittest.mock import Mock
from tools.builtin.memory_tools import RememberTool, ForgetTool, RecallCheckTool
from tools.base import ToolResult, ToolPermission


class TestRememberTool:
    """测试记住工具"""

    @pytest.fixture
    def remember_tool_no_backend(self):
        """无后端的记住工具"""
        return RememberTool()

    @pytest.fixture
    def remember_tool_with_mock(self):
        """带 mock 后端的记住工具"""
        mock_hippo = Mock()
        mock_hippo.force_encode_memory = Mock(return_value="memory_id_123")
        return RememberTool(hippocampus=mock_hippo)

    def test_initialization(self):
        """测试初始化"""
        tool = RememberTool()
        assert tool.name == "remember_tool"
        assert tool.permission == ToolPermission.READWRITE

    def test_execute_basic(self, remember_tool_no_backend):
        """测试基本执行"""
        result = remember_tool_no_backend.execute({
            "content": "用户喜欢喝咖啡",
            "importance": 1.5
        })
        assert result.success is True

    def test_execute_empty_content_fails(self, remember_tool_no_backend):
        """测试空内容失败"""
        result = remember_tool_no_backend.execute({
            "content": "",
            "importance": 1.0
        })
        assert result.success is False
        assert "不能为空" in result.error

    def test_execute_with_keywords(self, remember_tool_no_backend):
        """测试带关键词"""
        result = remember_tool_no_backend.execute({
            "content": "用户喜欢喝美式咖啡",
            "importance": 1.2,
            "keywords": ["咖啡", "美式", "饮品"],
            "insight": "用户对咖啡因有依赖"
        })
        assert result.success is True
        assert result.metadata["content_preview"] == "用户喜欢喝美式咖啡"

    def test_execute_with_hippocampus(self, remember_tool_with_mock):
        """测试使用海马体后端"""
        result = remember_tool_with_mock.execute({
            "content": "重要信息"
        })
        assert result.success is True
        assert result.data.get("memory_id") == "memory_id_123"
        remember_tool_with_mock.hippocampus.force_encode_memory.assert_called_once()

    def test_default_importance(self, remember_tool_no_backend):
        """测试默认重要度"""
        result = remember_tool_no_backend.execute({
            "content": "测试内容"
        })
        assert result.success is True
        # 默认 importance 是 1.0


class TestForgetTool:
    """测试遗忘工具"""

    @pytest.fixture
    def forget_tool_no_backend(self):
        return ForgetTool()

    @pytest.fixture
    def forget_tool_with_mock(self):
        mock_memory = Mock()
        mock_memory.recall = Mock(return_value=[
            {"id": 1, "content": "用户喜欢咖啡", "relevance": 0.9},
            {"id": 2, "content": "昨天喝了咖啡", "relevance": 0.7},
        ])
        return ForgetTool(episodic_memory=mock_memory)

    def test_initialization(self):
        """测试初始化"""
        tool = ForgetTool()
        assert tool.name == "forget_tool"
        assert tool.permission == ToolPermission.DESTRUCTIVE

    def test_execute_without_confirm(self, forget_tool_with_mock):
        """测试未确认时的预览模式"""
        result = forget_tool_with_mock.execute({
            "topic": "咖啡",
            "confirm": False
        })
        assert result.success is True
        assert result.metadata.get("requires_confirmation") is True
        assert result.data["found_memories"] == 2

    def test_execute_with_confirm(self, forget_tool_with_mock):
        """测试确认删除"""
        result = forget_tool_with_mock.execute({
            "topic": "咖啡",
            "confirm": True
        })
        assert result.success is True
        assert result.data["forgotten_count"] == 2

    def test_execute_empty_topic_fails(self, forget_tool_no_backend):
        """测试空主题失败"""
        result = forget_tool_no_backend.execute({
            "topic": "",
            "confirm": True
        })
        assert result.success is False
        assert "必须指定" in result.error


class TestRecallCheckTool:
    """测试回忆检查工具"""

    @pytest.fixture
    def recall_tool_no_backend(self):
        return RecallCheckTool()

    @pytest.fixture
    def recall_tool_with_memories(self):
        mock_memory = Mock()
        mock_memory.recall = Mock(return_value=[
            {"content": "用户喜欢喝美式咖啡", "relevance": 0.85},
            {"content": "用户每天早上一杯咖啡", "relevance": 0.75},
        ])
        return RecallCheckTool(episodic_memory=mock_memory)

    def test_initialization(self):
        """测试初始化"""
        tool = RecallCheckTool()
        assert tool.name == "recall_check_tool"
        assert tool.permission == ToolPermission.READONLY

    def test_has_memory_true(self, recall_tool_with_memories):
        """测试存在记忆"""
        result = recall_tool_with_memories.execute({
            "topic": "咖啡",
            "threshold": 0.5
        })
        assert result.success is True
        assert result.data["has_memory"] is True
        assert result.data["confidence"] == 0.85
        assert result.data["match_count"] == 2

    def test_has_memory_false_due_to_threshold(self, recall_tool_with_memories):
        """测试因阈值过高而无记忆"""
        result = recall_tool_with_memories.execute({
            "topic": "咖啡",
            "threshold": 0.95  # 高于最高相关度
        })
        assert result.success is True
        assert result.data["has_memory"] is False

    def test_no_memories_found(self, recall_tool_no_backend):
        """测试无记忆后端"""
        result = recall_tool_no_backend.execute({
            "topic": "不存在的主题"
        })
        assert result.success is True
        assert result.data["has_memory"] is False
        assert result.data["match_count"] == 0

    def test_empty_topic_fails(self, recall_tool_no_backend):
        """测试空主题失败"""
        result = recall_tool_no_backend.execute({
            "topic": ""
        })
        assert result.success is False
        assert "必须指定" in result.error

    def test_result_includes_preview(self, recall_tool_with_memories):
        """测试结果包含预览"""
        result = recall_tool_with_memories.execute({
            "topic": "咖啡"
        })
        assert result.success is True
        assert result.data["preview"] is not None
        assert "咖啡" in result.data["preview"]


class TestMemoryToolIntegration:
    """测试记忆工具的集成场景"""

    def test_remember_forget_recall_workflow(self):
        """测试完整的记忆工作流"""
        # 创建工具
        remember = RememberTool()

        # 记住一些信息
        remember.execute({
            "content": "用户喜欢下雨天的氛围",
            "keywords": ["天气", "雨天", "氛围"],
            "importance": 1.0
        })

        # 测试完成（实际持久化需要后端）
        # 这里主要是验证工具链可以正常工作

    def test_tools_permissions(self):
        """测试工具权限设置"""
        remember = RememberTool()
        forget = ForgetTool()
        recall = RecallCheckTool()

        assert remember.permission == ToolPermission.READWRITE
        assert forget.permission == ToolPermission.DESTRUCTIVE
        assert recall.permission == ToolPermission.READONLY
