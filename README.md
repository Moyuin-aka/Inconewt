# Inconnewt

Web 版 AI 小镇 Demo。居民会依据人设、需求、日程和记忆自主行动，未配置 AI 时可用 Mock 完整体验。

技术栈：React、Phaser、FastAPI、SQLite、Docker Compose。

角色精灵改编自 [Kenney RPG Urban Pack](https://kenney.nl/assets/rpg-urban-pack)，采用 CC0 许可。

## 启动

```bash
docker compose up --build
```

打开 <http://localhost:8080>。

停止服务：

```bash
docker compose down
```

## AI 配置

默认无需 API Key。需要启用 DeepSeek 时：

```bash
cp .env.example .env
```

在 `.env` 中设置：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
```

`.env` 不得提交到版本库；AI 调用失败时会自动回落到 Mock。

## 本地开发

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

前端地址：<http://localhost:5173>。

## 验证

```bash
cd backend
../.venv/bin/pytest

cd ../frontend
npm run build
```
