# 🧠 DeepSeek 深度思考开关插件

> **astrbot_plugin_deep_think_switch** — 为 AstrBot 提供 DeepSeek 深度思考模式（`reasoning_effort="max"`）的一键开关，**仅单次对话生效**，不影响后续对话。

---

## ✨ 功能

- **`/max 对话内容`** — 直接对当前消息开启 DeepSeek 最大思考力度模式
- **一次性生效** — 仅当前这一次 LLM 请求使用 `reasoning_effort="max"`，响应后自动恢复
- **`reasoning_content` 自动补全** — 修复 DeepSeek V3.2+ / V4 Thinking Mode 下 tool call 场景的 `reasoning_content` 缺失问题，防止 API 400 错误
- **零入侵** — 不修改 AstrBot 核心代码，完全通过插件钩子实现

---

## 📦 安装

将插件目录放置到 AstrBot 的 `plugins/` 目录下，然后在仪表板中启用。

```
plugins/
└── astrbot_plugin_deep_think_switch/
    ├── main.py
    ├── metadata.yaml
    └── README.md
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

## 🔧 技术细节

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

### reasoning_content 修复

DeepSeek V3.2+ 和 V4 在 thinking mode 下发生 tool call 时，后续请求的 `assistant` 消息**必须携带 `reasoning_content`**，否则 API 返回 400 错误。本插件通过以下方式解决：

1. **`on_llm_response`** — 缓存最近一次 thinking 响应的 `reasoning_content`
2. **`on_llm_request`** — 扫描历史消息中带 `tool_calls` 但缺 `reasoning_content` 的 assistant 消息，自动补全

### 兼容性

| 模型 | 状态 |
|------|------|
| `deepseek-v4-flash` | ✅ 完全兼容 |
| `deepseek-v4-pro` | ✅ 完全兼容 |
| `deepseek-chat` / `deepseek-reasoner` | ✅ 兼容 |

---

## 📋 命令

| 命令 | 说明 |
|------|------|
| `/max <内容>` | 对指定内容开启最大深度思考模式，仅本次生效 |

---

## 🗺️ 工作流程

```
用户: /max 请用中文解释量子纠缠的原理

                  │
                  ▼
    ┌─────────────────────────────┐
    │ on_llm_request 钩子         │
    │                             │
    │ 1. 检测 /max 前缀           │
    │ 2. 剥离前缀，保留实际内容   │
    │ 3. 修复历史 reasoning_content│
    │ 4. 注入 thinking + max      │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │ LLM API 请求                │
    │ extra_body: {               │
    │   thinking: {type: enabled},│
    │   reasoning_effort: max     │
    │ }                           │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │ on_llm_response 钩子        │
    │                             │
    │ 1. 缓存 reasoning_content   │
    │ 2. 恢复原始 Provider 配置   │
    └─────────────────────────────┘
                  │
                  ▼
              响应完成
```

---

## 📄 文件结构

```
astrbot_plugin_deep_think_switch/
├── main.py          # 插件主逻辑
├── metadata.yaml     # 插件元数据
└── README.md         # 本文件
```

---

## 🐛 已知问题 / 注意事项

- 插件依赖 `ProviderRequest.contexts` 来获取消息列表，请确保 AstrBot 版本支持此属性
- `reasoning_content` 缓存基于会话 ID，不同会话互不干扰
- 插件终止时会自动清理所有缓存和备份配置，不会留下残留状态

---

## 📝 License

MIT license
