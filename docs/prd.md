# PRD：本地生活 AI 智能导购 Agent

## 1. 项目定位

在现有 Pick（大众点评风格本地生活平台）基础上，集成 AI Agent 能力，将传统"信息展示型浏览"升级为"交互型智能导购"。用户通过自然语言对话获取个性化店铺推荐，实现从"随便看看"到"消费决策"的深度连接。

**核心原则**：先跑通最小闭环，再逐步增强。评审重点关注端到端链路的完整性。

**核心目标**：提高转化率，提高用户下单率。

---

## 2. 技术架构总览

```
┌──────────────┐   HTTP SSE        ┌──────────────┐   HTTP SSE      ┌─────────────────┐
│   Vue 3 前端  │ ◄─────────────── │  Java 后端    │ ◄───────────── │  Python AI 服务  │
│              │  /api/chat/stream │  (Spring Boot) │  (stream 透传)  │  (FastAPI)      │
│ /ai-assistant│                   │              │                 │                 │
│  独立对话页   │                   │ WebClient     │                 │ LangGraph Agent │
└──────────────┘                   │ (streaming)   │                 │ LangChain RAG   │
                                   └──────┬────────┘                 └───────┬─────────┤
                                          │                                  │
                                          │ MySQL                            ├── Milvus
                                          │                                  ├── Redis
                                          │                                  └── LLM (Doubao)
```

### 2.1 职责边界

| 层 | 职责 |
|---|---|
| **Vue 3 前端** | 对话 UI、SSE 流式渲染（fetch + ReadableStream）、店铺卡片+Modal、sa-token 鉴权 |
| **Java 后端** | 业务数据管理（店铺/券/Blog CRUD）、用户认证、HTTP 流式透传（WebClient）、数据同步只读端点 |
| **Python AI 服务** | LLM 调用、RAG 检索、对话上下文管理、意图识别、SSE 流式回复生成 |
| **Milvus** | 向量存储与语义检索 + 标量过滤，HNSW 索引 |
| **Redis** | 对话 session 历史存储（session_id 为 key，TTL 30min，每次消息续期） |
| **MySQL** | 业务主数据（店铺、券、Blog），复用现有表结构 |

### 2.2 模块结构

```
D:\Pick\
├── core-service/                   ← 现有 Spring Boot（WebClient 流式转发 + 同步端点）
├── python-ai-service/              ← 新建 Python 服务
│   ├── pyproject.toml
│   ├── src/
│   │   ├── agent/                  ← LangGraph Agent 图
│   │   ├── ingestion/              ← 数据摄入与增量同步
│   │   ├── milvus/                 ← Milvus 连接管理
│   │   └── main.py                 ← FastAPI + SSE streaming
├── vue3/                           ← 现有前端（新增 /ai-assistant 路由，TabBar + 搜索框入口）
├── sql/                            ← 现有 DDL + 新增迁移脚本
└── docs/                           ← 文档
```

---

## 3. 技术选型

| 层次 | 选型 | 说明 |
|---|---|---|
| Python 框架 | FastAPI | HTTP 端点 + SSE streaming |
| Agent 编排 | LangGraph | 多步骤 Agent 图、对话状态管理 |
| RAG 组件 | LangChain | Milvus connector、embedding、prompt template |
| 通信协议 | HTTP/SSE | Java ↔ Python 均走 HTTP，Java 用 WebClient 流式透传 |
| 向量数据库 | Milvus（Docker 单机） | 语义检索 + 标量过滤，HNSW 索引 |
| Embedding | Doubao-embedding-vision | 多模态 embedding（文本 + 图片） |
| LLM | Doubao-Seed-2.0-lite | 对话生成 + 意图识别 |
| 流式协议 | SSE | 单向流（AI → 用户），fetch + ReadableStream 消费 |
| 对话历史 | Redis | session_id 为 key，TTL 30 分钟，每次消息自动续期 |
| Java 内部认证 | API Key | Python 调 Java 下单接口用 `X-Internal-Token` Header |

---

## 4. 用户场景与功能需求

### 4.1 基础场景（MVP 必须实现）

