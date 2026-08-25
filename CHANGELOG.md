# Changelog

本项目采用语义化版本号记录可演示能力。

## v0.1.0 — 2026-08-25

- 建立 React + TypeScript 前端与 FastAPI 后端；
- 加入三地点、莫莫/利利两位 NPC 及状态驱动的自主 tick；
- 接入 DeepSeek V4 Flash，并提供自动 Mock 降级；
- 加入 NPC 详情、对话、天气/公告/礼物干预和 SSE 事件；
- 加入 SQLite 持久化、手动保存/恢复与 Docker Compose 部署；
- 修正 `Decision.action` 到 `NPCAction.type` 的显式映射，避免动作静默回落为 idle。
