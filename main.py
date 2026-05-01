"""
deep_think_switch - AstrBot 插件
功能: 发送 "/max 对话内容" 直接对"对话内容"开启 DeepSeek 深度思考模式，
      仅当前这一次生效，不影响后续对话。

核心机制:
1. 用户发送 "/max 对话内容"
2. on_llm_request 检测到 /max 前缀，剥离前缀，注入 thinking.enabled + reasoning_effort=max
3. 为防止 DeepSeek API 400 错误（tool call 时缺少 reasoning_content），
   临时禁用该请求的 function tool，避免模型产生 tool_call
4. 响应后自动恢复原始配置和 tool 设置

当不使用 thinking mode 时，tool_use 正常工作，不受影响。

参考: https://api-docs.deepseek.com/guides/thinking_mode
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
        self._backup_configs: dict[str, tuple[Any, Any]] = {}

        # 标记当前请求是否需要恢复 tool
        self._restore_tool_sessions: set[str] = set()

    # ==================== LLM 请求钩子 ====================

    @filter.on_llm_request()
    async def inject_and_fix(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """在 LLM 请求前，检查是否以 /max 开头，若是则注入深度思考参数。"""
        session_id = event.session_id

        # 获取最新一条用户消息
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

        # 获取当前使用的 LLM Provider
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
            # ===== 1. 备份并注入 thinking 参数 =====
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

            # ===== 2. 临时禁用 tool_use，避免 reasoning_content 缺失 =====
            if req.func_tool:
                self._restore_tool_sessions.add(session_id)
                req.func_tool = None
                logger.info(
                    f"🔧 [deep_think_switch] 已临时禁用 tool_use（会话 {session_id}），"
                    f"防止 thinking mode 下工具调用导致 400 错误"
                )

            logger.info(
                f"🧠 [deep_think_switch] 会话 {session_id} "
                f"已为消息「{actual_content[:40]}...」注入 thinking=enabled + reasoning_effort='max'"
            )
        except Exception as e:
            logger.error(f"[deep_think_switch] 注入深度思考参数失败: {e}")

    @filter.on_llm_response()
    async def restore_and_cache(
        self, event: AstrMessageEvent, resp: LLMResponse
    ) -> None:
        """在 LLM 响应后，恢复 Provider 的原始配置和 tool 设置。"""
        session_id = event.session_id

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

        # ==== 清理 tool 恢复标记 ====
        self._restore_tool_sessions.discard(session_id)

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
        self._restore_tool_sessions.clear()
        logger.info("[deep_think_switch] 插件已停止。")