| 场景 | 用户输入示例 | 期望行为 |
|---|---|---|
| 单轮模糊推荐 | "推荐附近的川菜馆" | 返回 2-3 个店铺 + 简要推荐理由 |
| 条件筛选 | "春熙路人均100以内的火锅" | 标量过滤：area + avg_price + type |
| 多轮追问 | "推荐火锅" → "人均100以内" → "有包厢的" | LLM 理解上下文，继承与叠加约束 |
| 反选/排除 | "推荐火锅，不要春熙路的" | 否定语义识别 |
| 闲聊兜底 | "你好"、"谢谢" | 直接回复，不走检索 |
| 自动下单 | "帮我买两张蜀大侠的满100减20券" | 查券 → LLM 确认语 → 用户确认 → 下单 |
| 秒杀提醒 | "蜀大侠秒杀券帮我关注" | 走现有 subscribe 接口设置提醒（不提供自动秒杀） |
| 位置未授权 | "推荐附近的火锅"但无坐标 | Agent 引导用户授权位置，或用户手动输入 |

### 4.2 进阶场景（后续迭代）

| 场景 | 说明 |
|---|---|
| 对比决策 | "A 和 B 哪家更适合约会？" — 多维度结构化对比 |
| 拍照找店 | 上传照片识别店铺门头/菜品，匹配同款 |
| 语音交互 | 语音输入 → ASR → RAG → TTS 播报 |
| 支付密码 / 二次确认弹窗 | 提升大额下单安全性 |
| Kafka 驱动增量同步 | 替换轮询，准实时 |
| Prompt 缓存 | 首屏优化 |
| 热门查询缓存 | 高频查询加速 |
| Docker Compose 编排 | 统一部署 |
| 长期记忆 | 向量数据库存储用户长期偏好 |

---

## 5. 数据模型

### 5.1 现有表变更

复用现有业务表，不做 RAG 专属表。Python 同步时通过 Java REST 接口查询现有表数据，做 embedding 写入 Milvus。

**`tb_shop` 新增字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| description | TEXT | 店铺详细描述（RAG 核心检索素材） |
| tags | JSON | 标签列表，如 `["停车方便", "有包厢", "适合约会"]` |
| recommended_scenes | JSON | 推荐场景列表，如 `["约会", "家庭聚餐", "商务宴请"]` |

**`tb_shop_type` 新增字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| parent_id | BIGINT | 父分类 ID（可空，构建两级分类树 e.g. 美食 → 川渝火锅） |

### 5.2 Milvus Collection

**`collection_shop_desc`** — 店铺描述向量

| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR PK | "shop_desc_{shop_id}" |
| embedding | FLOAT_VECTOR | `name + description + tags + recommended_scenes + images` 的多模态 embedding |
| shop_id | BIGINT | 店铺 ID（metadata） |
| area | VARCHAR | 商圈（metadata，标量过滤） |
| longitude | DOUBLE | 经度（metadata） |
| latitude | DOUBLE | 纬度（metadata） |
| avg_price | INT | 人均（metadata，标量过滤） |
| type | VARCHAR | 大类名称（metadata，标量过滤） |
| sub_type | VARCHAR | 子类名称（metadata） |
| score | INT | 评分（metadata） |
| open_hours | VARCHAR | 营业时间（metadata） |
| tags | VARCHAR | 标签（metadata） |
| content_type | VARCHAR | 固定为 "shop_description" |

- **向量化字段**（语义密集）：name + description + tags + recommended_scenes + images
- **元数据字段**（标量过滤/排序）：area, longitude, latitude, avg_price, type, sub_type, score, open_hours

**`collection_user_note`** — Blog（探店笔记）向量

| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR PK | "note_{blog_id}" |
| embedding | FLOAT_VECTOR | `title + content` 的 embedding |
| shop_id | BIGINT | 关联店铺 ID（metadata） |
| user_nickname | VARCHAR | 用户昵称（metadata） |
| content_type | VARCHAR | 固定为 "user_note" |

- **向量化字段**：title + content
- **元数据字段**：shop_id, user_nickname

**检索结果合并策略**：两个 Collection 分别检索后，按 `shop_id` 分组去重，同一店铺的 Blog 附在店铺后面，整体送入 LLM context。

### 5.3 Redis（对话历史）

```
Key:   chat:session:{session_id}
Value: JSON 数组
TTL:   30 分钟（每次新消息续期）

消息格式:
[
  {
    "role": "user",
    "content": "推荐附近的火锅"
  },
  {
    "role": "assistant",
    "content": "为您找到两家火锅店：...",
    "shops": [
      {"shop_id": 123456, "name": "蜀大侠火锅"}
    ]
  }
]
```

- session_id 由后端生成，按用户共享
- 长期记忆后续迭代用向量数据库实现

---

## 6. 核心流程

### 6.1 对话请求链路

