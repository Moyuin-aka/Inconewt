请从 move、work、rest、eat、chat、idle、observe 中选择一个行动，只输出一个 JSON 对象，不要 Markdown：
{"action":"work","target":"地点或 NPC id，也可为 null","say":"行动时可说的话","reason":"第一人称可解释理由，中文 40 字以内"}
行动必须能由当前状态解释，target 只能使用上下文提供的 id。
