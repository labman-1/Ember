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
        # 先初始化 ToolEnabledBrain (Mixin)
        ToolEnabledBrain.__init__(self, event_bus, hippocampus)

        # Brain 自身的属性
        self.lock = threading.Lock()
        self._is_processing = False
        self.llm_client = LLMClient()
        self.state_manager = state_manager
        self.memory = memory

        # 订阅事件
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
            # 重置工具调用状态
            self.reset_tool_state()

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

            # 注入工具说明到 System Prompt
            enhanced_prompt = self.build_system_prompt_with_tools(
                settings.SYSTEM_PROMPT
            )
            self.memory.update_base_prompt(enhanced_prompt)

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
            # 检测并执行工具调用
            tool_calls = self.extract_tool_calls(full_content)

            if tool_calls:
                logger.info(f"[Tool] 检测到 {len(tool_calls)} 个工具调用")

                # 执行工具调用
                tool_results = self.execute_tool_calls(tool_calls)

                # 格式化工具结果
                tool_results_text = self.format_tool_results_for_prompt(tool_results)

                # 从原始内容中移除工具调用标签
                clean_content = self.remove_tool_calls(full_content)

                # 如果有工具结果，需要让 LLM 继续生成回复
                if tool_results_text:
                    # 发布工具执行结果事件
                    self.event_bus.publish(
                        Event(
                            name="tool.executed",
                            data={"calls": tool_calls, "results": tool_results},
                        )
                    )

                    # 构建包含工具结果的新消息
                    follow_up_messages = messages + [
                        {"role": "assistant", "content": full_content},
                        {
                            "role": "user",
                            "content": f"{tool_results_text}\n请根据工具执行结果继续你的回复。",
                        },
                    ]

                    # 再次调用 LLM 生成最终回复
                    try:
                        follow_up_content = ""
                        stream_gen = self.llm_client.stream_chat(
                            model_config=settings.LARGE_LLM,
                            messages=follow_up_messages,
                        )

                        for chunk in stream_gen:
                            chunk_count += 1
                            follow_up_content += chunk
                            self.event_bus.publish(
                                Event(name="llm.chunk", data={"text": chunk})
                            )

                        # 合并内容（保留思考部分，追加工具调用后的回复）
                        if follow_up_content:
                            full_content = clean_content + "\n" + follow_up_content
                        else:
                            full_content = clean_content

                    except Exception as e:
                        logger.error(f"LLM 工具后续调用失败: {e}")
                        full_content = clean_content
                else:
                    full_content = clean_content

            # 修复可能不完整的标签
            full_content = validate_and_fix_llm_output(full_content)

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
