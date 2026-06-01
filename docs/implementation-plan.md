# AI 智能导购 Agent — 实现计划

> 22 个小步迭代 Issue，按依赖关系排列。做完一个勾一个。

## 依赖关系概览

```
#1 ──► #3 ──► #7
#2        #4 ──► #8
#5 ──► #6 ──► #9 (汇合 #7+#8)
 │
 ├─► #10 ──► #11
  │    ├──► #12 ──► #20 ──► #21 (#17+#20)
  │    ├──► #13 ──► #19
  │    │    ├─► #14 ──► #15 (#8+#14) ──► #16
  │    │    │                           │
  │    │    │    #11 ────────────────────┤
  │    │    │     │                      │
  │    │    │     └──► #18              │
  │    │    │                            │
  │    │    └──► #17 ◄── #15 + #16 ─────┘
  │    │              │
  │    │              └──► #22 (#17+#20)
```

---

## #1 DB迁移：tb_shop 新增字段

**类型**：AFK | **阻塞**：无

### 内容

`tb_shop` 表新增三个字段：

- `description` TEXT — 店铺详细描述，RAG 核心检索素材
- `tags` JSON — 标签列表，如 `["停车方便", "有包厢", "适合约会"]`
- `recommended_scenes` JSON — 推荐场景列表，如 `["约会", "家庭聚餐", "商务宴请"]`

编写 DDL 迁移脚本放入 `sql/` 目录。

### 验收标准

- [ ] `tb_shop` 包含 `description` (TEXT) 字段
- [ ] `tb_shop` 包含 `tags` (JSON) 字段
- [ ] `tb_shop` 包含 `recommended_scenes` (JSON) 字段
- [ ] 迁移脚本可重复执行（幂等）

---

## #2 DB迁移：tb_shop_type 新增 parent_id

**类型**：AFK | **阻塞**：无（可与 #1 并行）

### 内容

`tb_shop_type` 表新增 `parent_id` (BIGINT) 字段，可空，用于构建两级分类树（例如：美食 → 川渝火锅）。

编写 DDL 迁移脚本放入 `sql/` 目录。

### 验收标准

- [ ] `tb_shop_type` 包含 `parent_id` (BIGINT) 字段，允许 NULL
- [ ] 迁移脚本可重复执行（幂等）

---

## #3 Java：Shop 增量同步端点

**类型**：AFK | **阻塞**：#1

### 内容

新增 `GET /api/sync/shops?since={timestamp_ms}` 端点。

- `since=0` 时返回全量店铺
- 按 `update_time >= since` 过滤
- 返回字段：`shop_id, name, type(大类名), sub_type(子类名), area, address, longitude, latitude, avg_price, score, open_hours, images, description, tags, recommended_scenes, update_time`
- 使用 `X-Internal-Token` Header 认证

### 验收标准

- [ ] `GET /api/sync/shops?since=0` 返回全量店铺数据
- [ ] `GET /api/sync/shops?since={ts}` 只返回 update_time >= ts 的记录
- [ ] 无有效 Token 时返回 401
- [ ] 响应 JSON 包含全部指定字段

---

## #4 Java：Blog 增量同步端点

**类型**：AFK | **阻塞**：无（可与 #3 并行）

### 内容

新增 `GET /api/sync/blogs?since={timestamp_ms}` 端点。

- `since=0` 时返回全量 Blog
- 按 `update_time >= since` 过滤
- 返回字段：`blog_id, shop_id, user_nickname, title, content, update_time`
- 使用 `X-Internal-Token` Header 认证

### 验收标准

- [ ] `GET /api/sync/blogs?since=0` 返回全量 Blog 数据
- [ ] `GET /api/sync/blogs?since={ts}` 只返回 update_time >= ts 的记录
- [ ] 无有效 Token 时返回 401
- [ ] 响应 JSON 包含全部指定字段

---

## #5 Milvus Docker 部署 + Python 项目骨架

**类型**：AFK | **阻塞**：无（纯基础设施）

### 内容

- Docker Compose 配置文件启动 Milvus 单机实例
- Python 项目初始化：`pyproject.toml`，FastAPI app 骨架
- `/health` 端点返回 200
- 项目目录结构：`python-ai-service/src/{agent,ingestion,milvus,main.py}`

### 验收标准

