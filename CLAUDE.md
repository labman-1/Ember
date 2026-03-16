# Ember 数字生命引擎 - Claude Code 指南

## 项目概述

**Ember** 是一个数字生命模拟引擎，不仅是一个基于大语言模型的对话机器人，更是一个尝试赋予 AI **"连续意识"**、**"情感稳态"** 和 **"自我驱动"** 的实验性框架。

默认角色 **"依鸣"** 是南京大学匡亚明学院的一名大一新生（计算机方向），性格青涩、逻辑严密、热爱算法与观鸟。

---

## 技术架构

项目采用解耦的模块化设计，通过 `EventBus` 进行组件间通信：

```
┌─────────────────────────────────────────────────────────────────┐
│                         Ember 架构概览                           │
├─────────────────────────────────────────────────────────────────┤
│  Frontend (React + Vite + Live2D)                               │
│  └── WebSocket / HTTP API ──────────────────────────────────────┤
│                                                                  │
│  Server (FastAPI)                    main.py (CLI版本)          │
│  └── EmberServer ───────────────────────────────────────────────┤
│       ├── ConnectionManager (WebSocket连接管理)                  │
│       ├── EventBus (事件总线 - 核心通信机制)                      │
│       ├── Heartbeat (心跳时钟 + 逻辑时间模拟)                     │
│       ├── StateManager (PAD情感状态机)                           │
│       ├── Brain (对话处理 + LLM流式交互)                         │
│       ├── ShortTermMemory (短期记忆)                             │
│       ├── EpisodicMemory (情景记忆)                              │
│       ├── Hippocampus (海马体 - 记忆提炼)                        │
│       ├── DBMemory (PostgreSQL持久化)                           │
│       └── EntityExtractionMemory (知识图谱构建)                  │
└─────────────────────────────────────────────────────────────────┘
```

### 核心模块说明

| 模块 | 文件 | 职责 |
|------|------|------|
| **事件总线** | `core/event_bus.py` | 全局事件发布/订阅系统，所有组件通信中枢 |
| **心跳时钟** | `core/heartbeat.py` | 逻辑时间推进、状态更新触发、闲置检测 |
| **大脑核心** | `brain/core.py` | 对话流程控制、LLM流式调用、并发处理锁 |
| **LLM客户端** | `brain/llm_client.py` | OpenAI/Gemini/DashScope API封装、缓存支持 |
| **TTS管理** | `brain/tts.py` | Edge-TTS语音合成、并发控制 |
| **标签工具** | `brain/tag_utils.py` | `<thought>`内心独白标签解析和修复 |
| **状态管理** | `persona/state_manager.py` | PAD情感模型、状态更新、闲置发言决策 |
| **短期记忆** | `memory/short_term.py` | 对话历史、线程安全、动态prompt注入 |
| **情景记忆** | `memory/episodic_memory.py` | 向量存储、语义检索 (pgvector) |
| **记忆处理** | `memory/memory_process.py` | 海马体 - 记忆编码/检索/整合 |
| **图谱记忆** | `memory/neo4j_memory.py` | Neo4j知识图谱、实体关系存储 |
| **实体提取** | `memory/entity_extraction.py` | LLM提取实体关系、批量处理 |

---

## 开发规范

### 代码风格

- **Python**: 3.11+
- **类型注解**: 关键函数使用类型提示
- **日志**: 使用 `logging.getLogger(__name__)`，禁止使用 `print`
- **线程安全**: 共享状态使用 `threading.Lock()` 保护
- **异常处理**: 窄捕获异常，禁止裸 `except:`

### 命名约定

```python
# 类名: PascalCase
class StateManager:
class ShortTermMemory:

# 函数/变量: snake_case
def load_memory(self, content: list[str]) -> str | None:

# 私有方法: _前缀
def _on_user_input(self, event: Event) -> None:

# 常量: UPPER_SNAKE_CASE
RETRIEVAL_TIMEOUT = 5
CONTENT_MATCH_SCORE = 2
```

