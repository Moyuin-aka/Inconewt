请从 move、work、rest、eat、chat、idle、observe、visit、activity 中选择一个行动，只输出一个 JSON 对象，不要 Markdown：
{"action":"activity","target":"地点或 NPC id，也可为 null","activity_id":"地点特有动作 id，也可为 null","say":"行动时可说的话","reason":"第一人称可解释理由，中文 40 字以内"}
行动必须能由当前状态与今日计划解释，target 和 activity_id 只能使用上下文提供的 id。参考最近 3 次行动；不得连续给出完全相同的 action 与 reason，重复活动必须说明新的进展。
当前事实卡是唯一事实边界；reason 与 say 不得新增事实卡、记忆和可用列表之外的人名、地点、物品或事件。