```
Vue (SSE) → Java ChatController → HTTP SSE → Python /chat
                                                    │
                                         ┌──────────▼──────────┐
                                         │  1. 加载 Redis 历史   │
                                         │  2. 意图识别 (LLM)    │
                                         │     - recommend_shop │
                                         │     - chat           │
                                         │     - purchase       │
                                         │  3. 分支判断          │
                                         └──────────┬──────────┘
                          ┌──────────────────────────┼──────────────────────┐
                          │ recommend_shop           │ chat      │ purchase  │
                          ▼                          ▼           ▼           │
               ┌──────────────────┐   ┌──────────┐  ┌──────────────────┐    │
               │ 4. query→embedding│   │ 直接 LLM  │  │ 1. 解析券+数量    │    │
               │ 5. Milvus 检索    │   └──────────┘  │ 2. HTTP 查券(Java)│    │
               │    - shop_desc    │                  │ 3. LLM 生成确认语  │    │
               │    - user_note    │                  │ 4. 用户确认         │    │
               │    + 标量过滤     │                  │ 5. HTTP 下单(Java)  │    │
               │ 6. 按shop_id合并   │                  │ 6. 返回订单结果     │    │
               │ 7. HTTP 查券(Java)│                  └──────────────────┘    │
               │ 8. LLM 流式生成   │                                          │
               └──────────────────┘                                          │
                          │                                                  │
                          ▼                                                  │
               ┌──────────────────┐                                         │
               │ 9. 结构化 SSE 输出│                                         │
               │    text + shop_card                                        │
               │ 10.更新 Redis 历史│                                         │
               └──────────────────┘                                         │
```

- Java ChatController 对 SSE 内容**完全透传**，不做解析或过滤
- 用户确认下单后，若普通券库存不足，Agent 自动重新推荐同类券；秒杀券不支持自动秒杀

### 6.2 LangGraph Agent 图

```
     START ─────> [意图识别] ──→ intent ∈ {recommend_shop, chat, purchase}
                    │
          ┌─────────┼──────────────────┐
          │         │                  │
    recommend_shop  chat           purchase
          │         │                  │
          ▼         ▼                  ▼
     [Milvus 检索] [直接 LLM]    [HTTP 查券 → LLM 确认 → 用户确认 → HTTP 下单]
          │                           │
    ┌─────┴─────┐                     │
    │ 有结果    │ 无结果               │
    ▼          ▼                      │
 [HTTP 查券] [兜底回复]                │
    │          │                      │
 [LLM 生成]   │                      │
    │          │                      │
    └──────────┴──────────────────────┘
               │
              END
```

### 6.3 数据增量同步

```
Python 启动时:
  1. HTTP GET /api/sync/shops?since=0     → 全量店铺
  2. HTTP GET /api/sync/blogs?since=0     → 全量 Blog
  3. embedding + 批量写入 Milvus 两个 collection

定时任务（每 5 分钟）:
  1. 读取本地 last_sync_time
  2. HTTP GET /api/sync/shops?since={last_sync_time}
  3. HTTP GET /api/sync/blogs?since={last_sync_time}
  4. 变更处理:
     - 新增/更新: 删旧向量 → embedding → 插新向量
     - 软删除: 按 id 删向量
  5. 更新 last_sync_time = now()
```

- 图片处理：Python 从本地文件系统读取图片（同机器部署），送入多模态 embedding
- 后续迭代切 Kafka 准实时

### 6.4 SSE 消息格式

```
text:      {"type": "text", "content": "为您找到两家适合约会的火锅店：\n\n"}
shop_card: {"type": "shop_card", "data": { "shop_id": 123456, "name": "...", "score": 4.6, "avg_price": 120, "image": "...", "tags": [...], "voucher": {...} }}
done:      {"type": "done"}
error:     {"type": "error", "content": "错误信息"}
```

---

## 7. HTTP 接口定义

### 7.1 对话流式（Java → Python）

```
POST /chat
Header: X-Internal-Token: {api_key}
Content-Type: application/json

{
  "session_id": "uuid",
  "user_id": 123456,
  "query": "推荐附近的火锅",
  "longitude": 104.06,
  "latitude": 30.57
}

Response: SSE stream
  data: {"type": "text", "content": "为您找到..."}
  data: {"type": "shop_card", "data": {...}}
  data: {"type": "done"}
```

### 7.2 数据同步（Java 新增）

```
GET /api/sync/shops?since={timestamp_ms}
  → 返回 update_time >= since 的店铺列表
  → shop_id, name, type(大类名), sub_type(子类名), area, address,
    longitude, latitude, avg_price, score, open_hours, images,
    description, tags, recommended_scenes, update_time

GET /api/sync/blogs?since={timestamp_ms}
  → 返回 update_time >= since 的 Blog 列表
  → blog_id, shop_id, user_nickname, title, content, update_time
```

