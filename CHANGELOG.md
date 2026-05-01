# Changelog

## [1.0.1] — 2026-04-26

### Added
- CHANGELOG.md 文件

### Changed
- 重构插件核心逻辑：从 `on_llm_request` 直接检测 `/max` 前缀，移除命令处理器
- 启用 thinking mode 时临时禁用 tool_use，防止 DeepSeek API 400 错误（`reasoning_content` 缺失）

### Fixed
- 修复 `AttributeError: 'ProviderRequest' object has no attribute 'messages'` — 改用 `req.contexts`
- 修复 `All chat models failed: BadRequestError`（400 Missing reasoning_content）— 临时禁用 tool_use 规避

### Removed
- 移除 `_last_reasoning_cache` 缓存机制（因不覆盖 tool loop 子请求，无法彻底修复）
- 移除命令处理器 `@filter.command("max")`（改为纯钩子实现）

---

## [1.0.0] — 2026-04-25

### Added
- 初始版本发布
- 支持 `/max 对话内容` 直接开启 DeepSeek 深度思考模式
- 注入 `thinking.enabled` + `reasoning_effort="max"`
- 响应后自动恢复原始 Provider 配置
- 一次性生效，不影响后续对话
