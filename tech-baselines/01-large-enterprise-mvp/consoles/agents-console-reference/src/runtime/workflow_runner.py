"""Pure helpers for workflow step execution.

`render_prompt` substitutes `{input}` (workflow's initial input) and
`{prev_output}` (last completed step's text output) into a step's prompt
template. Plain string replacement — no `str.format`, no regex — so:

  - Unknown placeholders pass through verbatim (an agent prompt using
    `{file_path}` for its own purposes survives untouched).
  - Unbalanced `{` / `}` in the user's input or the prev step's output
    don't blow up the renderer.

Kept as a separate module so it can be unit-tested without spinning up
the workflow daemon.
"""
from __future__ import annotations


def render_prompt(template: str, *, input: str, prev_output: str) -> str:
    """Substitute `{input}` and `{prev_output}` literally. Multi-line
    outputs preserved as-is — no escaping or trimming."""
    return template.replace("{input}", input).replace("{prev_output}", prev_output)


def extract_text_output(events: list) -> str:
    """Concatenate the `text` field of every `token` event in order.
    Tool events and other types are excluded — token deltas are pure
    assistant text. Used by the workflow daemon to derive the
    `prev_output` for the next step."""
    parts: list[str] = []
    for ev in events:
        if ev.type == "token":
            text = ev.data.get("text") if isinstance(ev.data, dict) else None
            if text:
                parts.append(text)
    return "".join(parts)
