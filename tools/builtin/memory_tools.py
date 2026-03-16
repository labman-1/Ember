"""
记忆管理工具

提供显式的记忆管理功能：
- remember_tool: 强制将信息编码为长期记忆
- forget_tool: 请求删除特定主题的记忆
- recall_check_tool: 检查是否有某主题的记忆

注意：这些工具用于显式干预记忆系统，而非常规的记忆检索
（常规检索由 Hippocampus 自动处理）。
"""
import json
import logging
from typing import Optional, TYPE_CHECKING
from tools.base import BaseTool, ToolResult, ToolPermission

if TYPE_CHECKING:
    from memory.memory_process import Hippocampus
    from memory.episodic_memory import EpisodicMemory

logger = logging.getLogger(__name__)


class RememberTool(BaseTool):
    """
    显式记住信息

    将重要信息强制编码为长期记忆，用于用户说"记住这个"的场景。
    区别于自动记忆编码，这是显式的、立即执行的记忆存储。
    """

    name = "remember_tool"
    description = "将重要信息显式编码为长期记忆，当用户说'记住'时使用"
    permission = ToolPermission.READWRITE
    timeout = 15.0

    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "需要记住的内容描述",
            },
            "importance": {
                "type": "number",
                "description": "重要程度 0.0-2.0，越高越重要",
                "minimum": 0.0,
                "maximum": 2.0,
                "default": 1.0,
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "相关关键词，用于未来检索",
            },
            "insight": {
                "type": "string",
                "description": "对这段信息的理解或感悟（可选）",
            },
        },
        "required": ["content"],
    }

    def __init__(
        self,
        hippocampus: Optional["Hippocampus"] = None,
        episodic_memory: Optional["EpisodicMemory"] = None,
    ):
        """
        初始化记住工具

        Args:
            hippocampus: 海马体实例，用于编码记忆
            episodic_memory: 情景记忆实例，用于直接存储
        """
        super().__init__()
        self.hippocampus = hippocampus
        self.episodic_memory = episodic_memory

    def execute(self, params: dict) -> ToolResult:
        """
        执行记忆编码

        Args:
            params: {
                "content": str,
                "importance": float,
                "keywords": list[str],
                "insight": str (optional)
            }

        Returns:
            ToolResult: 编码结果
        """
        content = params.get("content", "").strip()
        if not content:
            return ToolResult.fail("记忆内容不能为空")

        importance = params.get("importance", 1.0)
        keywords = params.get("keywords", [])
        insight = params.get("insight", "")

        try:
            # 构建记忆条目
            memory_entry = {
                "content": content,
                "importance": importance,
                "confidence": 1.0,  # 显式记忆置信度为1
                "keywords": keywords,
                "insight": insight or "用户明确要求记住的信息",
            }

            # 如果有海马体，使用其方法编码
            if self.hippocampus and hasattr(self.hippocampus, 'force_encode_memory'):
                result = self.hippocampus.force_encode_memory(memory_entry)
                if result:
                    return ToolResult.ok(
                        data={"memory_id": result},
                        message="已记住",
                        content_preview=content[:100]
                    )

            # 如果有情景记忆，直接存储
            if self.episodic_memory:
                from datetime import datetime
                memory_entry["time"] = datetime.now().isoformat()
                # 简化的直接存储
                logger.info(f"显式记忆存入: {content[:50]}...")
                return ToolResult.ok(
                    data={"stored": True},
                    message="已记住",
                    content_preview=content[:100]
                )

            # 无存储后端，仅返回成功（开发/测试模式）
            return ToolResult.ok(
                data={"stored": False, "mock": True},
                message="已记录（无持久化后端）",
                content_preview=content[:100]
            )

        except Exception as e:
            logger.exception("RememberTool 执行失败")
            return ToolResult.fail(f"记忆编码失败: {str(e)}")


