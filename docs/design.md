# Inconnewt 技术方案

> 对应 goal.md 交付物「技术方案文档」。世界观与人设约束见 [outline.md](../outline.md)，迭代过程与各版本需求见 [goal.md](../goal.md)，AI 辅助开发的完整提示词记录见 [prompt.md](prompt.md)。

## 1. 玩法

玩家是「劫后十年，第一个走进新螈镇的外来者」，以角色身份（而非上帝视角）进入世界：

- **观察**：四位居民（莫莫/小柯/阿羯/利利）按人设、需求、每日计划自主行动，同地点相遇会自发互动；昼夜与天气在场景中可见。
- **对话**：靠近居民才能交谈（AVG 式演出 + 流式打字机）；居民会引用当下地点、时刻、天气与在场者，并更新对玩家的好感与印象。
- **行动**：对话中的自然语言请求（跟我走 / 去吃饭 / 帮我带话）由 AI 理解为结构化意图，下一 tick 由居民执行。
- **影响世界**：公告板自由文本进入全体居民上下文；水潭「蝾螈许愿」改天气；心愿系统（取物/传话/陪伴）与四格口袋构成回报回路；秘闻收进「小镇手记」作为收集目标。
- **存档**：每位访客一个独立世界（Cookie 身份），3 手动槽 + 自动档 + JSON 导出/导入。

## 2. 技术选型

| 层 | 选型 | 取舍理由 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite | 生态成熟，AI 辅助开发资料最全 |
| 渲染 | Phaser 3（嵌入 React） | Tilemap/精灵/相机开箱即用；强制 WebGL + 高性能模式 |
| 美术 | 2D 像素：整张静态底图 + Kenney CC0 精灵改色 | 不引入 Tiled 运行时解析，坐标锚点体系最简 |
| 后端 | Python 3.12 + FastAPI | AI 生态最强；异步支持 tick 循环；Pydantic 校验接口 |
| 实时 | REST + SSE | 单向推送足够，比 WebSocket 简单，反代零配置 |
| AI | OpenAI 兼容抽象（默认 DeepSeek V4 Flash） | 一套代码适配多家；决策用 JSON 结构化输出，对话流式 |
| 数据库 | SQLite（单文件，多世界多行） | 世界快照整存整取，零运维；MVP 规模远够 |
| 部署 | Docker Compose（backend + Caddy） | 一条命令上线；密钥仅走 `.env` |
| 测试 | pytest ×32 | 覆盖决策/降级/存档/幻觉治理/意图协议/多世界隔离 |

## 3. 架构与决策设计

```
浏览器  React HUD + Phaser 场景（玩家精灵/居民精灵/昼夜雾效）
   │ REST（指令/查询） ↑ SSE（事件流 + 心跳）
FastAPI
   ├─ 访客中间件：HttpOnly Cookie 签发 world_id → WorldManager 按访客隔离世界
   ├─ Tick 调度：仅推进活跃世界（页面开着才走时间）
   ├─ 认知层：决策/对话/心愿/互动 → AI Provider 抽象
   │     ├─ deepseek（结构化 JSON + 流式）
   │     └─ mock（效用规则引擎 + 人设模板库）
   ├─ grounding.py：事实卡拼装 / canon 秘闻白名单 / 记忆实体闸门
   ├─ intents.py：封闭动词表 + 白名单/可行性校验 → tick 行动队列
   └─ SQLite：world_state（按 world_id）/ saves（3 槽+auto）/ ai_usage（日预算）
```

**NPC 决策循环**：tick 到点 → 组装上下文（人设 prompt 分层 + 当前状态 + 每日计划 + 最近 3 次行动 + 短期记忆 + 日记摘要 + 事实卡）→ LLM 输出结构化行动 `{action, target, say, reason}` → 校验失败落规则引擎 → 执行并写记忆 → SSE 广播。`reason` 同时用于头顶气泡展示「自主决策」。

**Prompt 分层**：`world.md`（世界圣经：有什么、没有什么、谁知道什么）+ `npc/<id>.md`（每角色人设卡：性格 / 说话风格 Do & Don't / 面对未知的反应）+ `format.md`（输出格式）。改人设只改单文件。