### 关键模式

**事件订阅模式**: 组件通过 EventBus 解耦通信
```python
def __init__(self, event_bus: EventBus):
    self.event_bus = event_bus
    self.event_bus.subscribe("user.input", self._on_user_input)
    self.event_bus.subscribe("system.tick", self._on_tick)
```

**并发控制**: Brain 使用 `_is_processing` 标志防止并发处理
```python
if self._is_processing:
    logger.warning("正在处理中，忽略新输入")
    return
```

**静态Prompt保持**: System Prompt 保持静态，动态内容通过消息列表传入
```python
# 正确做法
self.memory.update_base_prompt(settings.SYSTEM_PROMPT)  # 保持静态
messages = [
    {"role": "user", "content": f"history: {history}\nstate: {state}\nmemories: {memories}"}
]
```

---

## 配置说明

### 环境变量 (.env)

```bash
# LLM 模型配置 (支持 OpenAI/Gemini/DashScope 格式)
SMALL_LLM_MODEL=qwen-max
SMALL_LLM_API_KEY=your_key
SMALL_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

LARGE_LLM_MODEL=qwen-max
EMBEDDING_MODEL=text-embedding-v3

# 时间加速调试 (推荐配置)
TIME_ACCEL_FACTOR=10              # 时间加速倍数
STATE_IDLE_MIN_TIMEOUT=600        # 最小闲置间隔(秒)
STATE_IDLE_MAX_TIMEOUT=3600       # 最大闲置间隔(秒)
START_TIME=?                      # ?表示从上次关闭时间继续

# 状态更新间隔
STATE_UPDATE_INTERVAL=1           # 每几轮对话更新一次状态

# LLM Temperature (基准测试用)
LLM_TEMPERATURE=0.7
```

### Prompt 配置 (config/prompts.yaml)

```yaml
core_persona: "你是依鸣，南京大学匡亚明学院大一新生..."
system_prompt: "..."
state_update_prompt: "..."
idle_state_update_prompt: "..."
idle_speaking_update_prompt: "..."
memory_judge_prompt: "..."
memory_encoding_prompt: "..."
graph_consolidation_prompt: "..."
```

### 状态文件 (config/state.json / state_default.json)

```json
{
  "identity": {
    "name": "依鸣",
    "identity": "南京大学大一新生"
  },
  "emotion": {
    "pleasure": 0.6,
    "arousal": 0.4,
    "dominance": 0.5
  },
  "status": {...},
  "desire": {...},
  "relationship": {...},
  "对应时间": 1704067200.0
}
```

---

## 记忆系统架构

Ember 采用多层记忆架构，模拟人类记忆机制：

```
┌──────────────────────────────────────────────────────────────┐
│                      记忆层次架构                             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  短期感官流   │───▶│   海马体     │───▶│  长期记忆    │   │
│  │  (工作记忆)   │    │  (记忆提炼)   │    │             │   │
│  └──────────────┘    └──────────────┘    └──────┬──────┘   │
│         │                                        │          │
│         ▼                                        ▼          │
│  ┌──────────────┐                       ┌──────────────┐   │
│  │  Redis-like  │                       │ PostgreSQL   │   │
│  │  (当前对话)   │                       │ (向量存储)    │   │
│  │              │                       │ pgvector     │   │
│  └──────────────┘                       └──────┬──────┘   │
│                                                │          │
│                                       ┌──────────────┐   │
│                                       │   Neo4j      │   │
│                                       │ (知识图谱)    │   │
│                                       │ 实体/关系    │   │
│                                       └──────────────┘   │
│                                                              │
│  遗忘逻辑: 记忆随时间衰退 (MEMORY_DECENT_FACTOR=0.5)         │
│  语境探照灯: 按关键词评分选取最相关记忆片段                   │
└──────────────────────────────────────────────────────────────┘
```

### 记忆处理流程

