// Inline Python scripts that boot a chat-console with a specific mock
// generator. Each constant produces a deterministic event stream that
// exercises a specific render path. Per [ENTERPRISE: tracker ref].

const HEADER = `
import asyncio
import json
import sys
sys.path.insert(0, "[ENTERPRISE: deployment root]/console")
from aiohttp import web
from app import build_app
from turns import TurnEvent
import os
PORT = int(os.environ["CONSOLE_PORT"])
HOST = os.environ.get("CONSOLE_HOST", "127.0.0.1")
`;

const RUN = `
app = build_app(generator=_gen)
web.run_app(app, host=HOST, port=PORT, print=lambda *a, **k: None)
`;

// Simple text-only response — for boot smoke.
export const SIMPLE_TEXT = HEADER + `
async def _gen(buf, prompt, **_kwargs):
    await buf.start()
    for word in ("hello", " from", " mock"):
        await buf.append(TurnEvent(type="token", data={"text": word}))
        await asyncio.sleep(0.005)
    await buf.finish()
` + RUN;

// Text + tool_call + tool_result + final text. Verifies the load-bearing
// "tool_result body inside tool-block" assertion (yesterday's bug class).
export const TEXT_TOOL_TEXT = HEADER + `
async def _gen(buf, prompt, **_kwargs):
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "Looking it up."}))
    await buf.append(TurnEvent(type="tool_call", data={
        "id": "tool_A", "name": "Bash",
        "input": {"command": "ls /tmp"}, "parent_tool_use_id": None,
    }))
    await buf.append(TurnEvent(type="tool_result", data={
        "tool_use_id": "tool_A",
        "content": "file1.txt\\nfile2.txt",
        "is_error": False, "parent_tool_use_id": None,
    }))
    for word in ("Found", " two", " files."):
        await buf.append(TurnEvent(type="token", data={"text": word}))
    await buf.finish()
` + RUN;

// Multi-burst text — text, tool, text, tool, text. Exploded-stream
// regression: each text-burst should be its own .text-block, distinct
// from tool-blocks rendered between them.
export const MULTI_BURST = HEADER + `
async def _gen(buf, prompt, **_kwargs):
    await buf.start()
    await buf.append(TurnEvent(type="token", data={"text": "First. "}))
    await buf.append(TurnEvent(type="tool_call", data={
        "id": "t1", "name": "Bash",
        "input": {"command": "x"}, "parent_tool_use_id": None,
    }))
    await buf.append(TurnEvent(type="tool_result", data={
        "tool_use_id": "t1", "content": "out1",
        "is_error": False, "parent_tool_use_id": None,
    }))
    await buf.append(TurnEvent(type="token", data={"text": "Second. "}))
    await buf.append(TurnEvent(type="tool_call", data={
        "id": "t2", "name": "Bash",
        "input": {"command": "y"}, "parent_tool_use_id": None,
    }))
    await buf.append(TurnEvent(type="tool_result", data={
        "tool_use_id": "t2", "content": "out2",
        "is_error": False, "parent_tool_use_id": None,
    }))
    await buf.append(TurnEvent(type="token", data={"text": "Third."}))
    await buf.finish()
` + RUN;

// Markdown table response — verifies marked.js GFM tables work.
export const MARKDOWN_TABLE = HEADER + `
async def _gen(buf, prompt, **_kwargs):
    await buf.start()
    text = (
        "| Col A | Col B |\\n"
        "|---|---|\\n"
        "| a1 | b1 |\\n"
        "| a2 | b2 |\\n"
    )
    await buf.append(TurnEvent(type="token", data={"text": text}))
    await buf.finish()
` + RUN;

// Slow generator that holds the connection long enough for a queue
// test to fire a second prompt during the in-flight window.
export const SLOW_TEXT = HEADER + `
async def _gen(buf, prompt, **_kwargs):
    await buf.start()
    for i in range(8):
        await buf.append(TurnEvent(type="token", data={"text": str(i) + " "}))
        await asyncio.sleep(0.15)
    await buf.finish()
` + RUN;
