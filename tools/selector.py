"""
动态工具选择器

基于对话意图动态选择相关工具，减少不必要的工具描述注入prompt。
使用关键词匹配和工具分类索引实现快速筛选。
"""
import logging
import re
from typing import List, Dict, Set, Optional
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class ToolSelector:
    """
    基于对话上下文动态选择相关工具

    通过关键词匹配和语义相似度，从可用工具中筛选出与当前对话最相关的工具，
    减少prompt中工具描述占用的token数量。

    Example:
        >>> selector = ToolSelector()
        >>> selector.register_tool_categories({
        ...     "time": ["time_tool"],
        ...     "memory": ["remember_tool", "recall_check_tool"],
        ... })
        >>> tools = selector.select_tools("现在几点了？", ["time_tool", "remember_tool"])
        >>> print(tools)  # ["time_tool"]
    """

    # 工具分类索引 - 工具名 -> 分类标签
    TOOL_CATEGORIES: Dict[str, List[str]] = {
        "time_tool": ["time", "datetime", "query"],
        "file_tool": ["file", "io", "storage"],
        "note_tool": ["note", "memory", "write"],
        "remember_tool": ["memory", "write", "persistent"],
        "forget_tool": ["memory", "delete", "persistent"],
        "recall_check_tool": ["memory", "query", "persistent"],
    }

    # 意图关键词映射 - 关键词 -> 相关分类
    INTENT_KEYWORDS: Dict[str, List[str]] = {
        # 时间相关
        "几点": ["time"],
        "时间": ["time"],
        "日期": ["time"],
        "今天": ["time"],
        "现在": ["time"],
        "什么时候": ["time"],
        "多久": ["time"],
        "timeout": ["time"],
        "时刻": ["time"],

        # 文件相关
        "文件": ["file"],
        "保存": ["file", "note"],
        "读取": ["file"],
        "打开": ["file"],
        "写入": ["file"],
        "下载": ["file"],

        # 笔记相关
        "笔记": ["note"],
        "记录": ["note"],
        "记下": ["note"],
        "待办": ["note"],
        "todo": ["note"],

        # 记忆相关
        "记住": ["memory"],
        "记得": ["memory"],
        "回忆": ["memory"],
        "想起": ["memory"],
        "遗忘": ["memory"],
        "忘掉": ["memory"],
        "曾经说过": ["memory"],
        "以前说过": ["memory"],
    }

    def __init__(self):
        """初始化工具选择器"""
        self._tool_categories: Dict[str, List[str]] = self.TOOL_CATEGORIES.copy()
        self._intent_keywords: Dict[str, List[str]] = self.INTENT_KEYWORDS.copy()
        self._tool_names: List[str] = []

    def register_tool_categories(self, categories: Dict[str, List[str]]):
        """
        注册工具分类

        Args:
            categories: 工具名 -> 分类标签列表 的映射
        """
        self._tool_categories.update(categories)

    def register_intent_keywords(self, keywords: Dict[str, List[str]]):
        """
        注册意图关键词

        Args:
            keywords: 关键词 -> 相关分类列表 的映射
        """
        self._intent_keywords.update(keywords)

    def set_available_tools(self, tool_names: List[str]):
        """
        设置当前可用的工具列表

        Args:
            tool_names: 可用工具名称列表
        """
        self._tool_names = tool_names

    def select_tools(
        self,
        user_message: str,
        available_tools: Optional[List[str]] = None,
        min_relevance: float = 0.3,
        max_tools: int = 5
    ) -> List[str]:
        """
        基于用户输入选择可能需要的工具

        Args:
            user_message: 用户输入消息
            available_tools: 可用工具列表，None则使用之前设置的列表
            min_relevance: 最小相关度阈值（0-1）
            max_tools: 最多返回的工具数量

        Returns:
            工具名称列表（按相关度排序）
        """
        if available_tools is None:
            available_tools = self._tool_names

        if not available_tools:
            return []

        # 计算每个工具的相关度分数
        tool_scores: Dict[str, float] = {}

        for tool_name in available_tools:
            score = self._calculate_relevance(user_message, tool_name)
            if score >= min_relevance:
                tool_scores[tool_name] = score

        # 按分数排序并限制数量
        sorted_tools = sorted(
            tool_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        selected = [name for name, _ in sorted_tools[:max_tools]]

        logger.debug(
            f"工具选择: 消息='{user_message[:30]}...' "
            f"选中={selected} (从{len(available_tools)}个工具中)"
        )

        return selected

    def _calculate_relevance(self, message: str, tool_name: str) -> float:
        """
        计算工具与消息的相关度

        Returns:
            相关度分数（0-1）
        """
        message = message.lower()
        score = 0.0

        # 1. 关键词匹配
        categories = self._tool_categories.get(tool_name, [])
        for keyword, related_cats in self._intent_keywords.items():
            if keyword in message:
                # 检查是否有共同分类
                common_cats = set(categories) & set(related_cats)
                if common_cats:
                    score += 0.4 * len(common_cats)

        # 2. 工具名直接匹配（模糊匹配）
        tool_base_name = tool_name.replace("_tool", "").lower()
        if tool_base_name in message:
            score += 0.5

        # 模糊匹配（用于类似"笔记"匹配"note_tool"）
        for word in message.split():
            if len(word) >= 2:
                similarity = SequenceMatcher(None, word, tool_base_name).ratio()
                if similarity > 0.7:
                    score += 0.3 * similarity

        # 3. 特定工具的特殊触发词
        if tool_name == "time_tool":
            time_patterns = [r'几点', r'时间', r'日期', r'今天', r'现在', r'什么时候']
            for pattern in time_patterns:
                if re.search(pattern, message):
                    score += 0.3

        elif tool_name in ["remember_tool", "forget_tool"]:
            memory_patterns = [r'记住', r'记住.*是', r'帮我记', r'别忘了']
            for pattern in memory_patterns:
                if re.search(pattern, message):
                    score += 0.3

        return min(score, 1.0)  # 限制最大值为1

    def should_use_tools(self, message: str, threshold: float = 0.2) -> bool:
        """
        判断消息是否需要使用工具

        Args:
            message: 用户消息
            threshold: 触发工具使用的最低相关度

        Returns:
            是否需要使用工具
        """
        # 检查是否有明显的时间/记忆/文件关键词
        trigger_words = [
            # 时间
            '几点', '时间', '日期', '今天几号', '现在',
            # 记忆
            '记住', '记得', '回忆', '以前', '曾经说过',
            # 文件
            '文件', '保存', '读取', '打开', '下载',
            # 笔记
            '笔记', '记录', '记下', '待办',
        ]

        message_lower = message.lower()

        for word in trigger_words:
            if word in message_lower:
                return True

        # 检查是否是问句但可能不需要工具
        casual_patterns = [
            r'^你好', r'^嗨', r'^在吗', r'^早$', r'^晚安',
            r'^谢谢', r'^好的', r'^哈哈', r'^嗯$',
            r'^怎么了', r'^为什么', r'^怎么样',
        ]

        for pattern in casual_patterns:
            if re.match(pattern, message.strip()):
                return False

        return True


# 全局选择器实例
_default_selector: Optional[ToolSelector] = None


def get_tool_selector() -> ToolSelector:
    """获取默认的工具选择器实例"""
    global _default_selector
    if _default_selector is None:
        _default_selector = ToolSelector()
    return _default_selector
