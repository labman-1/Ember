import json
import asyncio
import time
import logging
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.event_bus import EventBus, Event
from core.heartbeat import Heartbeat
from persona.state_manager import StateManager
from brain.core import Brain
from brain.tts import TTSManager
from memory.short_term import ShortTermMemory
from config.settings import settings
from memory.episodic_memory import EpisodicMemory
from memory.memory_process import Hippocampus
from memory.db_memory import DBMemory
from memory.entity_extraction import EntityExtractionMemory
from config.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)


class ConnectionManager:
    """Async connection manager"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Pure async broadcast"""
        if not self.active_connections:
            return

        payload = json.dumps(message, ensure_ascii=False)
        tasks = []
        for connection in self.active_connections:
            tasks.append(self._safe_send(connection, payload))
        await asyncio.gather(*tasks)

    async def _safe_send(self, websocket: WebSocket, payload: str):
        try:
            await websocket.send_text(payload)
        except Exception:
            self.disconnect(websocket)


class EmberServer:
    def __init__(self):
        self.app = FastAPI()
        self.event_bus = EventBus()
        self.manager = ConnectionManager()
        self.loop = None
        self.current_ai_msg_id = None  # Track ongoing AI message ID
        self.current_full_text = ""  # Track full text for TTS
        self._tts_semaphore = asyncio.Semaphore(3)  # 限制并发 TTS 数量为 3

        # Initialize components
        self.heartbeat = Heartbeat(self.event_bus, interval=settings.HEARTBEAT_INTERVAL)
        self.memory = ShortTermMemory(
            base_prompt=settings.SYSTEM_PROMPT,
            max_memory_size=settings.CONTEXT_WINDOW_SIZE,
        )
        self.episodic_memory = EpisodicMemory(self.event_bus)
        self.hippocampus = Hippocampus(self.event_bus)
        self.db_memory = DBMemory(self.event_bus)
        self.state_manager = StateManager(self.event_bus, self.hippocampus, self.memory)
        self.entity_memory = EntityExtractionMemory(self.event_bus)
        self.brain = Brain(
            self.event_bus, self.state_manager, self.memory, self.hippocampus
        )
        self.tts_manager = TTSManager(voice="zh-CN-XiaoxiaoNeural")

        self._setup_middleware()
        self._setup_routes()
        self._setup_event_handlers()

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        @self.app.on_event("startup")
        async def startup_event():
            self.loop = asyncio.get_running_loop()
            logger.info(f">>> [DEBUG] Asyncio loop initialized: {self.loop}")

        # Mount audio directory
        audio_dir = "data/audio"
        os.makedirs(audio_dir, exist_ok=True)
        self.app.mount("/audio", StaticFiles(directory=audio_dir), name="audio")

        @self.app.get("/config")
        async def get_config():
            return {
                "character_name": "Ember",
                "display_name": settings.CHARACTER_NAME,
                "state": self.state_manager.current_state,
                "logical_time": self.event_bus.formatted_logical_now,
                "is_thinking": self.state_manager.is_thinking,
            }

        @self.app.get("/history")
        async def get_history(limit: int = 20, before: int = None):
            try:
                return self.db_memory.get_history(limit=limit, before_timestamp=before)
            except Exception as e:
                logger.error(f"Failed to fetch history: {e}")
                return []

        @self.app.websocket("/ws/chat")
        async def websocket_endpoint(websocket: WebSocket):
            await self.manager.connect(websocket)
            last_ping = time.time()
            ping_interval = 30  # 30秒发送一次心跳

            try:
                while True:
                    # 检查是否需要发送心跳
                    if time.time() - last_ping > ping_interval:
                        try:
                            await websocket.send_text(json.dumps({"type": "ping"}))
                            last_ping = time.time()
                        except Exception:
                            break  # 发送失败，连接已断开

                    # 使用超时接收，避免阻塞
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_text(), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        continue  # 超时继续循环，检查心跳

                    message = json.loads(data)
                    msg_type = message.get("type")

                    # 处理心跳 pong
                    if msg_type == "pong":
                        continue

                    # 严格拦截 TTS 请求，防止进入消息广播逻辑
                    if msg_type == "tts_request":
                        text = message.get("content")
                        if text:
                            logger.info(f"收到手动 TTS 请求: {text[:20]}...")
                            asyncio.create_task(self._process_tts(text))
                        continue  # 必须 continue，跳过下方的 user_input 处理

                    user_input = message.get("content")
                    if user_input:
                        ts = int(self.event_bus.logical_now * 1000)
                        await self.manager.broadcast(
                            {
                                "type": "message",
                                "sender": "user",
                                "content": user_input,
                                "timestamp": ts,
                                "id": ts,
                            }
                        )
                        self.event_bus.publish(
                            Event(name="user.input", data={"text": user_input})
                        )
            except WebSocketDisconnect:
                self.manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WS loop exception: {e}")
                self.manager.disconnect(websocket)
            finally:
                # 确保连接被移除
                self.manager.disconnect(websocket)

    def _setup_event_handlers(self):
        self.event_bus.subscribe("llm.started", self._on_ai_start_internal)
        self.event_bus.subscribe("llm.chunk", self._on_ai_chunk_internal)
        self.event_bus.subscribe("llm.finished", self._on_ai_finished_internal)
        self.event_bus.subscribe(
            "state.update",
            lambda e: self.safe_broadcast(
                {"type": "state_update", "state": e.data.get("new_state", {})}
            ),
        )

    def _on_ai_start_internal(self, event):
        self.current_ai_msg_id = int(self.event_bus.logical_now * 1000)
        self.current_full_text = ""
        self.safe_broadcast(
            {
                "type": "message",
                "sender": "ai",
                "content": "",
                "mode": "start",
                "timestamp": self.current_ai_msg_id,
                "id": self.current_ai_msg_id,
            }
        )

    def _on_ai_chunk_internal(self, event):
        if self.current_ai_msg_id:
            chunk = event.data.get("text", "")
            self.current_full_text += chunk
            self.safe_broadcast(
                {
                    "type": "message",
                    "sender": "ai",
                    "content": chunk,
                    "mode": "append",
                    "id": self.current_ai_msg_id,
                }
            )

    def _on_ai_finished_internal(self, event):
        logger.info(
            f"LLM 完成输出，准备合成 TTS... (内容长度: {len(self.current_full_text)})"
        )
        if self.current_full_text and self.current_full_text.strip():
            # 只有开启了某种自动逻辑或当前处于 AI 回复流中才自动合成
            if self.loop:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        self._process_tts(self.current_full_text)
                    )
                )

        self.safe_broadcast({"type": "llm.done"})

    async def _process_tts(self, text):
        """处理 TTS，限制并发数量"""
        if not text or not text.strip():
            return

        # 使用信号量限制并发
        async with self._tts_semaphore:
            try:
                # 限制文本长度，防止超长文本导致性能问题
                max_tts_length = 500
                if len(text) > max_tts_length:
                    text = text[:max_tts_length] + "..."
                    logger.warning(f"TTS 文本过长，已截断至 {max_tts_length} 字符")

                base64_audio = await self.tts_manager.generate_base64(text)
                logger.info(f"广播 Base64 TTS 音频 (长度: {len(base64_audio)})")
                await self.manager.broadcast(
                    {"type": "audio", "audio_base64": base64_audio}
                )
            except Exception as e:
                logger.error(f"TTS 广播错误: {e}")

    def safe_broadcast(self, message: dict):
        """线程安全的广播方法"""
        if self.loop and self.loop.is_running():
            try:
                # 使用 call_soon_threadsafe 安排协程创建
                def create_task():
                    try:
                        asyncio.create_task(self.manager.broadcast(message))
                    except Exception as e:
                        logger.error(f"创建广播任务失败: {e}")

                self.loop.call_soon_threadsafe(create_task)
            except Exception as e:
                logger.error(f"safe_broadcast 失败: {e}")

    def start(self):
        self.heartbeat.start()
        import uvicorn

        logger.info(">>> Ember Server starting...")
        uvicorn.run(self.app, host="0.0.0.0", port=8000, loop="asyncio")


if __name__ == "__main__":
    server = EmberServer()
    server.start()
