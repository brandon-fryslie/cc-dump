"""Copilot provider adapter for Anthropic-compatible client traffic."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from cc_dump.core.token_counter import count_tokens
from cc_dump.proxies.copilot.api_config import (
    CopilotAuthConfig,
    build_copilot_headers,
    resolve_copilot_base_url,
)
from cc_dump.proxies.copilot.token_manager import (
    GITHUB_API_BASE_URL,
    build_github_headers,
    resolve_copilot_token,
)
from cc_dump.proxies.copilot.translation import (
    AnthropicStreamState,
    translate_chunk_to_anthropic_events,
    translate_error_to_anthropic,
    translate_models_to_anthropic,
    translate_stream_error_to_anthropic,
    translate_to_anthropic,
    translate_to_openai,
)
from cc_dump.proxies.runtime import ProxyRuntimeSnapshot


@dataclass(frozen=True)
class PreparedCopilotRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]
    stream: bool


@dataclass(frozen=True)
class PreparedCopilotModelsRequest:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class PreparedCopilotSimpleRequest:
    url: str
    headers: dict[str, str]
    method: str = "GET"


def _contains_image_content(messages: object) -> bool:
    if not isinstance(messages, list):
        return False
    stack = list(messages)
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("type") == "image":
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _is_agent_call(messages: object) -> bool:
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", ""))
        if role in {"assistant", "tool"}:
            return True
    return False


def prepare_messages_request(
    *,
    snapshot: ProxyRuntimeSnapshot,
    anthropic_payload: dict[str, Any],
) -> tuple[PreparedCopilotRequest | None, str | None]:
    openai_payload = translate_to_openai(anthropic_payload)
    openai_payload["stream"] = bool(anthropic_payload.get("stream", False))
    token, error = resolve_copilot_token(snapshot)
    if error is not None:
        return None, error

    auth = CopilotAuthConfig(
        token=token,
        account_type=snapshot.get_text("proxy_copilot_account_type", "individual"),
        base_url=snapshot.get_text("proxy_copilot_base_url"),
        vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
    )
    base_url = resolve_copilot_base_url(auth)
    vision = _contains_image_content(anthropic_payload.get("messages"))
    is_agent = _is_agent_call(openai_payload.get("messages"))
    headers = build_copilot_headers(
        config=auth,
        vision=vision,
        agent_initiator=is_agent,
    )
    headers["accept"] = "text/event-stream" if bool(openai_payload.get("stream")) else "application/json"
    return (
        PreparedCopilotRequest(
            url=f"{base_url}/chat/completions",
            headers=headers,
            body=openai_payload,
            stream=bool(openai_payload.get("stream")),
        ),
        None,
    )


def prepare_openai_chat_request(
    *,
    snapshot: ProxyRuntimeSnapshot,
    openai_payload: dict[str, Any],
) -> tuple[PreparedCopilotRequest | None, str | None]:
    token, error = resolve_copilot_token(snapshot)
    if error is not None:
        return None, error
    auth = CopilotAuthConfig(
        token=token,
        account_type=snapshot.get_text("proxy_copilot_account_type", "individual"),
        base_url=snapshot.get_text("proxy_copilot_base_url"),
        vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
    )
    base_url = resolve_copilot_base_url(auth)
    messages = openai_payload.get("messages", [])
    vision = _contains_image_content(messages)
    is_agent = _is_agent_call(messages)
    headers = build_copilot_headers(
        config=auth,
        vision=vision,
        agent_initiator=is_agent,
    )
    stream = bool(openai_payload.get("stream"))
    headers["accept"] = "text/event-stream" if stream else "application/json"
    return (
        PreparedCopilotRequest(
            url=f"{base_url}/chat/completions",
            headers=headers,
            body=openai_payload,
            stream=stream,
        ),
        None,
    )


def prepare_openai_embeddings_request(
    *,
    snapshot: ProxyRuntimeSnapshot,
    openai_payload: dict[str, Any],
) -> tuple[PreparedCopilotRequest | None, str | None]:
    token, error = resolve_copilot_token(snapshot)
    if error is not None:
        return None, error
    auth = CopilotAuthConfig(
        token=token,
        account_type=snapshot.get_text("proxy_copilot_account_type", "individual"),
        base_url=snapshot.get_text("proxy_copilot_base_url"),
        vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
    )
    base_url = resolve_copilot_base_url(auth)
    headers = build_copilot_headers(
        config=auth,
        vision=False,
        agent_initiator=False,
    )
    headers["accept"] = "application/json"
    return (
        PreparedCopilotRequest(
            url=f"{base_url}/embeddings",
            headers=headers,
            body=openai_payload,
            stream=False,
        ),
        None,
    )


def prepare_models_request(
    *,
    snapshot: ProxyRuntimeSnapshot,
) -> tuple[PreparedCopilotModelsRequest | None, str | None]:
    token, error = resolve_copilot_token(snapshot)
    if error is not None:
        return None, error
    auth = CopilotAuthConfig(
        token=token,
        account_type=snapshot.get_text("proxy_copilot_account_type", "individual"),
        base_url=snapshot.get_text("proxy_copilot_base_url"),
        vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
    )
    base_url = resolve_copilot_base_url(auth)
    headers = build_copilot_headers(config=auth, vision=False, agent_initiator=False)
    headers["accept"] = "application/json"
    return (
        PreparedCopilotModelsRequest(
            url=f"{base_url}/models",
            headers=headers,
        ),
        None,
    )


def prepare_usage_request(
    *,
    snapshot: ProxyRuntimeSnapshot,
) -> tuple[PreparedCopilotSimpleRequest | None, str | None]:
    github_token = snapshot.get_text("proxy_copilot_github_token")
    if not github_token:
        return None, "Missing proxy_copilot_github_token for /usage"
    headers = build_github_headers(
        github_token,
        vscode_version=snapshot.get_text("proxy_copilot_vscode_version", "1.99.0") or "1.99.0",
    )
    return (
        PreparedCopilotSimpleRequest(
            url=f"{GITHUB_API_BASE_URL}/copilot_internal/user",
            headers=headers,
            method="GET",
        ),
        None,
    )


def translate_non_stream_response(
    openai_payload: dict[str, Any],
) -> dict[str, Any]:
    return translate_to_anthropic(openai_payload)


def translate_models_response(
    copilot_models_payload: dict[str, Any],
) -> dict[str, Any]:
    return translate_models_to_anthropic(copilot_models_payload)


def translate_error_response(
    upstream_error_payload: dict[str, Any],
    *,
    fallback_message: str,
) -> dict[str, Any]:
    return translate_error_to_anthropic(
        upstream_error_payload,
        fallback_message=fallback_message,
    )


def stream_error_event() -> dict[str, Any]:
    return translate_stream_error_to_anthropic()


def count_tokens_for_messages(anthropic_payload: dict[str, Any]) -> int:
    """Approximate /v1/messages/count_tokens for Copilot-backed requests.

    Mirrors the high-level heuristic policy from the reference implementation.
    """
    try:
        openai_payload = translate_to_openai(anthropic_payload)
        payload_str = json.dumps(openai_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        estimated = count_tokens(payload_str)

        tools = anthropic_payload.get("tools", [])
        if isinstance(tools, list) and tools:
            anthropic_beta = str(anthropic_payload.get("_anthropic_beta", "") or "")
            mcp_tool_exists = anthropic_beta.startswith("claude-code") and any(
                isinstance(tool, dict)
                and isinstance(tool.get("name"), str)
                and tool.get("name", "").startswith("mcp__")
                for tool in tools
            )
            if not mcp_tool_exists:
                model = str(anthropic_payload.get("model", "")).lower()
                if model.startswith("claude"):
                    estimated += 346
                elif model.startswith("grok"):
                    estimated += 480

        model = str(anthropic_payload.get("model", "")).lower()
        multiplier = 1.0
        if model.startswith("claude"):
            multiplier = 1.15
        elif model.startswith("grok"):
            multiplier = 1.03
        final_count = int(round(max(1, estimated * multiplier)))
        return final_count
    except Exception:
        # // [LAW:single-enforcer] Token-count endpoint owns fallback contract for malformed payloads.
        return 1


def stream_state() -> AnthropicStreamState:
    return AnthropicStreamState()


def translate_stream_chunk(
    *,
    chunk_payload: dict[str, Any],
    state: AnthropicStreamState,
) -> list[dict[str, Any]]:
    return translate_chunk_to_anthropic_events(chunk_payload, state)
