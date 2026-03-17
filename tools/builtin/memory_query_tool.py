"""
内置工具：记忆查询工具

供 LLM 主动调用检索长期记忆，直接执行向量检索和图谱查询。
参考 config/prompts.yaml 中的 memory_judge_prompt 设计。
"""

import concurrent.futures
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
    同时执行向量语义检索和图谱精确查询。

    参数设计参考 memory_judge_prompt：
    - query: 待检索的历史记忆内容描述（陈述句格式）
    - keywords: 关键词/实体列表，用于语义匹配和图谱查询
    """

    name = "memory_query"
    description = "检索长期记忆，获取与当前话题相关的历史信息。适用于用户询问过去的事、特定实体、或需要维持长期人设连贯性时。"
    short_description = "检索记忆"
    permission = ToolPermission.READONLY
    timeout = 15.0  # 并行检索可能较慢

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "待检索的历史记忆内容描述，使用完整的陈述句描述目标记忆。例如：'第一次见面时的场景和对话'、'关于南京大学的定义和相关经历'。",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词和实体列表（10个以内）。包含人名（真名）、地名、物品、事件、情感词等。例如：['南京大学', '第一次', '喜欢']。用于语义匹配和图谱查询。",
            },
        },
        "required": ["query", "keywords"],
    }

    examples = [
        {
            "scenario": "用户询问过去的事",
            "parameters": {
                "query": "第一次见面时的场景和对话内容",
                "keywords": ["第一次", "见面", "初遇"],
            },
        },
        {
            "scenario": "用户讨论特定实体",
            "parameters": {
                "query": "关于南京大学的定义和相关经历",
                "keywords": ["南京大学", "匡亚明学院", "学校", "校园"],
            },
        },
        {
            "scenario": "用户询问喜好",
            "parameters": {
                "query": "依鸣的喜好和兴趣",
                "keywords": ["喜欢", "爱好", "兴趣", "观鸟", "编程"],
            },
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

        同时调用向量检索和图谱查询，keywords 用于两个系统。

        Args:
            params: {
                "query": str,       # 必需 - 检索查询语句
                "keywords": list    # 必需 - 关键词/实体列表
            }

        Returns:
            ToolResult: 包含检索到的情景记忆和图谱信息
        """
        if not self.hippocampus:
            return ToolResult.fail("海马体未初始化，无法检索记忆")

        query = params.get("query", "")
        keywords = params.get("keywords", [])

        if not query:
            return ToolResult.fail("缺少查询内容 (query)")
        if not keywords:
            return ToolResult.fail("缺少关键词 (keywords)")

        # keywords 同时用于向量检索和图谱查询
        # 筛选可能的实体名（通常是人名、地名等专有名词，长度>=2）
        potential_entities = [kw for kw in keywords if len(kw) >= 2]

        logger.info(
            f"[MemoryQuery] 开始检索: query='{query[:50]}...', keywords={keywords}"
        )

        try:
            # 并行检索：向量检索 + 图谱查询
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # 任务1：PostgreSQL 向量检索
                future_episodic = executor.submit(
                    self.hippocampus._get_persistence_memory,
                    {"query": query, "key_words": keywords},
                )

                # 任务2：Neo4j 图谱查询（使用关键词作为实体）
                future_graph = executor.submit(
                    self.hippocampus._get_graph_memory,
                    potential_entities,
                )

            # 获取向量检索结果
            raw_memories = future_episodic.result(timeout=10)
            simplified_memories = self.hippocampus._simplify_memories(raw_memories)

            # 获取图谱查询结果
            graph_context = self.hippocampus._simplify_graph(
                future_graph.result(timeout=5), query=query, key_words=keywords
            )

            # 统计结果
            episodic_count = len(simplified_memories)
            graph_entity_count = len(graph_context.get("entities", {}))

            logger.info(
                f"[MemoryQuery] 检索完成: 情景记忆 {episodic_count} 条 | "
                f"图谱实体 {graph_entity_count} 个"
            )

            found = episodic_count > 0 or graph_entity_count > 0

            return ToolResult.ok(
                data={
                    "found": found,
                    "episodic_memories": simplified_memories,
                    "graph_entities": graph_context.get("entities", {}),
                    "graph_relations": graph_context.get("relations", []),
                    "query": query,
                    "keywords": keywords,
                }
            )

        except concurrent.futures.TimeoutError:
            logger.error("[MemoryQuery] 检索超时")
            return ToolResult.fail("记忆检索超时，请稍后再试")
        except Exception as e:
            logger.exception(f"[MemoryQuery] 检索失败: {e}")
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
            parts.append(f"找到 {count} 条记忆")
            # 取第一条预览
            if count > 0 and isinstance(episodic[0], str):
                preview = episodic[0][:60].rstrip("...")
                parts.append(f": {preview}...")

        # 图谱实体摘要
        entities = data.get("graph_entities", {})
        if entities:
            names = list(entities.keys())[:3]
            if len(entities) > 3:
                names.append(f"等{len(entities)}个")
            parts.append(f"; 实体: {', '.join(names)}")

        summary = "".join(parts)
        return summary[:max_length] if len(summary) > max_length else summary
