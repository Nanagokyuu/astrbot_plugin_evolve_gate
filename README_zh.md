# astrbot_plugin_evolve_gate

面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的有界闭环自进化插件 —— **聊天窗口零斜杠命令**。

为了避免直接修改代码或无限追加 System Prompt 规则导致的人设漂移与上下文膨胀，**EvolveGate** 将在线自进化严格限制在以下三层：

1. **L0 有界数值参数**：所有可调参数均带硬上下界 `[min, max]` 与单周期最大步长 `step`。
2. **零和黄金样本池**：固定容量（默认 10 条）高质量对话样本，超出上限时按评分淘汰最低分条目。
3. **回归门禁 + 48 小时自动回滚**：任何参数调整必须通过所有已注册回归门禁才能生效；应用后在观察窗口内若错误率明显恶化，自动回滚至基线快照。

## 为什么不在聊天里加斜杠命令？

在 QQ / Telegram 对话中敲 `/evolve` 或 `/rollback` 会瞬间打破伴侣机器人的真实感与沉浸感。EvolveGate 刻意**不注册任何 `@filter.command`**，而是通过以下方式观测与控制：

- **内置独立 Web 看板**：默认 `http://127.0.0.1:8557`（可在插件配置中自定义端口与监听地址）
- **命令行工具**：`python cli.py <status | check | apply | rollback>`
- **宿主插件扩展接口（`evolve-gate.v1`）**：其他插件可注册自己的可调参数空间、回归门禁与遥测增强器。

## 配置项说明

- `dashboard_enabled` (`true`) / `dashboard_host` (`127.0.0.1`) / `dashboard_port` (`8557`)
- `evolution_interval_hours` (`24`)：自动进化周期（小时）
- `auto_apply_passed_proposals` (`true`)：门禁通过后是否自动应用
- `auto_rollback_hours` (`48`)：自动回滚观察窗口（小时）
- `max_golden_examples` (`10`)：零和样本池最大容量
- `inject_golden_examples` (`true`)：是否在请求时注入最多 2 条黄金样本

## 开源协议

MIT
