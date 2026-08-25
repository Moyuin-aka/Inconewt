# Inconnewt · 新螈镇 AI 小镇 Demo

一个可运行、可观察、可干预的 Web 版 AI 小镇 MVP。劫后第十年，莫莫和利利会依据自己的需求、人设、天气与小镇公告决定下一步行动；玩家可以查看她们的状态、与她们对话，也可以轻轻推动世界。

> 当前版本：`v0.1.0` 初始 Demo。默认 Mock，不需要 API Key 就能跑通主流程。

## 现在能体验什么

- 3 个地点：杂物铺「拾光」、温室食堂「芽」、中央广场·水潭；
- 2 名可辨识 NPC：恋旧安静的莫莫、热心爱操心的利利；
- 状态驱动的自主决策：精力、饥饿、社交需求、人设权重、天气和公告共同参与效用计算；
- NPC 详情：当前行动理由、决策来源、需求值和最近记忆；
- 与 NPC 对话：有密钥时调用 DeepSeek V4 Flash，无密钥或调用失败时自动使用角色化 Mock；
- 世界干预：切换天气、张贴旧照片、送礼物；
- 自动 tick + 手动“推进一刻”，SSE 实时更新事件；
- SQLite 自动持久化，以及手动保存/恢复。

## 最快启动：Docker

要求：Docker Desktop / Docker Engine + Compose。

```bash
docker compose up --build
```

打开 <http://localhost:8080>。默认就是完整可体验的 Mock 模式。

停止服务：

```bash
docker compose down
```

世界数据保存在 Docker volume `inconewt-data` 中，普通的 `docker compose down` 不会删除它。

## 本地开发

要求：Node.js 22+、Python 3.12+。

后端：

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

前端另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。Vite 会把 `/api` 代理到本地 `8000` 端口。

## 填写 DeepSeek API Key

Demo 跑通后再开启真实 AI 即可，Key 不需要、也不应该写进任何源码。

1. 在项目根目录复制配置：`cp .env.example .env`；
2. 编辑 `.env`：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

3. 重启后端或运行 `docker compose up -d --build`；
4. 页面右上角显示 `DEEPSEEK V4` 即表示配置被识别；推进一刻或发起对话会产生真实调用。

模型名和端点依据 [DeepSeek 官方快速开始](https://api-docs.deepseek.com/)；本项目调用 OpenAI 兼容的 `/chat/completions` 接口。为控制 Demo 延迟，关闭 thinking、设置 15 秒超时、最多重试一次；网络错误、鉴权失败、超时或决策 JSON 校验失败都会自动落回 Mock。

安全底线：

- `.env`、数据库文件和构建产物已写入 `.gitignore`；
- Key 只由 Python 后端读取，前端响应和健康检查均不返回 Key；
- 浏览器只请求本项目 `/api`，不会直连 DeepSeek；
- `.env.example` 只包含空占位符，可以安全提交。

## NPC 为什么不是固定动画

每个 tick 的链路是：

```text
需求自然变化
  → 组合人设 / 状态 / 记忆 / 天气 / 公告
  → DeepSeek 结构化决策，或 Mock 效用决策
  → Pydantic 校验
  → 执行动作并改变位置、需求、心情
  → 写入最近记忆、SQLite 和 SSE 事件
```

Mock 模式也不是固定顺序：例如精力最低时休息、饥饿最高时去「芽」、社交需求升高时寻找另一位 NPC；莫莫与利利的人设权重不同，相同世界状态下也可能产生不同选择。贴出旧照片或切换为雾天会直接改变下一次决策上下文。

真实 AI 的三层提示词放在：

```text
backend/prompts/
├── world.md       # 共享世界观
├── format.md      # 结构化行动约束
└── npc/
    ├── momo.md    # 莫莫私有人设
    └── lili.md    # 利利私有人设
```

要改 NPC 口吻只改对应人设文件，不需要翻业务代码。

## 项目结构

```text
inconewt/
├── frontend/               # React + TypeScript + Vite；地图、详情、对话、干预
│   └── src/
│       ├── App.tsx         # 相关 UI 与交互集中，便于阅读主流程
│       ├── api.ts          # API 类型与请求封装
│       └── styles.css      # Demo 视觉系统与响应式布局
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI 路由、生命周期、自动 tick
│   │   ├── models.py       # 数据模型与初始化世界
│   │   ├── world.py        # 世界推进、动作执行、SSE
│   │   ├── ai.py           # DeepSeek / Mock 双模式
│   │   └── store.py        # SQLite 快照与存档
│   ├── prompts/            # 世界观、格式、NPC 私有人设
│   └── tests/              # 两个核心自动化测试
├── docker-compose.yml      # 后端 + Caddy 静态站/反代
├── .env.example
├── goal.md
└── outline.md
```

## API 一览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 服务状态与 AI 模式，不暴露 Key |
| GET | `/api/world` | 当前世界快照 |
| GET | `/api/npcs/{id}` | NPC 详情 |
| POST | `/api/world/tick` | 手动推进一刻 |
| POST | `/api/chat/{id}` | 与 NPC 对话 |
| POST | `/api/world/actions` | 天气、公告、礼物干预 |
| POST | `/api/world/save` | 建立手动存档 |
| POST | `/api/world/load` | 恢复最近手动存档 |
| GET | `/api/events` | SSE 世界事件 |

FastAPI 交互文档：启动后打开 <http://localhost:8000/docs>。

## 最小验证

项目只保留两项高价值后端测试，符合初始 Demo “不过度测试”的取舍：

```bash
cd backend
../.venv/bin/pytest
```

- 高优先级需求会改变 Mock 决策；
- 世界保存/恢复能往返一致。

前端生产构建：

```bash
cd frontend
npm run build
```

## 关键取舍

- **先用 React/CSS 地图，不上 Phaser**：初版重点是证明自主决策、对话、降级和持久化闭环；地图保留地点/NPC 结构，后续换 Phaser 不影响 API。
- **SQLite 保存整份 Pydantic JSON 快照**：比 MVP 阶段拆十几张表更容易阅读和迁移；要做检索与多人世界时再规范化。
- **聊天先非流式，事件使用 SSE**：状态更新需要实时，短对话暂时不值得引入另一套流式状态机。
- **两个 NPC 做深，不急着铺四个**：先验证莫莫/利利反差最大的角色链路；小柯、阿羯的数据和 prompt 可按同一结构补入。
- **不把 LLM 当唯一运行条件**：Mock 与真实 AI 共用同一 `Decision` 模型和动作执行器，断网时世界仍然成立。

### 一处适合现场演示的 AI 修改案例

在 `backend/prompts/npc/momo.md` 给莫莫增加一句新的说话禁忌，重启后端，再向她问同一问题；只改一份人设文件就能观察真实 DeepSeek 回复变化。若输出不是合法决策 JSON，`Decision` 校验会拒绝它并自动用 Mock 完成本次 tick，这也能现场解释为什么 AI 能接入、但不能越过业务规则。

## 后续版本

- `v0.2`：补小柯、阿羯与跨 NPC 互动；
- `v0.3`：引入 Phaser/Tiled 像素地图与移动动画；
- `v0.4`：短期记忆自动摘要为日记；
- `v0.5`：服务器域名、Caddy HTTPS 与 3–5 分钟演示视频。

本仓库当前不声明线上体验地址；在服务器执行 Docker 启动并把域名反代到 `8080` 即可发布。正式公网部署时，请由外层 Caddy/Nginx 配置 HTTPS、域名和访问日志策略。
