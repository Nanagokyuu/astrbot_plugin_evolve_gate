# astrbot_plugin_evolve_gate

**English** | [简体中文](README_zh.md)

Bounded, regression-gated self-evolution plugin for [AstrBot](https://github.com/AstrBotDevs/AstrBot) — with **zero chat slash commands**.

Instead of mutating your bot's core code or endlessly appending system prompt rules (which causes persona drift and context bloat), **EvolveGate** restricts online adaptation to:

1. **L0 Bounded Numeric Parameters** — Tunable parameters with hard `[min, max]` clamps and small per-cycle `step` limits.
2. **Zero-Sum Golden Example Pool** — Fixed-capacity high-signal conversation examples (`max_golden_examples`, default `10`) with score-based eviction.
3. **Regression Gates + 48h Auto-Rollback** — Every parameter proposal must pass all registered regression gates before taking effect, and automatically rolls back if post-apply error rates regress within the observation window.

## Why Zero Slash Commands?

Adding `/evolve` or `/rollback` commands inside QQ/Telegram chat breaks immersion for companion bots. EvolveGate deliberately registers **no `@filter.command` handlers** and is operated via:

- **Built-in Web Dashboard**: `http://0.0.0.0:8557` (auto light/dark theme, bilingual ZH/EN UI, configurable host & port)
- **CLI**: `python cli.py <status | check | apply | rollback>`
- **Host Plugin API (`evolve-gate.v1`)**: Any AstrBot plugin can register tunable parameter spaces, regression gates, and telemetry enrichers.

## Installation

Clone or copy this repository into your AstrBot `data/plugins/astrbot_plugin_evolve_gate` directory and restart AstrBot (or install from the AstrBot WebUI plugin manager).

## Configuration

| Key | Default | Description |
| --- | --- | --- |
| `enabled` | `true` | Enable telemetry & periodic evolution |
| `dashboard_enabled` | `true` | Start built-in Web Dashboard |
| `dashboard_host` | `0.0.0.0` | Dashboard bind host (set `127.0.0.1` for local-only) |
| `dashboard_port` | `8557` | Dashboard bind port |
| `evolution_interval_hours` | `24` | Hours between automatic evolution cycles |
| `auto_apply_passed_proposals` | `true` | Automatically apply proposals that pass all gates |
| `auto_rollback_hours` | `48` | Observation window before a snapshot is considered stable |
| `max_golden_examples` | `10` | Maximum zero-sum pool size |
| `inject_golden_examples` | `true` | Inject up to 2 golden examples into `req.system_prompt` |

## Host Plugin Integration (`evolve-gate.v1`)

```python
from plugins.evolve_gate.api import TunableParamSpec, get_evolve_gate_api

api = get_evolve_gate_api()
api.register_tunable_space(
    "my_plugin",
    specs=[
        TunableParamSpec("reply_temp", "float", 0.5, 0.9, step=0.05, description="Reply temperature"),
    ],
    getter=lambda: {"reply_temp": 0.7},
    applier=lambda params: {"reply_temp": params["reply_temp"]},
)
```

## License

MIT