- [ ] `docker compose up` 启动 Milvus 单机，端口可访问
- [ ] `python-ai-service/` 目录结构就绪
- [ ] `pyproject.toml` 含 FastAPI, LangGraph, LangChain, pymilvus 依赖
- [ ] `GET /health` 返回 200

---

## #6 Milvus Collection 创建 + HNSW 索引

**类型**：AFK | **阻塞**：#5

### 内容

创建两个 Collection：

**collection_shop_desc** — 店铺描述向量
- PK: `id` (VARCHAR, "shop_desc_{shop_id}")
- 向量: `embedding` (FLOAT_VECTOR, dim 由 embedding 模型决定)
- 标量: `shop_id, area, longitude, latitude, avg_price, type, sub_type, score, open_hours, tags, content_type`

**collection_user_note** — 探店笔记向量
- PK: `id` (VARCHAR, "note_{blog_id}")
- 向量: `embedding` (FLOAT_VECTOR)
- 标量: `shop_id, user_nickname, content_type`

两个 Collection 均配置 HNSW 索引。

### 验收标准

- [ ] `collection_shop_desc` 存在，schema 包含所有指定字段
- [ ] `collection_user_note` 存在，schema 包含所有指定字段
- [ ] 两个 Collection 均配置 HNSW 索引

---

## #7 shop_desc Embedding + 全量同步

**类型**：AFK | **阻塞**：#3, #6

### 内容

- 调 `GET /api/sync/shops?since=0` 获取全量店铺
- 构造向量化文本：`name + description + tags + recommended_scenes + images`
- 调用 Doubao-embedding-vision 生成 embedding
- 批量 upsert 到 `collection_shop_desc`

### 验收标准

- [ ] 全量同步成功完成
- [ ] `collection_shop_desc` 行数等于 tb_shop 行数
- [ ] 每条记录的 `embedding` 字段非空

---

## #8 user_note Embedding + 全量同步

**类型**：AFK | **阻塞**：#4, #6

### 内容

- 调 `GET /api/sync/blogs?since=0` 获取全量 Blog
- 构造向量化文本：`title + content`
- 调用 Doubao embedding 生成 embedding
- 批量 upsert 到 `collection_user_note`

### 验收标准

- [ ] 全量同步成功完成
- [ ] `collection_user_note` 行数等于 tb_blog 行数
- [ ] 每条记录的 `embedding` 字段非空

---

## #9 增量同步定时任务

**类型**：AFK | **阻塞**：#7, #8

### 内容

- 每 5 分钟执行一次
- 读取本地 `last_sync_time`
- 分别调 `/api/sync/shops?since={last_sync_time}` 和 `/api/sync/blogs?since={last_sync_time}`
- 新增/更新：删旧向量 → embedding → 插新向量
- 软删除：按 id 删除向量
- 更新 `last_sync_time = now()`

### 验收标准

- [ ] 新增一条 shop 后，等一轮同步周期，Milvus 中可见
- [ ] 更新一条 shop 后，等一轮同步周期，向量已刷新
- [ ] 删除一条 shop 后，等一轮同步周期，向量已删除

---

## #10 Python /chat 端点骨架 + chat 意图 SSE

**类型**：AFK | **阻塞**：#5

### 内容

实现 `POST /chat` 端点：

- 接收 `{session_id, user_id, query, longitude, latitude}`
- 先只实现 `chat` 意图——直接调 Doubao LLM 流式生成
- SSE 流式返回 `text` + `done` 事件
- 响应格式：`data: {"type": "text", "content": "..."}` / `data: {"type": "done"}`

### 验收标准

- [ ] `POST /chat` 返回 SSE Content-Type
- [ ] curl 发送 `{"query": "你好"}`，收到流式 text 事件
- [ ] 流结束时收到 `{"type": "done"}`

---

## #11 Redis 对话历史存储

**类型**：AFK | **阻塞**：#10

### 内容

- Key: `chat:session:{session_id}`
- Value: JSON 数组 `[{role, content, shops?}]`
- TTL: 30 分钟，每次新消息自动续期
- 每次对话请求前加载历史，请求后追加新消息

### 验收标准

- [ ] 发一条消息后 Redis 中存在对应 key
- [ ] 历史数据包含 role 和 content 字段
- [ ] 30 分钟无操作后 key 自动过期
- [ ] 新消息到达时 TTL 重置为 30 分钟

---

## #12 Java ChatController + WebClient SSE 透传