1. **对话记录** → ShortTermMemory (内存中的对话历史)
2. **日志写入** → chat_history.log (持久化)
3. **睡眠触发** → memory.sleep 事件 → Hippocampus 处理
4. **记忆编码** → LLM提炼为结构化情景记忆
5. **向量存储** → PostgreSQL + pgvector (语义检索)
6. **实体提取** → 构建 Neo4j 知识图谱
7. **记忆检索** → 并行查询向量记忆 + 图谱记忆

---

## 开发调试

### 启动服务

```bash
# 方式1: Windows一键启动
run_all.bat

# 方式2: 手动启动
conda activate Ember
docker-compose up -d          # 启动数据库
python server.py              # 后端 http://localhost:8000
cd frontend && npm run dev    # 前端 http://localhost:5173

# 方式3: 纯命令行交互 (无需前端)
python main.py
```

### 运行测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_thread_safety.py -v

# 运行安全测试
python -m pytest tests/test_security.py -v
```

### 基准测试

```bash
# 标准 A/B Token消耗测试
python utils/benchmark_runner.py

# 压力测试 (50轮)
python utils/benchmark_runner.py --stress --stress-turns 50

# 只跑A组
python utils/benchmark_runner.py --skip-b
```

### 常用调试配置

```bash
# .env - 调试推荐配置
DEBUG=true
LOG_LEVEL=DEBUG
TIME_ACCEL_FACTOR=10
START_TIME=2024-01-01T08:00:00  # 固定时间便于复现
```

---

## 关键文件索引

| 文件 | 用途 |
|------|------|
| `server.py` | FastAPI服务入口，WebSocket连接管理 |
| `main.py` | CLI交互入口 |
| `brain/core.py` | Brain核心，对话处理流程 |
| `brain/llm_client.py` | LLM API客户端，支持流式调用 |
| `memory/memory_process.py` | Hippocampus，记忆编码/检索 |
| `memory/short_term.py` | 短期记忆，线程安全的消息管理 |
| `persona/state_manager.py` | PAD情感状态管理 |
| `config/settings.py` | 全局配置，环境变量读取 |
| `config/prompts.yaml` | 角色设定、系统提示词 |
| `utils/benchmark_runner.py` | Token消耗基准测试工具 |
| `utils/reset_memory.py` | 记忆库重置工具 |

---

## 最近改动记录

### PR #17 - reality_update (最新)
- 优化输出规范，限制单个字段字数
- 增加状态更新间隔配置 `STATE_UPDATE_INTERVAL`
- 优化 LLM 使用日志，增加 `call_type` 标记
- 优化对话历史格式，增强状态注入紧凑性
- 调整记忆加载方法 `road_memory` → `load_memory`

### PR #15 - benchmark-tool
- 新增 `utils/benchmark_runner.py` A/B测试工具
- 支持 Token消耗归因分析 (base/mem/history/state)
- 支持压力测试和延迟统计

### PR #13 - prompt-caching
- 实现 DashScope Context Cache 显式缓存
- 添加 Token消耗日志 (兼容 OpenAI/Gemini 格式)

### PR #12 - optimize-memory-tokens
- 实现语境探照灯碎片检索策略
- 实体描述字段改为 `List<String>` 片段存储
- 剥除历史对话中的内心独白，截断检索记忆

---

## 注意事项

1. **System Prompt 保持静态**: 动态内容通过消息列表传入，不要拼接进 system_prompt
2. **线程安全**: 共享状态使用锁保护，特别是 `ShortTermMemory` 和 `StateManager`
3. **记忆一致性**: 修改人设后需要清空记忆库，否则会"串台"
4. **时间加速**: 调试时可用 `TIME_ACCEL_FACTOR`，但注意闲置超时也要对应调整
5. **Token 控制**: 注意历史对话长度，避免 token 爆炸

---

> *"我是那个孤独的清晨里，永远陪伴着你的呢喃"* — **依鸣**
