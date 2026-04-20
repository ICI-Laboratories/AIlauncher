from __future__ import annotations

from typing import Any


def render_openai_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                parts.append(str(item))
                continue

            item_type = item.get("type")
            if item_type in {"text", "input_text"}:
                text = item.get("text", "")
                if text:
                    parts.append(str(text))
            elif item_type in {"image_url", "input_image"}:
                image_payload = item.get("image_url") or item.get("image") or {}
                if isinstance(image_payload, dict):
                    url = image_payload.get("url", "image")
                else:
                    url = image_payload or "image"
                parts.append(f"[image: {url}]")
            elif "text" in item:
                parts.append(str(item["text"]))
        return "\n".join(part for part in parts if part)
    return str(content)


def split_system_prompt_and_transcript(
    messages: list[dict[str, Any]],
) -> tuple[str | None, str]:
    system_parts: list[str] = []
    conversation: list[str] = []
    last_role: str | None = None

    for message in messages:
        role = str(message.get("role", "user"))
        content = render_openai_content(message.get("content"))

        if role in {"system", "developer"}:
            if content:
                system_parts.append(content)
            continue

        label = {
            "assistant": "Assistant",
            "tool": "Tool",
            "user": "User",
        }.get(role, role.title())
        conversation.append(f"{label}: {content}".rstrip())
        last_role = role

    if last_role != "assistant":
        conversation.append("Assistant:")

    system_prompt = "\n\n".join(part for part in system_parts if part) or None
    transcript = "\n".join(part for part in conversation if part)
    return system_prompt, transcript


def to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        normalized.append(
            {
                "role": message.get("role", "user"),
                "content": render_openai_content(message.get("content")),
            }
        )
    return normalized