**NPC 数据结构**：`profile`（静态人设 + 降级引擎 weights）/ `state`（位置、当前行动、needs、mood）/ `memory`（短期环形缓冲 + LLM 摘要日记）/ `relationships`（含对玩家的 affinity + impression）。

## 4. 接口设计

| 接口 | 说明 |
|---|---|
| `GET /api/session` · `POST /api/session/start` · `/restart` | 访客身份、进入/重开世界 |
| `GET /api/world` · `GET /api/npcs/{id}` | 世界快照 / 居民详情 |
| `POST /api/chat/{id}/stream` | 对话（SSE 流式；meta 帧含意图、好感、秘闻解锁） |
| `POST /api/player/move` · `/scavenge` · `/gift` · `/appearance` | 玩家移动 / 拾取 / 送礼 / 外观 |
| `POST /api/board` · `/wish-weather` · `/quests/{id}/accept` | 公告板留言 / 蝾螈许愿 / 接心愿 |
| `POST /api/world/save` · `/load` · `GET /saves` · `/export` · `POST /import` | 槽位存档与 JSON 导出导入 |
| `GET /api/events`（SSE） | 世界事件推送，兼作活跃心跳 |
| `POST /api/world/tick` · `/actions` | 观察者调试：推进一刻 / 直改天气 |

## 5. AI / Mock 模式

- `.env` 中 `AI_PROVIDER=mock|deepseek` 一键切换；未配置密钥、调用超时或失败时自动回落 Mock，前端右上角标注当前模式。
- **Mock 保证全流程可体验**：效用规则引擎（读人设 weights）驱动决策，对话模板按角色分库，心愿/传话/存档均可完成——对应评估项 3、4。
- **幻觉治理**（真实 AI）：每次调用注入结构化事实卡（居民/地点/在场者/口袋/心愿/近 5 条真实事件全集），模型不能新增世界实体；秘闻正文写死在 `canon.json`，模型只返回可透露的 ID；事件记忆由后端模板生成，入库前过实体闸门。原则：**事实由代码保证，感受由 AI 生成**。
- **意图理解**（真实 AI）：对话一次调用同时产出台词与 `intents[]`（封闭动词表：follow/stop/goto/do/visit/relay），后端白名单 + 可行性校验后入 tick 队列异步执行；Mock 刻意只保留跟随/停止两个短语，README 写明边界——两种模式的对照即是「AI 真正被用起来」的演示位。
- **成本护栏**：仅活跃世界消耗 tick 与 AI 调用；每世界每日 AI 预算（默认 120 次），用尽当日进入 Mock，不影响其他访客。

## 6. 关键决策与 AI 修改案例

六条关键决策（玩家入世界坐标系、事实卡边界、封闭动词表、对话不阻塞世界执行、服务器托管+本地导出、活跃/预算护栏）及其完整理由见 [README「关键决策」章节](../README.md#关键决策)。

**一处 AI 修改案例**：v3 早期「NPC 听懂玩家的话」用关键词短语表实现，扩展新意图时词条组合爆炸、实现卡死。修改为：代码只定义封闭动词表（`intents.py`），理解完全交给模型——对话结构化输出扩为 `intents[]`，任意措辞（委托/暗示/反话）由模型映射到动词表，后端只做白名单与可行性校验。详见 [README「一处 AI 修改案例」](../README.md#一处-ai-修改案例从关键词匹配到模型原生理解) 与提交 `5052bdc`。

## 7. 工程素养对照

- **配置管理**：密钥仅走 `.env`（提供 `.env.example`），`.gitignore` 排除密钥与数据库文件；
- **错误处理**：AI 调用超时/重试/降级链路；意图非法参数静默丢弃；存档导入 `schema_version` 校验；读档/重开二次确认；
- **自动化测试**：32 项 pytest（`backend/tests/test_world.py`），CI 入口即 `pytest` + `npm run build`；
- **AI 辅助开发流程**：全程提示词与版本迭代记录见 [prompt.md](prompt.md)（Claude Fable 负责方案与审查、GPT 负责实现的双 agent 分工，goal.md 以 v1→v3.3 递进承载需求）。
