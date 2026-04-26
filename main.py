"""
deep_think_switch - AstrBot 插件
功能: 发送 "/max 对话内容" 直接对"对话内容"开启 DeepSeek 深度思考模式，
      仅当前这一次生效，不影响后续对话。

同时修复 DeepSeek Thinking Mode 下 tool call 场景的 reasoning_content 缺失问题：
- DeepSeek V3.2+ / V4 在 thinking mode 中发生 tool call 时，
  后续请求必须携带 assistant 消息的 reasoning_content 字段。
- 该插件缓存最近一次思考模式的 reasoning_content，
  并在 on_llm_request 中自动补全历史中缺失的 reasoning_content。

参考: https://api-docs.deepseek.com/guides/thinking_mode

官方文档 (Thinking Mode):
- Thinking Toggle: extra_body={"thinking": {"type": "enabled"}}
- Effort Control: reasoning_effort = "high" | "max"
- 有 tool call 时 reasoning_content 必须在后续请求中原样携带

工作方式:
1. 用户发送 "/max 对话内容"
2. on_llm_request 钩子检测到最新用户消息以 "/max" 开头
3. 从消息内容中剥离 "/max" 前缀
4. 注入 thinking=enabled + reasoning_effort="max"
5. 同时修复历史消息中缺少的 reasoning_content
6. on_llm_response 缓存返回的 reasoning_content
7. 仅当前这次 LLM 请求生效，响应后自动恢复
"""

from collections.abc import AsyncGenerator
from copy import deepcopy
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register