### 7.3 查券与下单（复用现有接口）

| 用途 | 接口 | 认证 |
|---|---|---|
| 按 shop_ids 批量查可用券 | 现有 voucher 查询 + user_id 过滤 | `X-Internal-Token` |
| 下单 | 现有 VoucherOrderController | `X-Internal-Token` + body 传 user_id |

---

## 8. 前端对话页面

- 路由：`/ai-assistant`
- 入口：底部 TabBar "AI 导购" 图标 + 首页搜索框旁入口
- 核心组件拆分：
  - `ChatView.vue` — 对话窗口主容器
  - `ChatMessage.vue` — 消息气泡（用户/AI 样式区分）
  - `ShopCard.vue` — 可点击店铺卡片，点击弹出 Modal 展示店铺详情（不离开对话页）
  - `ChatInput.vue` — 底部输入框 + 发送按钮
- SSE 消费：`fetch` + `ReadableStream` 解析结构化 JSON，兼容 Header 携带 sa-token
- 用户位置：前端调 `navigator.geolocation` API 获取坐标并传入请求，首次失败时 Agent 引导授权
- 网络断开：显示"连接断开，点击重试"，重连携带同一 session_id，服务端从 Redis 恢复历史并从断点继续

---

## 9. 降级与兜底策略

| 故障点 | 处理 |
|---|---|
| Milvus 不可用 | 闲聊仍可用（纯 LLM），推荐返回 "搜索服务暂时不可用，请稍后再试" |
| LLM 超时 | 返回已生成的部分文本 + "回答被截断，请刷新重试" |
| 检索结果为空 | LLM 告知用户扩大搜索范围，**严禁编造店铺** |
| HTTP 查券失败 | 仍返回店铺推荐，但省略优惠券信息 |
| Redis 不可用 | 仅当前轮对话可用（无历史），不影响核心流程 |

---

## 10. 领域术语

**店铺 (Shop)**：提供餐饮、丽人、休闲等服务的线下实体商户。

**探店笔记 (Blog)**：用户发布的探店/消费评价，包含标题、正文、图片和关联店铺。

**优惠券 (Voucher)**：店铺发布的团购券或代金券，分普通券和秒杀券。

**秒杀券 (Seckill Voucher)**：限量限时的优惠券，需设置提醒但不能自动抢购。

**商圈 (Area)**：地理位置聚类名称，如"春熙路""太古里""九眼桥"，用于标量过滤。

**店铺分类 (Shop Type)**：两级分类树，一级大类（美食）+ 二级子类（川渝火锅）。

**智能导购 (AI Shopping Guide)**：基于自然语言对话为用户推荐店铺和优惠、并可直接下单的 AI Agent。

---

## 11. MVP 范围 vs 后续迭代

### MVP 最小闭环

- [ ] Vue 3 独立对话页面（/ai-assistant），TabBar + 搜索框入口
- [ ] Java WebClient 流式 SSE 透传 Controller + 2 个增量同步 REST 端点
- [ ] Python AI 服务（FastAPI + LangGraph + LangChain）
- [ ] Milvus Docker 部署 + 2 个 Collection（HNSW 索引）
- [ ] 数据全量同步 + 定时轮询增量同步
- [ ] 单轮 + 多轮推荐对话（LLM 理解上下文约束继承与叠加）
- [ ] 意图识别（recommend_shop / chat / purchase）
- [ ] 位置 + 价格 + 类型标量过滤
- [ ] 自动下单（Agent 确认流程，不可自动秒杀）
- [ ] 结构化 SSE 输出（text + shop_card）
- [ ] 降级兜底 + 断点恢复
- [ ] 多模态 embedding（Doubao-embedding-vision，文本 + 图片）
- [ ] tb_shop 新增 description / tags / recommended_scenes 字段
- [ ] tb_shop_type 新增 parent_id 字段

### 后续迭代

- [ ] 多商品对比对话（"A 和 B 哪家好"）
- [ ] 拍照找店（多模态搜索）
- [ ] 语音输入 + TTS 播报
- [ ] 支付密码 / 二次确认弹窗
- [ ] Kafka 驱动增量同步
- [ ] Prompt 缓存与首屏优化
- [ ] 热门查询缓存
- [ ] Docker Compose 统一编排
- [ ] 长期记忆（向量数据库存储用户偏好）
