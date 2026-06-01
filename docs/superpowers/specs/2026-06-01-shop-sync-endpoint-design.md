# Shop 增量同步端点设计

**日期**: 2026-06-01 | **相关 Issue**: #3

## 概述

新增 `GET /api/sync/shops?since={timestamp_ms}` 端点，供 Python AI 服务增量/全量同步店铺数据。

## 需求

- `since=0` 返回全量店铺
- `since={ts}` 返回 `update_time >= ts` 的记录
- `X-Internal-Token` Header 认证（application.yml 配置）
- 返回字段：shop_id, name, type(大类名), sub_type(子类名), area, address, longitude, latitude, avg_price, score, open_hours, images, description, tags, recommended_scenes, update_time

## 设计决策

1. **类型名称解析**: DTO + JOIN 查询 — MyBatis 自定义 SQL，一次 JOIN 取出大类名和子类名
2. **认证**: `InternalTokenInterceptor` 校验 `X-Internal-Token` Header，Token 值配置在 application.yml
3. **响应格式**: 复用现有 `Result` 类包装 `List<ShopSyncDTO>`

## 新增组件

| 组件 | 位置 | 职责 |
|---|---|---|
| `ShopSyncDTO` | `dto/ShopSyncDTO.java` | 同步返回字段 |
| `ShopMapper.selectSyncShops()` | `mapper/ShopMapper.java` | JOIN 查询 SQL |
| `SyncController` | `controller/SyncController.java` | REST 端点 |
| `InternalTokenInterceptor` | `utils/InternalTokenInterceptor.java` | Token 校验 |
| `application.yml` | resources | `sync.internal-token` 配置项 |
| `MvcConfig` 修改 | `config/MvcConfig.java` | 注册拦截器 |

## SQL 逻辑

`type_id` 指向子类（parent_id IS NOT NULL），JOIN 两次 `tb_shop_type`：
- `t_sub`：shop.type_id = t_sub.id（子类）
- `t_main`：t_sub.parent_id = t_main.id（大类）

`since=0` 等效全量查询，不加 WHERE 条件。