@register(
    "deep_think_switch",
    "ZYT",
    "发送 /max 对话内容 直接对此内容开启 DeepSeek 深度思考模式（Max），仅当前一次生效。",
    "1.0.0",
)
class DeepThinkSwitchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.context = context

        # 存储备份的 provider 配置，用于请求完成后恢复
        # backup_key -> (provider, original_custom_extra_body)
        self._backup_configs: dict[str, tuple[Any, Any]] = {}

        # ===== reasoning_content 修复相关 =====
        # 缓存最近一次 thinking mode 下 assistant 回复的 reasoning_content
        # 用于在后续请求中补全历史消息
        # session_id -> {"role": "assistant", "reasoning_content": "...", ...}
        self._last_reasoning_cache: dict[str, dict[str, Any]] = {}

    # ==================== LLM 请求钩子 ====================

    @filter.on_llm_request()
    async def inject_and_fix(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """在 LLM 请求前，注入深度思考参数，并修复历史消息中缺失的 reasoning_content。"""
        session_id = event.session_id

        # ==== 第一步：检查并修复历史消息中缺失的 reasoning_content ====
        self._fix_reasoning_content_in_contexts(session_id, req)

        # ==== 第二步：检查是否以 /max 开头 ====
        # 注意：req.messages 不存在，使用 req.contexts 代替
        # contexts 是 OpenAI 格式的消息列表，最后一条是用户消息
        if not req.contexts:
            return

        last_msg = req.contexts[-1]
        if last_msg.get("role") != "user":
            return

        content: str = last_msg.get("content", "")
        if not isinstance(content, str):
            return

        stripped = content.lstrip()
        if not stripped.startswith("/max"):
            return

        # 剥离 /max 前缀，获取实际对话内容
        actual_content = stripped[4:].lstrip()

        if not actual_content:
            return

        # 修改消息内容，去掉 /max 前缀
        last_msg["content"] = actual_content

        # ==== 第三步：注入深度思考参数 ====
        provider = self.context.get_using_provider(event.unified_msg_origin)
        if not provider:
            logger.warning(
                "[deep_think_switch] 未能获取 LLM Provider，跳过注入。"
            )
            return

        if not hasattr(provider, "provider_config"):
            logger.warning(
                "[deep_think_switch] 当前 Provider 不支持 provider_config，跳过注入。"
            )
            return

        provider_config: dict = provider.provider_config

        try:
            original_extra_body = provider_config.get("custom_extra_body", {})
            if not isinstance(original_extra_body, dict):
                original_extra_body = {}

            backup_key = f"{session_id}_{id(last_msg)}"
            self._backup_configs[backup_key] = (
                provider,
                deepcopy(original_extra_body),
            )

            new_extra_body = deepcopy(original_extra_body)
            new_extra_body["thinking"] = {"type": "enabled"}
            new_extra_body["reasoning_effort"] = "max"
            provider_config["custom_extra_body"] = new_extra_body

            logger.info(
                f"🧠 [deep_think_switch] 会话 {session_id} "
                f"已为消息「{actual_content[:30]}...」注入 thinking=enabled + reasoning_effort='max'"
            )
        except Exception as e:
            logger.error(f"[deep_think_switch] 注入深度思考参数失败: {e}")

    def _fix_reasoning_content_in_contexts(
        self, session_id: str, req: ProviderRequest
    ) -> None:
        """修复上下文中 assistant 消息缺失的 reasoning_content。

        DeepSeek V3.2+ / V4 在 thinking mode + tool call 场景下，
        如果 assistant 消息包含 tool_calls 但没有 reasoning_content，
        API 会返回 400 错误。

        策略：遍历 contexts，对每个带 tool_calls 的 assistant 消息，
        如果缺少 reasoning_content，从缓存中补全。
        """
        cached = self._last_reasoning_cache.get(session_id)
        if not cached:
            return

        cached_reasoning = cached.get("reasoning_content", "")
        if not cached_reasoning:
            return

        contexts = req.contexts
        if not contexts:
            return

        fixed_count = 0
        for msg in contexts:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            # 只修复带 tool_calls 但缺少 reasoning_content 的消息
            if "tool_calls" not in msg or not msg["tool_calls"]:
                continue
            if msg.get("reasoning_content"):
                continue  # 已经有 reasoning_content，跳过

            # 补全 reasoning_content
            msg["reasoning_content"] = cached_reasoning
            fixed_count += 1

        if fixed_count > 0:
            logger.info(
                f"🔧 [deep_think_switch] 已修复 {fixed_count} 条 assistant 消息的 reasoning_content（会话 {session_id}）"
            )

    @filter.on_llm_response()
    async def restore_and_cache(
        self, event: AstrMessageEvent, resp: LLMResponse
    ) -> None:
        """在 LLM 响应后，恢复 Provider 的原始配置，并缓存 reasoning_content。"""
        session_id = event.session_id

        # ==== 缓存 reasoning_content ====
        if resp and resp.reasoning_content:
            self._last_reasoning_cache[session_id] = {
                "reasoning_content": resp.reasoning_content,
            }
            logger.debug(
                f"💾 [deep_think_switch] 已缓存会话 {session_id} 的 reasoning_content "
                f"({len(resp.reasoning_content)} chars)"
            )

        # ==== 恢复 Provider 配置 ====
        keys_to_delete = []
        for backup_key, (provider, original_extra_body) in self._backup_configs.items():
            if backup_key.startswith(f"{session_id}_"):
                try:
                    if hasattr(provider, "provider_config"):
                        provider.provider_config["custom_extra_body"] = original_extra_body
                        logger.info(
                            f"✅ [deep_think_switch] 已恢复会话 {session_id} 的 Provider 配置"
                        )
                except Exception as e:
                    logger.error(
                        f"[deep_think_switch] 恢复 Provider 配置失败: {e}"
                    )
                keys_to_delete.append(backup_key)

        for key in keys_to_delete:
            self._backup_configs.pop(key, None)

    # ==================== 生命周期管理 ====================

    async def terminate(self) -> None:
        """插件停止时清理所有状态"""
        logger.info("[deep_think_switch] 插件正在停止，清理状态...")

        for backup_key, (provider, original_extra_body) in list(self._backup_configs.items()):
            try:
                if hasattr(provider, "provider_config"):
                    provider.provider_config["custom_extra_body"] = original_extra_body
                    logger.info(
                        f"✅ [deep_think_switch] 已恢复 Provider 配置 (key={backup_key})"
                    )
            except Exception as e:
                logger.error(
                    f"[deep_think_switch] 恢复 Provider 配置失败: {e}"
                )

        self._backup_configs.clear()
        self._last_reasoning_cache.clear()
        logger.info("[deep_think_switch] 插件已停止。")