**类型**：AFK | **阻塞**：#10

### 内容

- `ChatController` 接收前端 SSE 请求（携带 sa-token）
- `WebClient` 连接 Python `POST /chat`，传入 `X-Internal-Token`
- `Flux<ServerSentEvent>` 逐条透传给前端
- **不做解析、不做过滤**——完全透传

### 验收标准

- [ ] curl Java `/api/chat/stream` 返回的 SSE 与直接调 Python `/chat` 一致
- [ ] 无 sa-token 时返回 401
- [ ] 前端可通过 `fetch` + `ReadableStream` 消费 SSE

---

## #13 LLM 意图识别路由

**类型**：AFK | **阻塞**：#10

### 内容

LangGraph 入口节点：LLM 将用户 query 分类为三种意图：

- `recommend_shop` — 店铺推荐（后续走 Milvus 检索）
- `chat` — 闲聊兜底（直接 LLM 回复）
- `purchase` — 下单购买券

`chat` 走现有直聊分支；其余两个先返回占位提示。

### 验收标准

- [ ] "推荐火锅" → 识别为 `recommend_shop`
- [ ] "你好" → 识别为 `chat`
- [ ] "帮我买两张券" → 识别为 `purchase`
- [ ] 非 chat 意图返回明确的占位提示

---

## #14 shop_desc 语义检索（单 Collection）

**类型**：AFK | **阻塞**：#7, #13

### 内容

`recommend_shop` 分支第一步：

- 用户 query → Doubao embedding
- Milvus `collection_shop_desc` 向量搜索（Top-K = 5）
- 纯向量检索，暂不加标量过滤

### 验收标准

- [ ] curl "推荐火锅" → Python 日志确认 Milvus 返回 5 条搜索结果
- [ ] 返回结果的 content_type 均为 "shop_description"

---

## #15 user_note 检索 + 双路结果合并

**类型**：AFK | **阻塞**：#8, #14

### 内容

- 同时对 `collection_user_note` 检索（Top-K = 3）
- 两路结果按 `shop_id` 分组去重
- Blog 附在对应店铺后，整体结构为 `[{shop, notes: [...]}, ...]`

### 验收标准

- [ ] 一次 query 同时触发两个 Collection 搜索
- [ ] 同一 shop_id 的笔记正确合并到对应店铺下
- [ ] 合并后的数据结构可送入 LLM

---

## #16 标量过滤（商圈 / 价格 / 类型）

**类型**：AFK | **阻塞**：#14

### 内容

- LLM 从 query 中提取过滤条件（area, avg_price, type）
- Milvus 查询时附加 scalar filter：`area == "春熙路" AND avg_price <= 100 AND type == "美食"`
- 结合向量相似度 + 标量过滤返回结果

### 验收标准

- [ ] "春熙路人均100以内的火锅" → 结果全部满足 area=春熙路, avg_price<=100, type=美食
- [ ] query 无过滤条件时仍按纯向量检索
- [ ] LLM 提取条件失败时优雅降级

---

## #17 HTTP 查券 + LLM 推荐语生成 + shop_card SSE

**类型**：AFK | **阻塞**：#15, #16

### 内容

- 检索结果合并后，HTTP 调 Java 查券接口（按 shop_ids 批量查可用券）
- 拼接 context（店铺信息 + 券信息 + 用户笔记）送入 LLM
- LLM 流式生成推荐语
- SSE 交替输出 `text` 和 `shop_card` 事件

shop_card 格式：
```json
{"type": "shop_card", "data": {"shop_id": 123, "name": "...", "score": 4.6, "avg_price": 120, "image": "...", "tags": [...], "voucher": {...}}}
```

### 验收标准

- [ ] SSE 流中包含 `{"type": "shop_card"}` 事件
- [ ] shop_card 含券信息（如果该店铺有可用券）
- [ ] 查券失败时仍返回店铺推荐，但省略券信息
- [ ] 流结束收到 `{"type": "done"}`

---

## #18 多轮对话：Redis 历史注入 + 约束继承

**类型**：AFK | **阻塞**：#11, #14

### 内容

- 加载 Redis 历史注入 LLM context
- 约束继承叠加：第一轮"火锅" → 第二轮"人均100以内" → 第三轮"有包厢"，逐轮追加筛选
- 否定语义识别："不要春熙路的"
- 断线重连：前端重连携带同一 session_id，从 Redis 恢复对话历史继续

