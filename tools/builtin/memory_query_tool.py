"""
内置工具：记忆查询工具

封装 Hippocampus.load_memory 功能，供 LLM 主动调用检索记忆。
"""

import json
import logging
from typing import Optional, TYPE_CHECKING
from tools.base import BaseTool, ToolResult, ToolPermission

if TYPE_CHECKING:
    from memory.memory_process import Hippocampus

logger = logging.getLogger(__name__)


class MemoryQueryTool(BaseTool):
    """
    记忆查询工具

    允许 AI 主动检索长期记忆，获取与当前对话相关的历史信息。
    基于 Hippocampus.load_memory 实现。
    """

    name = "memory_query"
    description = "检索长期记忆，获取与当前话题相关的历史信息"
    short_description = "检索记忆"
    permission = ToolPermission.READONLY
    timeout = 10.0  # 检索可能较慢

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询语句，描述想查找的记忆内容",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词列表，用于精确匹配",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "相关实体名称（人名、地点等）",
            },
        },
        "required": ["query"],
    }

    examples = [
        {
            "user": "我们之前聊过什么关于编程的话题？",
            "parameters": {
                "query": "编程相关的对话",
                "keywords": ["编程", "代码", "算法"],
            },
        },
        {
            "user": "我记得你说过你喜欢什么来着？",
            "parameters": {"query": "喜好兴趣", "keywords": ["喜欢", "爱好"]},
        },
    ]

    def __init__(self, hippocampus: Optional["Hippocampus"] = None):
        """
        初始化记忆查询工具

        Args:
            hippocampus: 海马体实例，用于执行记忆检索
        """
        super().__init__()
        self.hippocampus = hippocampus

    def execute(self, params: dict) -> ToolResult:
        """
        执行记忆检索

        Args:
            params: {
                "query": str,          # 必需
                "keywords": list[str], # 可选
                "entities": list[str]  # 可选
            }

        Returns:
            ToolResult: 包含检索到的记忆
        """
        if not self.hippocampus:
            return ToolResult.fail("海马体未初始化，无法检索记忆")

        query = params.get("query", "")
        keywords = params.get("keywords", [])
        entities = params.get("entities", [])

        if not query:
            return ToolResult.fail("缺少查询内容")

        try:
            # 构建检索请求
            content = json.dumps(
                {
                    "query": query,
                    "keywords": keywords,
                    "entities": entities,
                },
                ensure_ascii=False,
            )

            # 调用 Hippocampus 检索
            # 注意：load_memory 原本期望的是 history 和 state，这里简化使用
            result = self.hippocampus.load_memory([content])

            if not result:
                return ToolResult.ok(data={"found": False, "message": "未找到相关记忆"})

            # 解析结果
            if isinstance(result, str):
                memories = json.loads(result)
            else:
                memories = result

            # 统计结果
            episodic_count = len(memories.get("episodic_memories", []))
            graph_entities = memories.get("graph_context", {}).get("entities", {})

            logger.info(
                f"[MemoryQuery] 查询: {query[:30]}... | "
                f"情景记忆: {episodic_count}条 | 图谱实体: {len(graph_entities)}个"
            )

            return ToolResult.ok(
                data={
                    "found": episodic_count > 0 or len(graph_entities) > 0,
                    "episodic_memories": memories.get("episodic_memories", []),
                    "graph_entities": graph_entities,
                    "graph_relations": memories.get("graph_context", {}).get(
                        "relations", []
                    ),
                }
            )

        except json.JSONDecodeError as e:
            logger.error(f"记忆检索结果解析失败: {e}")
            return ToolResult.fail(f"记忆解析失败: {str(e)}")
        except Exception as e:
            logger.error(f"记忆检索失败: {e}")
            return ToolResult.fail(f"检索失败: {str(e)}")

    def summarize_result(self, result: ToolResult, max_length: int = 200) -> str:
        """
        将检索结果摘要为自然语言

        Args:
            result: 工具执行结果
            max_length: 摘要最大长度

        Returns:
            自然语言摘要
        """
        if not result.success:
            return f"检索失败: {result.error}"

        data = result.data
        if not data.get("found"):
            return "未找到相关记忆"

        parts = []

        # 情景记忆摘要
        episodic = data.get("episodic_memories", [])
        if episodic:
            count = len(episodic)
            parts.append(f"找到{count}条相关记忆")
            # 取第一条预览
            if count > 0 and isinstance(episodic[0], str):
                preview = episodic[0][:50]
                parts.append(f": {preview}...")

        # 图谱实体摘要
        entities = data.get("graph_entities", {})
        if entities:
            names = list(entities.keys())[:3]
            parts.append(f"; 相关实体: {', '.join(names)}")

        summary = "".join(parts)
        return summary[:max_length] if len(summary) > max_length else summary
