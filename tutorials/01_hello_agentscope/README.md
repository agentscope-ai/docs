# Tutorial 01: Hello AgentScope — 你的第一个 Agent

> **什么时候需要这个？** 第一次接触 AgentScope 2.0，想最快搞清楚"用几行代码创建一个 Agent 并跟它对话"到底涉及哪些组件。后面所有章节都从这里的最小 Agent 出发。

## 你将学到

- AgentScope 2.0 的设计哲学与核心四要素
- 如何创建和配置一个最基本的 Agent
- `reply()` 与 `reply_stream()` 两种交互方式
- 如何切换不同的模型提供商

## 前置要求

- Python 3.11+
- 安装 AgentScope：`pip install agentscope==2.0.4`
- 至少一个 LLM API Key（DashScope / OpenAI / Ollama 等）

## 核心概念

### AgentScope 2.0 设计哲学

AgentScope 2.0 的核心理念是**利用模型能力，而非约束模型**。

与许多框架用严格的 prompt 和固定编排来"控制"模型不同，AgentScope 2.0 信任模型的推理和工具使用能力，提供最少必要的抽象，让模型自由发挥。

### 核心四要素

创建一个 Agent 需要四个要素：

```
Credential → Model → Toolkit → Agent
(认证凭据)  (LLM模型)  (工具集)   (智能体)
```

1. **Credential** — 管理 API 密钥等认证信息
2. **Model** — 指定使用哪个 LLM（如 qwen-plus, gpt-4o）
3. **Toolkit** — 注册 Agent 可以使用的工具（本教程暂不添加）
4. **Agent** — 将上述组件组合起来的智能体

### 异步编程

AgentScope 2.0 是**全异步**的。所有 Agent 方法都需要使用 `async/await` 语法：

```python
import asyncio

async def main():
    result = await agent.reply(msg)  # await 等待异步操作完成

asyncio.run(main())  # 启动异步事件循环
```

### 两种交互方式

| 方法 | 返回值 | 适用场景 |
|------|--------|----------|
| `agent.reply(msg)` | 最终的 `Msg` 对象 | 后台自动化，不需要实时输出 |
| `agent.reply_stream(msg)` | `AgentEvent` 事件流 | 交互式 UI，需要实时显示 |

### 消息类型

AgentScope 2.0 提供了三种快捷消息工厂函数：

```python
from agentscope.message import UserMsg, AssistantMsg, SystemMsg

# 用户消息
msg = UserMsg(name="user", content="你好")

# 助手消息
msg = AssistantMsg(name="agent", content="你好！有什么可以帮你的？")

# 系统消息
msg = SystemMsg(name="system", content="你是一个数据分析助手。")
```

## 示例：DataMuse 的诞生

本期我们创建 **DataMuse** 的最初版本 —— 一个能进行基本对话的数据分析助手。

### 步骤 1：创建最简 Agent

```python
from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel

agent = Agent(
    name="DataMuse",
    system_prompt="You are DataMuse, a helpful data analysis assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
    ),
)
```

### 步骤 2：使用 reply() 进行对话

```python
from agentscope.message import UserMsg

msg = UserMsg(name="user", content="What is the best chart type for showing trends over time?")
result = await agent.reply(msg)
print(result.get_text_content())
```

`reply()` 会阻塞直到 Agent 完成回复，然后返回完整的 `Msg` 对象。

### 步骤 3：使用 reply_stream() 进行流式对话

```python
from agentscope.event import EventType

async for event in agent.reply_stream(msg):
    match event.type:
        case EventType.TEXT_BLOCK_DELTA:
            print(event.delta, end="", flush=True)
        case EventType.REPLY_END:
            print("\n[Done]")
```

`reply_stream()` 返回一个异步迭代器，逐步产出事件。你可以实时处理每个事件（如打印文本片段）。

### 步骤 4：切换模型提供商

只需更换 Credential 和 Model 类即可切换提供商：

```python
# OpenAI
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel

model = OpenAIChatModel(
    credential=OpenAICredential(api_key=os.environ["OPENAI_API_KEY"]),
    model="gpt-4o",
)

# Ollama (本地模型)
from agentscope.credential import OllamaCredential
from agentscope.model import OllamaChatModel

model = OllamaChatModel(
    credential=OllamaCredential(),
    model="qwen3:8b",
)
```

## 运行示例

```bash
# 默认用 DashScope
export DASHSCOPE_API_KEY="your-key-here"

# 运行
cd tutorials/01_hello_agentscope
python main.py
```

> 想用 OpenAI？按 [main.py](main.py) 顶部 docstring 的提示替换 `main()` 里的 4 行 model 配置即可。后续章节会用一个 `create_model()` helper 自动切换 provider，这里先保持最简结构。

## 进一步探索

- 尝试修改 `system_prompt`，让 DataMuse 具有不同的个性
- 尝试使用不同的模型提供商，比较回复质量
- 观察 `reply()` 返回的 `Msg` 对象有哪些字段

## 下一期预告

**Tutorial 02: Message & Event** — 深入理解 AgentScope 的消息和事件系统，掌握 Agent 通信的核心协议。
