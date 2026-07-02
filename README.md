# Pick — 本地生活Agent导购平台

基于 Spring Boot + LangGraph 的本地生活运营平台，围绕店铺发现、优惠券秒杀、AI 智能导购三大核心场景，融合高并发、分布式、RAG 检索等企业级技术方案。

## 核心功能

### 店铺发现与评价
- 店铺按商圈/分类浏览，支持坐标定位与评分排序
- 用户探店笔记（Blog）发布、评论互动、关注机制
- 布隆过滤器 + 本地缓存支撑热点查询

### 优惠券与秒杀
- 普通券（不限量）与秒杀券（限量限时）双模式
- Redis Lua 脚本原子化库存扣减，Kafka 异步持久化对账
- 令牌桶 + 滑动窗口双算法限流，防刷防超卖
- 秒杀提醒订阅、候补排队机制

### AI 智能导购
- 自然语言对话式推荐店铺与优惠券，支持流式输出（SSE）
- RAG 检索增强生成：Milvus 向量语义检索 + BM25 关键词检索 + 多路融合
- Neo4j 知识图谱实体关系增强
- 意图分类：店铺推荐 / 闲聊 / 下单购买
- 用户长期记忆系统：会话摘要、用户画像、反馈闭环
- 工具调用：查券、下单、退款、收藏、到店预约

### 社交与互动
- 用户关注/取关、探店笔记发布、评论回复
- 券收藏与上架提醒

## 技术架构

| 层次 | 技术栈 |
|------|--------|
| 前端 | Vue 3 (Composition API) + Vite 6 + Pinia + Axios (SSE 流式) |
| 后端 | Java 17 / Spring Boot 3.5.4 / MyBatis-Plus / Sa-Token |
| AI 服务 | Python / FastAPI / LangGraph / Milvus / Neo4j |
| 数据库 | MySQL 8.0 + ShardingSphere 5.3.2 分库分表 |
| 缓存 | Redis (Redisson) — 分布式锁、布隆过滤器、延迟队列 |
| 消息队列 | Kafka — 订单异步持久化 + DLQ 容错 |
| 监控 | Prometheus + Micrometer + Log4j2 |
| API 文档 | Knife4j (Swagger) |

## 项目结构

```
Pick/
├── core-service/          # Spring Boot 主服务 — 业务逻辑、API、消息消费
├── agent-service/         # Python AI Agent 服务 — RAG 检索、LLM 对话、记忆系统
├── common/                # 共享枚举、异常、工具类
├── parameter/             # 跨模块 DTO/VO
├── sharding/              # ShardingSphere 分片配置
├── id-generator-framework/ # 雪花 ID 生成器
├── mq-framework/          # Kafka 生产者/消费者抽象
├── redis-tool-framework/  # Redis 限流工具（令牌桶 + 滑动窗口）
├── redisson-framework/    # Redisson 分布式服务封装
├── vue3/                  # Vue 3 前端
├── sql/                   # 数据库建表与种子数据
└── docs/                  # 设计文档与迭代计划
```

## 快速开始

### 环境要求

- JDK 17
- Maven 3.8+
- Node.js 18+
- MySQL 8.0
- Redis 7.x
- Kafka 3.x
- Milvus 2.x (AI 导购功能需要)
- Neo4j 5.x (AI 导购功能需要)
- Python 3.10+ (AI 导购功能需要)

### 后端

```bash
# 初始化数据库（创建 shard_0 / shard_1 并导入表结构）
mysql -u root -p < sql/1_create_database.sql
mysql -u root -p shard_0 < sql/Pick_0.sql
mysql -u root -p shard_1 < sql/Pick_1.sql

# 编译启动
mvn clean package -DskipTests
mvn spring-boot:run -pl core-service
```

### 前端

```bash
cd vue3
npm install
npm run dev        # 开发服务器，默认代理 /api → localhost:8085
```

### AI Agent 服务

```bash
cd agent-service
pip install -r requirements.txt
python -m src.main
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_SERVICE_URL` | `http://localhost:8000` | AI Agent 服务地址 |
| `SYNC_INTERNAL_TOKEN` | `internal-dev-token` | 内部同步接口鉴权 Token |

### 秒杀链路

```
用户请求 → 令牌桶限流 → Redis Lua 原子扣减 ──成功──→ Kafka 消息 → 异步创建订单 → 对账入库
                         │
                         └──失败──→ 回滚 Lua 脚本恢复库存
```

- Lua 脚本一次网络往返完成库存校验 + 用户去重 + 扣减 + 流水记录
- Kafka 手动立即确认 + 幂等生产者（acks=all, retries=5）+ DLQ 兜底

## License

Apache License 2.0
