"""
工具意图识别器

识别用户输入是否需要工具支持，减少不必要的工具调用尝试。
用于在注入工具描述前进行预过滤，避免在简单问候对话中浪费token。
"""
import logging
import re
from typing import List, Pattern, Optional
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)


class ToolIntent(Enum):
    """工具使用意图类型"""
    NO_TOOL_NEEDED = auto()      # 不需要工具
    LIKELY_NEEDS_TOOL = auto()   # 可能需要工具
    DEFINITELY_NEEDS_TOOL = auto()  # 明确需要工具
    UNCLEAR = auto()             # 意图不明确


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: ToolIntent
    confidence: float  # 0-1
    reason: str
    suggested_tools: List[str] = None

    def __post_init__(self):
        if self.suggested_tools is None:
            self.suggested_tools = []


class ToolIntentRecognizer:
    """
    识别用户输入是否需要工具支持

    用于减少不必要的工具调用尝试，过滤掉简单问候、闲聊等不需要工具的对话。

    Example:
        >>> recognizer = ToolIntentRecognizer()
        >>> result = recognizer.recognize("现在几点了？")
        >>> print(result.intent)  # ToolIntent.DEFINITELY_NEEDS_TOOL
        >>> result = recognizer.recognize("你好")
        >>> print(result.intent)  # ToolIntent.NO_TOOL_NEEDED
    """

    # 不需要工具的常见问候语和闲聊模式
    CASUAL_PATTERNS: List[Pattern] = [
        # 问候
        re.compile(r'^你好', re.IGNORECASE),
        re.compile(r'^您好', re.IGNORECASE),
        re.compile(r'^嗨', re.IGNORECASE),
        re.compile(r'^嗨[\s\n]', re.IGNORECASE),
        re.compile(r'^在吗', re.IGNORECASE),
        re.compile(r'^在么', re.IGNORECASE),
        re.compile(r'^在不在', re.IGNORECASE),
        re.compile(r'^早[安上]*$', re.IGNORECASE),
        re.compile(r'^晚[安上好]*$', re.IGNORECASE),
        re.compile(r'^午安', re.IGNORECASE),
        re.compile(r'^哈喽', re.IGNORECASE),
        re.compile(r'^hello', re.IGNORECASE),
        re.compile(r'^hi$', re.IGNORECASE),
        re.compile(r'^hey$', re.IGNORECASE),

        # 感叹/语气
        re.compile(r'^谢谢', re.IGNORECASE),
        re.compile(r'^感谢', re.IGNORECASE),
        re.compile(r'^好的*$', re.IGNORECASE),
        re.compile(r'^ok$', re.IGNORECASE),
        re.compile(r'^okay$', re.IGNORECASE),
        re.compile(r'^哈哈+', re.IGNORECASE),
        re.compile(r'^嗯+$', re.IGNORECASE),
        re.compile(r'^哦+$', re.IGNORECASE),
        re.compile(r'^啊+$', re.IGNORECASE),
        re.compile(r'^好吧', re.IGNORECASE),
        re.compile(r'^行吧', re.IGNORECASE),

        # 简单疑问
        re.compile(r'^怎么了$', re.IGNORECASE),
        re.compile(r'^什么意思$', re.IGNORECASE),
        re.compile(r'^然后呢$', re.IGNORECASE),
        re.compile(r'^为什么$', re.IGNORECASE),
        re.compile(r'^怎么样$', re.IGNORECASE),
        re.compile(r'^是吗$', re.IGNORECASE),
        re.compile(r'^真的吗$', re.IGNORECASE),
        re.compile(r'^好吧$', re.IGNORECASE),

        # 告别
        re.compile(r'^再见', re.IGNORECASE),
        re.compile(r'^拜拜', re.IGNORECASE),
        re.compile(r'^bye', re.IGNORECASE),
        re.compile(r'^回头见', re.IGNORECASE),
        re.compile(r'^下次聊', re.IGNORECASE),

        # 无意义的短输入
        re.compile(r'^[.。,，;；！!？?\s]+$', re.IGNORECASE),
        re.compile(r'^[0-9]+$', re.IGNORECASE),
    ]

    # 明确需要工具的关键词（高置信度）
    DEFINITE_TOOL_KEYWORDS: List[str] = [
        # 时间工具
        '几点', '现在时间', '当前时间', '今天日期', '今天几号',
        'timestamp', 'utc时间', '时区',

        # 记忆工具
        '记住', '帮我记住', '记住这个', '别忘了',
        '忘掉', '删除记忆', '清除记忆',
        '回忆一下', '记得我', '我以前说过',

        # 笔记工具
        '记下来', '记笔记', '创建笔记', '写个备忘',
        '待办事项', 'todo list', 'checklist',

        # 文件工具
        '读取文件', '打开文件', '查看文件',
        '保存到文件', '写入文件', '下载文件',
    ]

    # 可能需要工具的关键词（中等置信度）
    LIKELY_TOOL_KEYWORDS: List[str] = [
        '时间', '日期', '什么时候', '多久',
        '记得', '回忆', '以前', '曾经说过',
        '笔记', '记录', '记下', '备忘',
        '文件', '保存', '读取', '打开',
    ]

    # 与特定工具相关的关键词映射
    TOOL_KEYWORD_MAP: dict = {
        'time_tool': ['几点', '时间', '日期', '今天', '现在', '什么时候', 'timestamp'],
        'remember_tool': ['记住', '帮我记', '记住这个', '别忘了'],
        'forget_tool': ['忘掉', '删除记忆', '清除记忆', '忘记'],
        'recall_check_tool': ['记得我', '我以前说过', '回忆一下', '我曾经'],
        'note_tool': ['笔记', '记下来', '记笔记', '备忘', '待办', 'todo'],
        'file_tool': ['文件', '读取', '打开', '保存', '下载'],
    }

    def __init__(self):
        """初始化意图识别器"""
        self._casual_patterns = self.CASUAL_PATTERNS.copy()
        self._definite_keywords = self.DEFINITE_TOOL_KEYWORDS.copy()
        self._likely_keywords = self.LIKELY_TOOL_KEYWORDS.copy()
        self._tool_keyword_map = self.TOOL_KEYWORD_MAP.copy()

    def recognize(self, message: str) -> IntentResult:
        """
        识别用户消息的工具使用意图

        Args:
            message: 用户输入消息

        Returns:
            IntentResult: 识别结果
        """
        message = message.strip()
        message_lower = message.lower()

        # 1. 检查是否是明显的闲聊/问候（不需要工具）
        if self._is_casual_conversation(message):
            return IntentResult(
                intent=ToolIntent.NO_TOOL_NEEDED,
                confidence=0.9,
                reason="检测到问候语或闲聊模式"
            )

        # 2. 检查明确需要工具的关键词
        definite_match = self._match_keywords(message_lower, self._definite_keywords)
        if definite_match:
            suggested_tools = self._suggest_tools_for_keywords(message_lower)
            return IntentResult(
                intent=ToolIntent.DEFINITELY_NEEDS_TOOL,
                confidence=0.95,
                reason=f"明确需要工具的关键词: {definite_match}",
                suggested_tools=suggested_tools
            )

        # 3. 检查可能需要工具的关键词
        likely_match = self._match_keywords(message_lower, self._likely_keywords)
        if likely_match:
            suggested_tools = self._suggest_tools_for_keywords(message_lower)
            return IntentResult(
                intent=ToolIntent.LIKELY_NEEDS_TOOL,
                confidence=0.7,
                reason=f"可能需要工具的关键词: {likely_match}",
                suggested_tools=suggested_tools
            )

        # 4. 检查句子结构（疑问句可能不需要工具）
        if self._is_simple_question(message):
            return IntentResult(
                intent=ToolIntent.NO_TOOL_NEEDED,
                confidence=0.6,
                reason="简单问句，不需要外部信息"
            )

        # 5. 默认情况
        return IntentResult(
            intent=ToolIntent.UNCLEAR,
            confidence=0.5,
            reason="意图不明确"
        )

    def needs_tool(self, message: str, threshold: float = 0.6) -> bool:
        """
        快速判断消息是否需要工具支持

        Args:
            message: 用户消息
            threshold: 判断阈值（置信度高于此值认为需要工具）

        Returns:
            是否需要工具
        """
        result = self.recognize(message)

        if result.intent == ToolIntent.DEFINITELY_NEEDS_TOOL:
            return True
        if result.intent == ToolIntent.LIKELY_NEEDS_TOOL and result.confidence >= threshold:
            return True

        return False

    def _is_casual_conversation(self, message: str) -> bool:
        """检查是否是闲聊/问候"""
        for pattern in self._casual_patterns:
            if pattern.match(message.strip()):
                return True
        return False

    def _match_keywords(self, message: str, keywords: List[str]) -> Optional[str]:
        """匹配关键词，返回匹配到的第一个关键词"""
        for keyword in keywords:
            if keyword.lower() in message:
                return keyword
        return None

    def _suggest_tools_for_keywords(self, message: str) -> List[str]:
        """根据关键词建议可能的工具"""
        suggested = []
        for tool_name, keywords in self._tool_keyword_map.items():
            for keyword in keywords:
                if keyword in message:
                    if tool_name not in suggested:
                        suggested.append(tool_name)
                    break
        return suggested

    def _is_simple_question(self, message: str) -> bool:
        """检查是否是简单问句（不需要外部信息）"""
        # 以问号结尾的短句
        if message.endswith('?') or message.endswith('？'):
            # 长度小于10且不含特定关键词
            if len(message) < 15:
                no_tool_indicators = ['你', '感觉', '觉得', '认为', '喜欢', '想']
                if any(ind in message for ind in no_tool_indicators):
                    return True
        return False

    def add_casual_pattern(self, pattern: Pattern):
        """添加自定义闲聊模式"""
        self._casual_patterns.append(pattern)

    def add_definite_keyword(self, keyword: str):
        """添加明确需要工具的关键词"""
        self._definite_keywords.append(keyword)

    def add_tool_keyword_mapping(self, tool_name: str, keywords: List[str]):
        """
        添加工具关键词映射

        Args:
            tool_name: 工具名称
            keywords: 触发该工具的关键词列表
        """
        if tool_name in self._tool_keyword_map:
            self._tool_keyword_map[tool_name].extend(keywords)
        else:
            self._tool_keyword_map[tool_name] = keywords.copy()


# 全局实例
_default_recognizer: Optional[ToolIntentRecognizer] = None


def get_intent_recognizer() -> ToolIntentRecognizer:
    """获取默认的意图识别器实例"""
    global _default_recognizer
    if _default_recognizer is None:
        _default_recognizer = ToolIntentRecognizer()
    return _default_recognizer


def needs_tool(message: str, threshold: float = 0.6) -> bool:
    """
    快速判断消息是否需要工具（便捷函数）

    Args:
        message: 用户消息
        threshold: 判断阈值

    Returns:
        是否需要工具
    """
    return get_intent_recognizer().needs_tool(message, threshold)
