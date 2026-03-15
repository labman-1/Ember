"""
Context Construction Package
上下文构建管理器

功能:
- 滑动窗口管理历史消息
- 分层构建 (静态层 + 动态层 + 历史层)
- 预设模板 (对话、闲置、状态更新等)
- Token 计数
- Cache 边界标记
"""
import time
import logging
from typing import Optional, Callable
from datetime import datetime

from ember_v2.core.package_base import BasePackage
from ember_v2.core.types import PackageResponse

from .types import Message, ContextSection, BuildOptions, TokenInfo

logger = logging.getLogger(__name__)


class ContextConstruction(BasePackage):
    """
    上下文构建管理器
    
    分层结构:
    1. 静态层: 人设 Prompt (几乎不变，可 Cache)
    2. 动态层: 时间、状态、记忆等 (每次可能变化)
    3. 历史层: 最近 N 条对话 (滑动窗口)
    """
    
    def __init__(
        self,
        system_prompt: str = "",
        window_size: int = 20,
        config_path: Optional[str] = None
    ):
        """
        初始化上下文构建器
        
        Args:
            system_prompt: 系统人设 Prompt
            window_size: 滑动窗口大小
            config_path: 配置文件路径
        """
        super().__init__(config_path)
        
        # 从配置读取默认值
        self._window_size = self.get_config_value("window_size", window_size)
        self._system_prompt = system_prompt
        
        # 内部存储
        self._history: list[Message] = []
        self._dynamic_sections: list[ContextSection] = []
        
        # 时间格式化函数（可自定义）
        self._time_formatter: Optional[Callable[[float], str]] = None
        
        # Token 估算器
        self._token_counter: Optional[Callable[[str], int]] = None
        
        self._logger.info(f"ContextConstruction initialized with window_size={self._window_size}")
    
    # ==================== 存储管理 ====================
    
    def add_message(self, role: str, content: str) -> None:
        """
        添加消息到历史
        
        Args:
            role: 角色
            content: 消息内容
        """
        message = Message(role=role, content=content)
        self._history.append(message)
        self._truncate_history()
    
    def add_messages(self, messages: list[dict]) -> None:
        """
        批量添加消息
        
        Args:
            messages: 消息列表，格式 [{"role": "...", "content": "..."}]
        """
        for msg in messages:
            self.add_message(msg["role"], msg["content"])
    
    def get_recent_messages(self, k: Optional[int] = None) -> list[dict]:
        """
        获取最近 k 条消息
        
        Args:
            k: 获取条数，None 表示全部
        
        Returns:
            消息列表
        """
        if k is None:
            return [msg.to_dict() for msg in self._history]
        return [msg.to_dict() for msg in self._history[-k:]]
    
    def get_history_count(self) -> int:
        """获取历史消息数量"""
        return len(self._history)
    
    def clear_history(self) -> None:
        """清空历史消息"""
        self._history.clear()
        self._logger.info("History cleared")
    
    def set_window_size(self, size: int) -> None:
        """设置滑动窗口大小"""
        self._window_size = size
        self._truncate_history()
    
    def _truncate_history(self) -> None:
        """截断历史到窗口大小"""
        if len(self._history) > self._window_size:
            self._history = self._history[-self._window_size:]
    
    # ==================== 静态层管理 ====================
    
    def set_system_prompt(self, prompt: str) -> None:
        """
        设置系统人设 Prompt
        
        Args:
            prompt: 人设内容
        """
        self._system_prompt = prompt
    
    def get_system_prompt(self) -> str:
        """获取系统 Prompt"""
        return self._system_prompt
    
    # ==================== 动态层管理 ====================
    
    def add_context_section(
        self,
        name: str,
        content: str,
        position: int = 0
    ) -> None:
        """
        添加上下文段落
        
        Args:
            name: 段落名称 (time, state, memory, instruction, custom)
            content: 段落内容
            position: 排序位置，数字越小越靠前
        """
        section = ContextSection(name=name, content=content, position=position)
        # 移除同名的旧段落
        self._dynamic_sections = [
            s for s in self._dynamic_sections if s.name != name
        ]
        self._dynamic_sections.append(section)
        # 按位置排序
        self._dynamic_sections.sort(key=lambda s: s.position)
    
    def clear_dynamic_sections(self) -> None:
        """清空动态段落"""
        self._dynamic_sections.clear()
    
    def set_time_formatter(self, formatter: Callable[[float], str]) -> None:
        """
        设置时间格式化函数
        
        Args:
            formatter: 接收时间戳，返回格式化字符串
        """
        self._time_formatter = formatter
    
    def _format_time(self, timestamp: Optional[float] = None) -> str:
        """格式化时间"""
        ts = timestamp or time.time()
        if self._time_formatter:
            return self._time_formatter(ts)
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y年%m月%d日 %H:%M")
    
    # ==================== 构建方法 ====================
    
    def build(self, options: Optional[BuildOptions] = None) -> list[dict]:
        """
        构建完整的消息列表
        
        Args:
            options: 构建选项
        
        Returns:
            标准消息列表
        """
        opts = options or BuildOptions()
        messages = []
        
        # 1. 静态层：系统 Prompt
        if self._system_prompt:
            system_msg = {"role": "system", "content": self._system_prompt}
            if opts.include_cache_control and opts.cache_static_prefix:
                system_msg["cache_control"] = {"type": "ephemeral"}
            messages.append(system_msg)
        
        # 2. 动态层：各上下文段落
        for section in self._dynamic_sections:
            section_msg = {"role": "system", "content": section.content}
            if opts.include_cache_control and opts.cache_dynamic_sections:
                section_msg["cache_control"] = {"type": "ephemeral"}
            messages.append(section_msg)
        
        # 3. 历史层：对话记录
        if opts.include_history:
            history_limit = opts.history_limit
            history_to_add = self._history
            if history_limit is not None:
                history_to_add = self._history[-history_limit:]
            
            for msg in history_to_add:
                messages.append(msg.to_dict())
        
        return messages
    
    def build_simple(self) -> list[dict]:
        """快速构建，使用默认选项"""
        return self.build()
    
    # ==================== 预设模板 ====================
    
    def build_for_dialogue(
        self,
        state: Optional[dict] = None,
        memory: Optional[str] = None,
        time_info: Optional[str] = None,
        include_history: bool = True
    ) -> list[dict]:
        """
        对话场景模板
        
        自动添加时间、状态、记忆等动态内容
        
        Args:
            state: 当前状态 (PAD 等)
            memory: 相关记忆内容
            time_info: 时间信息，None 则自动生成
            include_history: 是否包含历史对话
        
        Returns:
            构建好的消息列表
        """
        # 清空之前的动态段落
        self.clear_dynamic_sections()
        
        # 添加时间
        time_content = time_info or f"现在的时间是{self._format_time()}"
        self.add_context_section("time", time_content, position=1)
        
        # 添加状态
        if state:
            state_str = self._format_state(state)
            self.add_context_section("state", state_str, position=2)
        
        # 添加记忆
        if memory:
            self.add_context_section("memory", f"[脑海闪现的记忆]：{memory}", position=3)
        
        # 构建
        options = BuildOptions(include_history=include_history)
        return self.build(options)
    
    def build_for_idle(
        self,
        state: dict,
        idle_duration: Optional[str] = None
    ) -> list[dict]:
        """
        闲置场景模板
        
        用于主动发起对话或状态更新
        
        Args:
            state: 当前状态
            idle_duration: 闲置时长描述
        
        Returns:
            构建好的消息列表
        """
        self.clear_dynamic_sections()
        
        # 时间信息
        self.add_context_section("time", f"现在的时间是{self._format_time()}", position=1)
        
        # 状态信息
        state_str = self._format_state(state)
        self.add_context_section("state", state_str, position=2)
        
        # 闲置时长
        if idle_duration:
            self.add_context_section("idle", f"已过去 {idle_duration}", position=3)
        
        return self.build(BuildOptions(include_history=False))
    
    def build_for_state_update(
        self,
        current_state: dict,
        idle_duration: str
    ) -> list[dict]:
        """
        状态更新模板
        
        用于让 LLM 推演状态变化
        
        Args:
            current_state: 当前状态
            idle_duration: 闲置时长
        
        Returns:
            构建好的消息列表
        """
        # 状态更新不需要历史对话，只需要当前信息
        state_json = self._format_state_json(current_state)
        
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": 
                f"当前时间：{self._format_time()}\n"
                f"已过去：{idle_duration}\n"
                f"当前状态：\n{state_json}\n\n"
                f"请根据以上信息，推演角色的状态变化。"}
        ]
        return messages
    
    def build_for_memory_query(
        self,
        query: str,
        context: Optional[str] = None
    ) -> list[dict]:
        """
        记忆查询模板
        
        用于检索或处理记忆
        
        Args:
            query: 查询内容
            context: 额外上下文
        
        Returns:
            构建好的消息列表
        """
        content = f"查询任务：{query}"
        if context:
            content += f"\n\n上下文：{context}"
        
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": content}
        ]
        return messages
    
    # ==================== 格式化方法 ====================
    
    def _format_state(self, state: dict) -> str:
        """格式化状态信息"""
        parts = []
        
        # PAD 情感
        if "pleasure" in state or "arousal" in state or "dominance" in state:
            pad_parts = []
            if "pleasure" in state:
                pad_parts.append(f"愉悦度: {state['pleasure']}")
            if "arousal" in state:
                pad_parts.append(f"激活度: {state['arousal']}")
            if "dominance" in state:
                pad_parts.append(f"支配度: {state['dominance']}")
            parts.append("情感状态: " + ", ".join(pad_parts))
        
        # 其他状态
        for key, value in state.items():
            if key not in ["pleasure", "arousal", "dominance"]:
                parts.append(f"{key}: {value}")
        
        return "\n".join(parts)
    
    def _format_state_json(self, state: dict) -> str:
        """将状态格式化为 JSON 字符串"""
        import json
        return json.dumps(state, ensure_ascii=False, indent=2)
    
    # ==================== Token 计数 ====================
    
    def set_token_counter(self, counter: Callable[[str], int]) -> None:
        """
        设置 Token 计数函数
        
        Args:
            counter: 接收字符串，返回 Token 数量
        """
        self._token_counter = counter
    
    def count_tokens(self, text: str) -> int:
        """
        计算 Token 数量
        
        Args:
            text: 文本内容
        
        Returns:
            Token 数量
        """
        if self._token_counter:
            return self._token_counter(text)
        # 简单估算：中文约 1.5 字符/token，英文约 4 字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)
    
    def get_token_info(self) -> TokenInfo:
        """
        获取当前 Token 信息
        
        Returns:
            TokenInfo 包含各部分的 Token 数
        """
        info = TokenInfo()
        
        # 系统提示
        info.system = self.count_tokens(self._system_prompt)
        
        # 动态段落
        for section in self._dynamic_sections:
            info.dynamic += self.count_tokens(section.content)
        
        # 历史
        for msg in self._history:
            info.history += self.count_tokens(msg.content)
        
        info.total = info.system + info.dynamic + info.history
        return info
    
    # ==================== 工具方法 ====================
    
    def get_messages_for_cache(
        self,
        cache_static: bool = True,
        cache_dynamic: bool = False
    ) -> list[dict]:
        """
        获取带有 Cache 标记的消息列表
        
        用于支持 Prompt Cache 的模型 (如 Claude, Gemini)
        
        Args:
            cache_static: 是否标记静态层为可缓存
            cache_dynamic: 是否标记动态层为可缓存
        
        Returns:
            带有 cache_control 的消息列表
        """
        options = BuildOptions(
            include_cache_control=True,
            cache_static_prefix=cache_static,
            cache_dynamic_sections=cache_dynamic
        )
        return self.build(options)
    
    def peek(self, last_k: int = 3) -> str:
        """
        预览最近的对话内容
        
        Args:
            last_k: 预览最近 k 条
        
        Returns:
            格式化的预览文本
        """
        if not self._history:
            return "(无历史消息)"
        
        recent = self._history[-last_k:]
        lines = []
        for msg in recent:
            lines.append(f"[{msg.role}]: {msg.content[:50]}...")
        return "\n".join(lines)