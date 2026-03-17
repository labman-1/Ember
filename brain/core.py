from brain.llm_client import LLMClient
from config.settings import settings
from memory.short_term import ShortTermMemory
from core.event_bus import EventBus, Event
from persona.state_manager import StateManager
import threading
import logging
from memory.memory_process import Hippocampus
import json
from brain.tag_utils import validate_and_fix_llm_output
from tools.brain_mixin import ToolEnabledBrain

logger = logging.getLogger(__name__)


class Brain(ToolEnabledBrain):

    def __init__(
        self,
        event_bus: EventBus,
        state_manager: StateManager,
        memory: ShortTermMemory,
        hippocampus: Hippocampus,
    ):
        self.lock = threading.Lock()
        self._is_processing = False
        self.llm_client = LLMClient()
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.memory = memory
        self.hippocampus = hippocampus

        # 初始化工具系统 (ToolEnabledBrain Mixin)
        ToolEnabledBrain.__init__(
            self,
            event_bus=event_bus,
            hippocampus=hippocampus,
        )

        self.event_bus.subscribe("user.input", self._on_user_input)
        self.event_bus.subscribe("idle_speak", self._on_idle_speak)

    def _on_user_input(self, event: Event):
        user_msg = event.data["text"]
        thread = threading.Thread(target=self.process_dialogue, args=(user_msg,))
        thread.start()

    def _on_idle_speak(self, event: Event):
        def _speak():
            with self.lock:
                self.memory.update_base_prompt(settings.SYSTEM_PROMPT)
            self._llm_speak(self.memory, pack=True, memories="")

        thread = threading.Thread(target=_speak)
        thread.start()

    def process_dialogue(self, user_message):
        # 防止并发处理
        if self._is_processing:
            logger.warning("正在处理中，忽略新输入")
            return

        try:
            self._is_processing = True

            # 重置工具调用计数
            self._tool_call_count = 0
            self._tool_results_buffer = []

            self.memory.add_message("user", user_message)
            history = json.dumps(self.memory.get_memory(), ensure_ascii=False)
            state = self.state_manager.prompt_injection
            messages = [
                "history:" + history,
                "state:" + state,
            ]
            road_result = self.hippocampus.load_memory(messages)
            memories = (
                json.dumps(road_result, ensure_ascii=False) if road_result else ""
            )

            # 构建带工具说明的 System Prompt（如果有注册工具）
            base_prompt = settings.SYSTEM_PROMPT
            if len(self.tool_registry) > 0:
                system_prompt = self.build_system_prompt_with_tools(base_prompt)
            else:
                system_prompt = base_prompt

            self.memory.update_base_prompt(system_prompt)

            self._llm_speak(self.memory, pack=True, memories=memories)
        finally:
            self._is_processing = False

    def _llm_speak(self, memory, pack: bool = False, memories: str = ""):
        # 在锁外准备数据，减少锁持有时间
        with self.lock:
            data = memory.get_full_messages()
            system_prompt = data[0]["content"]
            history = data[1:]

        # 构建消息（在锁外）
        if pack:
            formatted_history = ""
            for msg in history:
                role_label = (
                    "对方" if msg["role"] == "user" else f"{settings.CHARACTER_NAME}"
                )
                formatted_history += f"{role_label}: {msg['content']}\n"

            dynamic_context = ""
            if memories:
                dynamic_context = f"\n\n[脑海闪现的记忆]：\n{memories}\n"

            state_injection = self.state_manager.prompt_injection
            base_len = len(settings.SYSTEM_PROMPT)
            mem_len = max(0, len(system_prompt) - base_len)
            logger.info(
                f"[Prompt Breakdown] base={base_len} mem={mem_len}"
                f" history={len(formatted_history)} state={len(state_injection)}"
            )

            user_content = f"""以下是对话历史：
{formatted_history}{dynamic_context}{state_injection}
现在的时间是{self.event_bus.formatted_logical_now}，请参考并结合状态生成你将要说的下一句话"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        else:
            messages = data

        self.event_bus.publish(Event(name="llm.started", data=""))

        full_content = ""
        chunk_count = 0
        max_chunks = 10000

        try:
            stream_gen = self.llm_client.stream_chat(
                model_config=settings.LARGE_LLM,
                messages=messages,
            )

            for chunk in stream_gen:
                chunk_count += 1
                if chunk_count > max_chunks:
                    logger.warning("LLM 输出超过最大限制，截断")
                    break

                full_content += chunk
                self.event_bus.publish(Event(name="llm.chunk", data={"text": chunk}))

        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            error_msg = "[系统: AI 响应出现问题，请稍后再试]"
            self.event_bus.publish(Event(name="llm.chunk", data={"text": error_msg}))
            full_content = error_msg

        if full_content:
            # 修复可能不完整的标签
            full_content = validate_and_fix_llm_output(full_content)

            # 检查并处理工具调用
            tool_calls = self.extract_tool_calls(full_content)
            if tool_calls:
                logger.info(f"检测到工具调用: {[c['name'] for c in tool_calls]}")

                # 执行工具
                tool_results = self.execute_tool_calls(tool_calls)
                self._tool_results_buffer.extend(tool_results)

                # 格式化结果
                results_text = self.format_tool_results_for_prompt(tool_results)

                # 从输出中移除工具调用标签
                clean_content = self.remove_tool_calls(full_content)

                # 如果有工具结果且未超过最大调用次数，继续对话
                if (
                    tool_results
                    and self._tool_call_count < self.MAX_TOOL_CALLS_PER_TURN
                ):
                    tool_context = (
                        f"\n[工具执行结果]\n{results_text}\n请根据工具结果继续回复。"
                    )
                    self.memory.add_message("assistant", clean_content)
                    self.memory.add_message("user", tool_context)

                    # 递归调用
                    self._llm_speak(memory, pack=True, memories=memories)
                    return

                full_content = clean_content

            logger.info(f"LLM回复: {full_content[:100]}...")

            try:
                self.memory.add_message("assistant", full_content)
            except Exception as e:
                logger.error(f"保存消息失败: {e}")

            self.event_bus.publish(
                Event(name="llm.finished", data={"text": full_content})
            )
            self.event_bus.publish(
                Event(name="user_interaction", data=self.memory.get_memory())
            )
