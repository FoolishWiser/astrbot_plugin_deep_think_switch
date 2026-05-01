# 🧠 DeepSeek 深度思考开关插件

> **astrbot_plugin_deep_think_switch** — 为 AstrBot 提供 DeepSeek 深度思考模式（`reasoning_effort="max"`）的一键开关，**仅单次对话生效**，不影响后续对话。

---

## 📦 安装

将插件目录放置到 AstrBot 的 `plugins/` 目录下，然后在仪表板中启用。

```
plugins/
└── astrbot_plugin_deep_think_switch/
    ├── main.py
    ├── metadata.yaml
    ├── README.md
    └── CHANGELOG.md
```

> 无需额外依赖。

---

## 🚀 使用方法

### 基本用法

直接在消息前加上 `/max`：

```
/max 请用中文解释量子纠缠的原理
```

插件会自动：
1. 检测到 `/max` 前缀
2. 剥离前缀，将实际内容发送给 LLM
3. 注入 `thinking.enabled` + `reasoning_effort="max"`
4. 响应后自动恢复原始配置

### 效果

```
用户: /max 请用中文解释量子纠缠的原理
🤔 思考: ...（DeepSeek 以最大力度深度推理）
助手: （深度思考后的回答）

用户: 继续解释一下
助手: （普通模式，无深度思考）
```

> 第二次对话不再使用深度思考模式，完全不影响后续对话。

---

## 🔧 工作原理

### 注入参数

根据 [DeepSeek Thinking Mode 官方文档](https://api-docs.deepseek.com/guides/thinking_mode)，插件向 API 请求注入以下参数：

| 参数 | 值 | 说明 |
|------|-----|------|
| `thinking` | `{"type": "enabled"}` | 显式启用思考模式 |
| `reasoning_effort` | `"max"` | 最大思考力度 |

### 参数传递路径

```
插件修改 provider_config["custom_extra_body"]
    → AstrBot 合并到 extra_body
        → OpenAI SDK 作为请求体顶层字段
            → DeepSeek API 接收并应用
```

### ⚠️ 重要限制

DeepSeek V3.2+ / V4 在 thinking mode 下进行 tool call 时，要求后续请求必须携带 `reasoning_content`。由于 AstrBot 的 `Message` 类未包含此字段，**thinking mode 与 tool_use 同时开启会导致 API 400 错误**。

因此，启用 `/max` 时插件会**临时禁用 tool_use**，避免产生需要 `reasoning_content` 的工具调用消息。这保证 `/max` 请求稳定返回深度思考结果，但代价是该次请求无法使用函数工具。

> 不影响非 `/max` 请求，工具调用在普通模式下正常工作。

### 工作流程

```
用户: /max 请用中文解释量子纠缠的原理
                  │
                  ▼
    ┌─────────────────────────────────┐
    │ on_llm_request 钩子             │
    │                                 │
    │ 1. 检测 /max 前缀               │
    │ 2. 剥离前缀，保留实际内容       │
    │ 3. 注入 thinking.enabled + max  │
    │ 4. 临时禁用 tool_use 🛡️        │
    └─────────────┬───────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────┐
    │ LLM API 请求 (no tool_use)      │
    │ extra_body: {                   │
    │   thinking: {type: enabled},    │
    │   reasoning_effort: max         │
    │ }                               │
    └─────────────┬───────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────┐
    │ on_llm_response 钩子            │
    │                                 │
    │ 1. 恢复原始 Provider 配置       │
    │ 2. tool_use 自动恢复（下一请求）│
    └─────────────────────────────────┘
```

---

## 📋 配置

无额外配置项。插件读取 AstrBot 的 Provider 配置中的 `custom_extra_body` 字段。

---

## 🔌 兼容性

| 模型 | 深度思考 | tool_use |
|------|---------|----------|
| `deepseek-v4-flash` | ✅ | ✅（/max 时暂停） |
| `deepseek-v4-pro` | ✅ | ✅（/max 时暂停） |
| `deepseek-chat` / `deepseek-reasoner` | ✅ | ✅（/max 时暂停） |

---

## 📄 文件结构

```
astrbot_plugin_deep_think_switch/
├── main.py          # 插件主逻辑
├── metadata.yaml     # 插件元数据
├── README.md         # 本文件
└── CHANGELOG.md      # 更新日志
```

---

## 📝 License

Apache License 2.0