### 验收标准

- [ ] 同一 session 连续 3 条消息：约束逐轮叠加
- [ ] "推荐火锅，不要春熙路的" → 结果排除春熙路商圈
- [ ] 模拟断线重连：同一 session_id 发送消息，上下文不丢失

---

## #19 下单流程：券解析 → 查券 → LLM 确认 → 下单

**类型**：AFK | **阻塞**：#13

### 内容

`purchase` 意图完整链路：

1. LLM 解析券名 + 数量
2. HTTP 调 Java 查券接口（`X-Internal-Token` 认证）
3. LLM 生成确认语（"为您找到蜀大侠满100减20券 ×2，共40元，确认下单吗？"）
4. 等待用户回复"确认"
5. HTTP 调 Java 下单接口（`X-Internal-Token` + body 传 user_id）
6. 返回订单结果

业务规则：
- 秒杀券拦截，提示"秒杀券不支持自动下单，已为您设置提醒"
- 普通券库存不足时 LLM 推荐同类替代券

### 验收标准

- [ ] curl 发送"帮我买两张蜀大侠满100减20的券" → 收到确认语
- [ ] 回复"确认" → 返回订单号和订单状态
- [ ] 回复"取消" → 取消下单
- [ ] 秒杀券 → 拦截 + 提示已设置提醒
- [ ] 库存不足 → 推荐替代券

---

## #20 前端聊天页面（路由 + SSE 消费 + Chat UI）

**类型**：AFK | **阻塞**：#12

### 内容

- 路由：`/ai-assistant`
- 入口：底部 TabBar "AI 导购" 图标
- `ChatView.vue` — 对话窗口主容器
- `ChatMessage.vue` — 消息气泡（用户/AI 样式区分）
- `ChatInput.vue` — 底部输入框 + 发送按钮
- `fetch` + `ReadableStream` 消费 SSE，兼容 Header 携带 sa-token
- `navigator.geolocation` 获取坐标并传入请求

### 验收标准

- [ ] 浏览器打开 `/ai-assistant`，显示空白对话页
- [ ] 输入"你好"，看到 AI 流式回复逐字渲染
- [ ] 用户消息和 AI 消息气泡样式有明显区分
- [ ] 坐标获取失败时仍可发送消息（传空坐标）

---

## #21 前端店铺卡片 + 详情 Modal

**类型**：AFK | **阻塞**：#17, #20

### 内容

- `ShopCard.vue` 解析 `type: "shop_card"` SSE 事件
- 在对话流中渲染可点击店铺卡片：名称、评分、人均、图片、标签、关联券
- 点击卡片弹出 Modal 展示店铺完整详情（复用现有店铺详情接口）
- Modal 不离开对话页

### 验收标准

- [ ] 对话中收到推荐回复 → 店铺卡片在消息气泡中渲染
- [ ] 卡片显示评分、人均、图片、标签、券信息
- [ ] 点击卡片 → Modal 弹出展示完整店铺详情
- [ ] Modal 关闭回到对话页，聊天状态不丢失

---

## #22 降级兜底 + 断点恢复

**类型**：AFK | **阻塞**：#17, #20

### 内容

各故障点的降级处理：

| 故障点 | 处理 |
|--------|------|
| Milvus 不可用 | 闲聊仍可用（纯 LLM），推荐返回 "搜索服务暂时不可用，请稍后再试" |
| LLM 超时 | 返回已生成的部分文本 + "回答被截断，请刷新重试" |
| 检索结果为空 | LLM 告知用户扩大搜索范围，严禁编造店铺 |
| HTTP 查券失败 | 仍返回店铺推荐，但省略优惠券信息 |
| Redis 不可用 | 仅当前轮对话可用（无历史），不影响核心流程 |
| 前端网络断开 | 显示 "连接断开，点击重试"，重连携带同一 session_id |

### 验收标准

- [ ] Milvus 宕机 → 闲聊正常，推荐返回降级提示
- [ ] LLM 超时 → 用户收到部分文本 + 截断提示
- [ ] 检索为空 → LLM 引导扩大搜索，不编造内容
- [ ] 查券 500 → 仍返回店铺卡片，无券字段
- [ ] Redis 宕机 → 当前轮对话可用，历史丢失
- [ ] 前端断网 → 显示重试按钮，重连恢复对话