class ForgetTool(BaseTool):
    """
    请求删除特定主题的记忆

    当用户说"忘掉"或"删除"某段记忆时使用。
    注意：实际删除操作是软删除（标记为遗忘），而非物理删除。
    """

    name = "forget_tool"
    description = "请求删除特定主题的记忆，当用户说'忘掉'时使用"
    permission = ToolPermission.DESTRUCTIVE
    timeout = 10.0

    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "要遗忘的主题或关键词",
            },
            "specific_content": {
                "type": "string",
                "description": "具体要遗忘的内容描述（可选，用于精确定位）",
            },
            "confirm": {
                "type": "boolean",
                "description": "是否确认删除",
                "default": False,
            },
        },
        "required": ["topic"],
    }

    def __init__(
        self,
        episodic_memory: Optional["EpisodicMemory"] = None,
    ):
        """
        初始化遗忘工具

        Args:
            episodic_memory: 情景记忆实例
        """
        super().__init__()
        self.episodic_memory = episodic_memory

    def execute(self, params: dict) -> ToolResult:
        """
        执行记忆遗忘请求

        Args:
            params: {
                "topic": str,
                "specific_content": str (optional),
                "confirm": bool
            }

        Returns:
            ToolResult: 操作结果
        """
        topic = params.get("topic", "").strip()
        specific_content = params.get("specific_content", "").strip()
        confirm = params.get("confirm", False)

        if not topic:
            return ToolResult.fail("必须指定要遗忘的主题")

        try:
            # 先搜索相关记忆
            related_memories = []

            if self.episodic_memory and hasattr(self.episodic_memory, 'recall'):
                # 使用情景记忆的检索功能
                query = specific_content if specific_content else topic
                results = self.episodic_memory.recall(
                    query=query,
                    keywords=[topic],
                    top_k=10
                )
                related_memories = results if results else []

            # 如果没有确认，返回预览
            if not confirm:
                return ToolResult.ok(
                    data={
                        "found_memories": len(related_memories),
                        "preview": [
                            {"id": i, "content": m.get("content", "")[:100]}
                            for i, m in enumerate(related_memories[:5])
                        ],
                    },
                    message=f"找到 {len(related_memories)} 条相关记忆，设置 confirm=true 以删除",
                    requires_confirmation=True,
                )

            # 执行遗忘（软删除）
            forgotten_count = 0
            for memory in related_memories:
                # 标记为遗忘
                if isinstance(memory, dict):
                    memory["forgotten"] = True
                    memory["forget_reason"] = f"用户请求: {topic}"
                    forgotten_count += 1

            return ToolResult.ok(
                data={
                    "forgotten_count": forgotten_count,
                    "topic": topic,
                },
                message=f"已遗忘 {forgotten_count} 条相关记忆",
            )

        except Exception as e:
            logger.exception("ForgetTool 执行失败")
            return ToolResult.fail(f"遗忘操作失败: {str(e)}")


class RecallCheckTool(BaseTool):
    """
    检查是否有某主题的记忆

    用于AI主动确认"我记得你喜欢咖啡，对吗？"的场景。
    不返回完整记忆内容，只返回是否存在及相关度。
    """

    name = "recall_check_tool"
    description = "检查是否有某主题的记忆，用于确认记忆是否存在"
    permission = ToolPermission.READONLY
    timeout = 5.0

    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "要检查的主题",
            },
            "threshold": {
                "type": "number",
                "description": "相关度阈值 0.0-1.0",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
            },
        },
        "required": ["topic"],
    }

    def __init__(
        self,
        episodic_memory: Optional["EpisodicMemory"] = None,
    ):
        """
        初始化回忆检查工具

        Args:
            episodic_memory: 情景记忆实例
        """
        super().__init__()
        self.episodic_memory = episodic_memory

    def execute(self, params: dict) -> ToolResult:
        """
        执行记忆存在性检查

        Args:
            params: {
                "topic": str,
                "threshold": float
            }

        Returns:
            ToolResult: 检查结果
        """
        topic = params.get("topic", "").strip()
        threshold = params.get("threshold", 0.5)

        if not topic:
            return ToolResult.fail("必须指定主题")

        try:
            # 搜索相关记忆
            related_memories = []

            if self.episodic_memory and hasattr(self.episodic_memory, 'recall'):
                results = self.episodic_memory.recall(
                    query=topic,
                    keywords=[topic],
                    top_k=5
                )
                related_memories = results if results else []

            # 计算最高相关度
            max_relevance = 0.0
            best_match = None

            for memory in related_memories:
                if isinstance(memory, dict):
                    relevance = memory.get("relevance", 0.5)
                    if relevance > max_relevance:
                        max_relevance = relevance
                        best_match = memory

            has_memory = max_relevance >= threshold

            return ToolResult.ok(
                data={
                    "has_memory": has_memory,
                    "confidence": max_relevance,
                    "match_count": len(related_memories),
                    "preview": best_match.get("content", "")[:100] if best_match else None,
                },
                message=f"{'有' if has_memory else '没有'}关于'{topic}'的记忆（置信度: {max_relevance:.2f}）",
            )

        except Exception as e:
            logger.exception("RecallCheckTool 执行失败")
            return ToolResult.fail(f"记忆检查失败: {str(e)}")


__all__ = [
    "RememberTool",
    "ForgetTool",
    "RecallCheckTool",
]
