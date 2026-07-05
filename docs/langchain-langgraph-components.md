# LangChain & LangGraph 常用组件详解

> 基于 Context7 最新文档整理，更新日期：2026-06-05

---

## 一、LangChain 核心组件

### 1. Chat Models（聊天模型）

聊天模型是一切 LLM 应用的入口，使用 `init_chat_model` 统一初始化，支持多种 provider：

```python
from langchain.chat_models import init_chat_model

# 格式： "provider:model-name"
model = init_chat_model("gpt-5.4-mini")                        # OpenAI
model = init_chat_model("claude-sonnet-4-6")                   # Anthropic
model = init_chat_model("google_genai:gemini-2.5-flash-lite")  # Google Gemini
model = init_chat_model("ollama:llama3")                       # 本地模型
model = init_chat_model("azure_openai:gpt-5.4")                # Azure
```

#### bind_tools — 绑定工具

```python
tool = {"type": "web_search"}
model_with_tools = model.bind_tools([tool])
response = model_with_tools.invoke("今天有什么正面新闻？")
```

#### with_structured_output — 强制结构化 JSON 输出

```python
from pydantic import BaseModel, Field

class Movie(BaseModel):
    title: str = Field(description="电影名称")
    year: int = Field(description="上映年份")
    director: str = Field(description="导演")
    rating: float = Field(description="评分")

structured_llm = llm.with_structured_output(Movie, method="json_schema")
response = structured_llm.invoke("Provide details about the movie Inception")
# response 是 Movie 实例
```

---

### 2. Prompts（提示词模板）

`ChatPromptTemplate` 是最核心的提示词组件，支持多种消息角色：

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant that translates {input_language} to {output_language}."),
    ("human", "{input}"),
])

