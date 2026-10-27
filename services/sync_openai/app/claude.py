"""Claude through the Anthropic API, for short latency-sensitive jobs such as understanding a spoken answer on a
live call. LLM_PROVIDER=anthropic with ANTHROPIC_API_KEY switches it on; CLAUDE_MODEL picks the model."""
import anthropic

from services.shared import config

DEFAULT_MODEL = "claude-haiku-5-5"   # fastest and cheapest Claude; set CLAUDE_MODEL=claude-sonnet-5-5 for more judgment
_client: anthropic.AsyncAnthropic | None = None


def _anthropic() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        # Someone is waiting on the phone line: a short timeout and one retry.
        _client = anthropic.AsyncAnthropic(timeout=6.0, max_retries=1)
    return _client


async def complete(messages: list[dict], schema: dict | None = None) -> str:
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in {"user", "assistant"}]
    output_config = {"effort": "low"}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    response = await _anthropic().messages.create(
        model=config.env("CLAUDE_MODEL") or DEFAULT_MODEL, max_tokens=1024,
        output_config=output_config, messages=turns, **({"system": system} if system else {}))
    if response.stop_reason in {"refusal", "max_tokens"}:
        raise ValueError(f"Claude stopped early: {response.stop_reason}")
    text = next((block.text for block in response.content if block.type == "text"), "").strip()
    if not text:
        raise ValueError("Claude returned no text")
    return text
