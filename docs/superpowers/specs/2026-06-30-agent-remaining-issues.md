# Agent 服务待办事项追踪

> 2026-06-30 | 基于 codebase gap analysis 的剩余工作

## P1 — RAG 增强

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | **产品搜索仅有 Dense**：`search_shops` 无 BM25 混合检索，仅靠 HNSW/COSINE | `agent/services/milvus.py` | 关键词精确匹配场景（如"星巴克"）召回率低 |
| 2 | **无 Query Rewriting**：用户原始 query 直接传入 Milvus，无扩展/改写/分解 | `search_shops.py` | 短 query、口语化 query 召回不足 |
| 3 | **无 Reranker**：检索结果仅靠 cosine distance 排序，无 Cross-encoder 精排 | `retrieval/` | Top-K 结果相关性不够精准 |
| 4 | **两种嵌入模型不互通**：shop 用 Doubao vision model，user note 用 text model，向量空间不同 | `shop_sync.py` vs `embedding.py` | 跨集合无法比较 |
| 5 | **无语义路由**：用户请求无文档类型分流（shop vs blog vs knowledge doc） | `search_shops.py` | 所有查询走同一条检索路径 |

## P2 — 可运维性

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 6 | **无可观测性**：无 Prometheus metrics、无 OpenTelemetry tracing、无请求 ID | `main.py` | 生产排错困难 |
| 7 | **无集中配置**：`os.getenv` 散落 7+ 文件，无校验、无文档 | 全项目 | 配置错误只能在运行时发现 |
| 8 | **无 Dockerfile**：agent-service 无法容器化 | `agent-service/` | 部署依赖手动步骤 |
| 9 | **健康检查不验证依赖**：`/health` 只返回 ok，不检查 Neo4j/Milvus/Postgres | `main.py:358` | K8s liveness probe 无法发现依赖故障 |
| 10 | **Prompt 重复**：`system_prompt.py` 定义了 `SYSTEM_PROMPT_WITH_MEMORY`（130行），但 `agent.py` 用内联版本 | `agent.py` vs `prompts/system_prompt.py` | 维护两套 prompt，不同步 |
| 11 | **无 CORS 中间件** | `main.py` | 前端跨域受限 |
| 12 | **无模型 Fallback**：LLM 不可用时无降级链 | `config.py` | 单点故障 |

## P3 — 待建设

| # | 问题 | 说明 |
|---|------|------|
| 13 | **提取模型未分离** | 对话、意图分类、记忆提取、Profile 更新全用同一个模型（默认 gpt-4o-mini），无成本/质量分层 |
| 14 | **检索质量评估框架** | 无 recall@k / MRR / NDCG 离线评估 |
| 15 | **知识库文档摄入** | 仅 shop/blog 数据，无 FAQ、政策文档、运营规则等结构化知识 |
| 16 | **多 Agent Phase 15-19** | Supervisor + Worker 编排（数据模型已预留，逻辑未实现） |
| 17 | **反馈闭环未拉通** | `FeedbackProcessor` 用关键词推断（临时方案），`FeedbackConsumer` 依赖 Kafka 未验证 |
| 18 | **Session 历史仅靠 checkpoint** | 已有会话完全跳过检索，同一会话多轮不会发现新记忆 |

## 已修复 (2026-06-30)

| # | 问题 | 状态 |
|---|------|------|
| P0-1 | `embed_texts` 循环导入 | ✅ 已修复 |
| P0-2 | `redis_history.py` 源码缺失 | ✅ 已修复 |
| P0-3 | `_trigger_memory_extraction` 传空数据 | ✅ 已修复 |
| — | `src/ingestion/` + `src/milvus/` → `src/storage/` | ✅ 已整合 |
| P1-1 | Java 同步无增量 cursor | ✅ 已修复 |
| P1-2 | Java 客户端无连接池/重试/熔断 | ✅ 已修复 |