# 使用 LCEL 管道操作符组合
chain = prompt | chat_model
chain.invoke({
    "input_language": "English",
    "output_language": "German",
    "input": "I love programming.",
})
```

**支持的消息角色：**
- `system` — 系统指令，定义 AI 的行为边界
- `human` — 用户消息
- `ai` — AI 的历史回复（用于多轮对话）
- `tool` — 工具调用结果

---

### 3. Tools（工具）

#### 方式1：`@tool` 装饰器（推荐）

```python
from langchain.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the weather for a given city.

    Args:
        city: The city to get weather for.
    """
    return f"It's always sunny in {city}!"
```

#### 方式2：Pydantic BaseModel（结构化输入）

```python
from pydantic import BaseModel, Field

class GetWeather(BaseModel):
    """Get the current weather in a given location"""
    location: str = Field(description="The city and state, e.g. San Francisco, CA")
```

#### 方式3：字典格式（兼容 OpenAI function calling）

```python
get_product_info = {
    "type": "function",
    "function": {
        "name": "get_product_info",
        "description": "Get information about a product by its id",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "number",
                    "description": "The unique identifier of the product",
                }
            },
            "required": ["product_id"],
        },
    },
}
```

---

### 4. Agents（智能体）

新版 LangChain 使用 `create_agent` 一站式创建：

```python
from langchain.agents import create_agent

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

agent = create_agent(
    model="claude-sonnet-4-6",           # LLM 模型
    tools=[get_weather],                 # 工具列表
    system_prompt="You are a helpful assistant",
)

# 调用
result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's the weather in San Francisco?"}]}
)
print(result["messages"][-1].content_blocks)
```

Agent 自动处理：工具调用循环 → 消息管理 → 错误处理。

---

### 5. Chains & LCEL（链与表达式语言）

LCEL 使用 `|` 管道操作符将 Runnable 组件串联：

```python
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer based only on the provided context."),
    ("human", "Question: {question}\n\nContext:\n{context}")
])

chain = (
    {"context": retriever | format_docs, "question": lambda x: x}
    | prompt
    | ChatOpenAI(model="gpt-4o-mini")
    | StrOutputParser()
)

answer = chain.invoke("What is the capital of France?")
```

**每个组件都是 `Runnable`，支持：**
- `.invoke()` — 单次调用
- `.stream()` — 流式输出
- `.batch()` — 批量处理

---

### 6. Retrievers & Vector Stores（检索器与向量存储）

```python
from langchain_core.vectorstores import InMemoryVectorStore

# 初始化向量存储（需要 embedding 模型）
vector_store = InMemoryVectorStore(embedding=SomeEmbeddingModel())

# 创建检索器
retriever = vector_store.as_retriever()

# 存入文档
vector_store.add_documents(documents)

# RAG 管道中使用
chain = {"context": retriever | format_docs, "question": lambda x: x} | prompt | llm
```

**常用检索策略：** 语义搜索、MMR（最大边际相关性）、相似度阈值过滤。

---

### 7. Memory（长期记忆 / Store）

用于跨会话持久化用户数据、偏好等：

```python
from langgraph.store.memory import InMemoryStore  # 开发用，生产用 DB-backed store

store = InMemoryStore()

# 写入数据
await store.put(["users"], "userPick_123", {"name": "John", "language": "English"})

# 在 Tool 中访问 store
@tool
async def save_user_info(user_info, runtime: ToolRuntime):
    user_id = runtime.context.user_id
    await runtime.store.put(["users"], user_id, user_info)
    return "Successfully saved user info."

agent = create_agent(
    model="claude-sonnet-4-6",
    tools=[save_user_info],
    context_schema=context_schema,
    store=store,
)
```

**Store 特性：** 命名空间化 key-value 存储，tool 通过 `runtime.store` 访问。

---

## 二、LangGraph 核心组件

LangGraph 是用于构建**有状态、多步骤 Agent 工作流**的底层编排框架。

### 架构概览

```
                    ┌─────────────────────────────┐
                    │        StateGraph(State)     │
                    │                             │
    START ──→ node_a ──→ node_b ──┬──→ node_d ──→ END
                         node_c ──┘
                         (并行)
                    │                             │
                    │  Checkpointer (状态快照)      │
                    │  Store (长期记忆)             │
                    └─────────────────────────────┘
```

---

### 1. StateGraph & State（状态图与状态定义）

`StateGraph` 是所有 LangGraph 应用的入口，State 定义图的共享数据结构：

```python
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

class State(TypedDict):
    messages: list                              # 普通字段（每次覆盖）
    aggregate: Annotated[list, operator.add]    # Reducer 字段（追加合并）
    foo: str
```

**字段更新规则：**
- **普通字段**：节点返回的 dict 直接**覆盖**旧值
- **`Annotated[type, reducer]`**：reducer 控制合并逻辑（如 `operator.add` = 追加）

---

### 2. Nodes & Edges（节点与边）

```python
builder = StateGraph(State)

# 添加节点（每个节点是一个函数，接收 State，返回部分更新）
builder.add_node("stepPick_1", node_functionPick_1)
builder.add_node("step_2", node_function_2)
builder.add_node("tools", ToolNode([search, calculator]))

# 普通边（固定路由）
builder.add_edge(START, "stepPick_1")
builder.add_edge("stepPick_1", "step_2")
builder.add_edge("step_2", END)

graph = builder.compile()
```

**节点函数签名：** `(state: State) -> dict`，返回的 dict 只包含需要更新的字段。

---

### 3. Conditional Edges（条件边 / 动态路由）

```python
class AgentState(TypedDict):
    messages: list
    current_tool: str
    retry_count: int

def should_continue(state):
    if state["retry_count"] > 3:
        return "end"
    elif state["current_tool"] == "search":
        return "process_search"
    else:
        return "call_llm"

builder.add_conditional_edges(
    "call_llm",
    should_continue,     # 路由函数
    {                     # 返回值到目标节点的映射
        "end": END,
        "process_search": "search_node",
        "call_llm": "call_llm_node",
    }
)
```

---

### 4. Command（命令式控制流）

`Command` 让节点内部**同时完成状态更新 + 路由决策**，无需显式边：

```python
from langgraph.types import Command

def node_a(state: State) -> Command[Literal["node_b", "node_c"]]:
    if state["foo"] == "bar":
        return Command(update={"foo": "baz"}, goto="node_b")
    else:
        return Command(update={"foo": "qux"}, goto="node_c")

builder.add_node("node_a", node_a)
builder.add_node("node_b", node_b)
builder.add_node("node_c", node_c)
builder.add_edge(START, "node_a")
# 不需要 node_a → node_b / node_a → node_c 的边！Command 已处理路由
```

**Command vs Conditional Edge 选择：**
- `Command`：路由逻辑紧耦合在节点内，适合简单分支
- `Conditional Edge`：路由逻辑与节点解耦，适合复杂决策树、可视化

---

### 5. 并行执行 & Send API

#### 固定并行（拓扑驱动）

从同一节点出发的多条边自动并行：

```python
# b 和 c 在 a 之后并行执行
builder.add_edge("a", "b")
builder.add_edge("a", "c")
builder.add_edge("b", "d")
builder.add_edge("c", "d")  # d 等待 b 和 c 都完成（汇合点）
```

#### 动态并行（Send API / Map-Reduce）

```python
from langgraph.types import Send

class OverallState(TypedDict):
    topic: str
    subjects: list[str]
    jokes: Annotated[list[str], operator.add]  # reducer 自动聚合
    best_selected_joke: str

def continue_to_jokes(state: OverallState):
    # 为每个 subject 动态生成并行任务，每个带独立 state
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

builder.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])
builder.add_edge("generate_joke", "best_joke")
```

**Send API 特点：** 每个 fan-out 任务收到独立的 state 副本，通过 reducer 聚合结果。

---

### 6. Checkpointing（检查点 / 状态持久化）

让图支持暂停、恢复、重放、时间旅行调试：

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()  # 开发用；生产用 PostgresSaver / SqliteSaver
graph = builder.compile(checkpointer=checkpointer)

# thread_id 区分不同会话
config = {"configurable": {"thread_id": "1"}}
graph.invoke({"messages": [{"role": "user", "content": "hi! I'm Bob"}]}, config)

# 第二次调用相同 thread_id，自动加载历史状态
graph.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

**每个 super-step 完成后自动保存检查点**，支持断点续传。

---

### 7. Interrupt & Human-in-the-Loop（中断与人工审批）

```python
from langgraph.types import Command, interrupt

class ApprovalState(TypedDict):
    action_details: str
    status: Optional[Literal["pending", "approved", "rejected"]]

def approval_node(state: ApprovalState) -> Command[Literal["proceed", "cancel"]]:
    # 中断执行，向外暴露决策信息
    decision = interrupt({
        "question": "Approve this action?",
        "details": state["action_details"],
    })
    # 恢复后根据决策路由
    return Command(goto="proceed" if decision else "cancel")

# --- 首次调用：在 interrupt 处暂停 ---
graph.stream_events(
    {"action_details": "Transfer $500", "status": "pending"},
    config=config,
    version="v3",
)
# 检查中断值
print(initial.interrupts)  # -> (Interrupt(value={'question': ..., 'details': ...}),)

# --- 恢复执行 ---
graph.invoke(Command(resume=True), config=config)   # 批准 → 路由到 proceed
graph.invoke(Command(resume=False), config=config)  # 拒绝 → 路由到 cancel
```

---

### 8. ToolNode（工具执行节点）

LangGraph 预置的工具节点，自动处理 LLM 返回的 tool_calls：

```python
from langgraph.prebuilt import ToolNode

@tool
def search(query: str) -> str:
    """Search for information."""
    return f"Results for: {query}"

@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))

builder = StateGraph(MessagesState)
builder.add_node("tools", ToolNode([search, calculator]))
# ... 配合 LLM 节点 + 条件边实现 Agent 循环
```

**Agent 循环模式：** LLM 节点 → 条件边判断是否有 tool_calls → 执行 ToolNode → 回到 LLM 节点。

---

### 9. Subgraphs（子图 / 嵌套图）

将一个编译好的图作为另一个图的节点：

```python
# 定义子图
subgraph = StateGraph(SubState).add_node(...).add_edge(...).compile()

# 嵌入父图
builder = StateGraph(ParentState)
builder.add_node("subgraph", subgraph)  # 子图作为一个整体节点
builder.add_edge(START, "subgraph")
```

通过 `Command(graph=Command.PARENT)` 从子图导航回父图节点。

---

### 10. Retry Policy（重试策略）

```python
from langgraph.types import RetryPolicy

builder.add_node(
    "search_documentation",
    search_documentation,
    retry_policy=RetryPolicy(max_attempts=3)
)
```

---

## 三、LangChain vs LangGraph 对比

| 维度 | LangChain | LangGraph |
|------|-----------|-----------|
| **定位** | 高层 Agent 框架 | 底层编排运行时 |
| **入口** | `create_agent()` | `StateGraph(State)` |
| **控制流** | 模型自主决策（隐式） | 显式图：节点 + 边 |
| **状态** | 消息列表 | TypedDict + Reducer |
| **持久化** | Store（长期记忆） | Checkpointer（状态快照） |
| **人机协作** | 无原生支持 | `interrupt()` + `Command(resume=...)` |
| **并行策略** | 工具并发调用 | 图拓扑并行 + Send 动态 fan-out |
| **适用场景** | 简单对话 Agent | 复杂多步骤工作流 |

---

## 四、两者关系

**LangChain 的 `create_agent` 底层就是用 LangGraph 构建的图。** 两者的典型配合模式：

- 用 **LangGraph** 定义工作流骨架：多步骤、分支、并行、人工审批
- 用 **LangChain** 填充节点内容：工具定义、提示词模板、结构化输出、模型调用

```
LangGraph 工作流
├── node: classify_intent  ← LangChain structured output
├── node: search           ← LangChain retriever + vector store
├── node: call_llm          ← LangChain chat model + prompt template
├── node: tools             ← LangGraph ToolNode(LangChain tools)
└── node: human_approval    ← LangGraph interrupt
```

---

## 五、与 Pick 项目的关联

Pick 项目（`agent-service/`）的 AI Shopping Guide Agent 可以直接使用这些组件：

| 需求 | 推荐组件 |
|------|----------|
| 意图路由（闲聊 vs 推荐） | LangGraph Conditional Edges + LangChain `with_structured_output` |
| 双路语义搜索（Shop + Blog） | LangChain Vector Store + Retriever |
| 标量过滤（区域、类型） | LangChain Retriever `search_kwargs` filter |
| 多轮对话 | LangGraph Checkpointer（`thread_id`） |
| 工具调用（搜索、下单、查券） | `@tool` 装饰器 + ToolNode |
| SSE 流式输出 | LangGraph `stream_events` / `astream_events` |
| 人工确认（下单前确认） | LangGraph `interrupt` + `Command(resume=...)` |
