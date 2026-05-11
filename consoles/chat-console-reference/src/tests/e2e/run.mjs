// e2e smoke runner — boots a real chat console with a mock generator
// per scenario, drives puppeteer, asserts DOM. Per [ENTERPRISE: tracker ref].
//
// Run: node console/tests/e2e/run.mjs
//      node console/tests/e2e/run.mjs --filter=multi-burst
// Output: TAP-ish "ok" / "not ok" lines + a summary.

import puppeteer from "/tmp/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { setTimeout as sleep } from "node:timers/promises";
import { bootMockConsole } from "./server-fixture.mjs";
import {
    SIMPLE_TEXT,
    TEXT_TOOL_TEXT,
    MULTI_BURST,
    MARKDOWN_TABLE,
    SLOW_TEXT,
} from "./mock-generators.mjs";

const filterArg = process.argv.find((a) => a.startsWith("--filter="));
const FILTER = filterArg ? filterArg.split("=")[1] : null;
const RUN_LIVE = process.argv.includes("--live");

// Live-stack endpoints (chat console + agents service + Kroki). Probed
// at start; tests that depend on them skip cleanly if unreachable.
const CONSOLE_URL = process.env.E2E_CHAT_URL  || "http://localhost:8080";
const AGENTS_URL  = process.env.E2E_AGENTS_URL || "http://localhost:8091";

const tests = [];
function test(name, fn, opts = {}) { tests.push({ name, fn, live: !!opts.live }); }
function liveTest(name, fn) { test(name, fn, { live: true }); }

async function probe(url) {
    try {
        const r = await fetch(url, { signal: AbortSignal.timeout(2000) });
        return r.ok;
    } catch { return false; }
}

function assert(cond, msg) {
    if (!cond) throw new Error("assertion failed: " + msg);
}

async function withConsole(script, fn) {
    const ctx = await bootMockConsole({ script });
    try { return await fn(ctx); }
    finally { ctx.kill(); }
}

async function withPage(baseUrl, fn) {
    const browser = await puppeteer.launch({
        headless: "new",
        args: ["--no-sandbox", "--disable-setuid-sandbox"],
    });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (err) => errors.push(err.message));
    try {
        await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
        await page.waitForSelector("#prompt-input");
        return await fn(page, errors);
    } finally {
        await browser.close();
    }
}

async function submit(page, prompt) {
    await page.click("#prompt-input");
    await page.type("#prompt-input", prompt);
    await Promise.all([
        page.click("#send-btn"),
        page.waitForSelector(".turn-status-footer.completed", { timeout: 10000 }),
    ]);
}

// ---- scenarios ----

test("boot-smoke", async () => {
    await withConsole(SIMPLE_TEXT, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page, errors) => {
            const title = await page.title();
            assert(title === "chat console", `title=${title}`);
            const sidebar = await page.$(".sidebar");
            assert(sidebar !== null, "sidebar present");
            const input = await page.$("#prompt-input");
            assert(input !== null, "composer input present");
            const sendable = await page.evaluate(() => !document.getElementById("send-btn").disabled);
            assert(sendable, "send button enabled");
            assert(errors.length === 0, "no page errors: " + errors.join("|"));
        });
    });
});

test("synchronous-turn-renders-fully", async () => {
    await withConsole(TEXT_TOOL_TEXT, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page) => {
            await submit(page, "test");
            // text-block(s)
            const textBlocks = await page.$$(".turn-events .text-block");
            assert(textBlocks.length >= 1, "at least one .text-block");
            // tool-block with body INSIDE (yesterday's bug regression)
            const tb = await page.$('.turn-events .tool-block[data-tool-use-id="tool_A"]');
            assert(tb !== null, "tool-block matched by tool_use_id");
            const bodyInside = await page.$(
                '.turn-events .tool-block[data-tool-use-id="tool_A"] .tool-body'
            );
            assert(bodyInside !== null, "tool-body inside its tool-block");
            const bodyText = await page.evaluate((el) => el.textContent, bodyInside);
            assert(bodyText.includes("file1.txt"), "tool-body content rendered");
            // No orphan tool-blocks
            const orphans = await page.$$(".turn-events .tool-block.orphan");
            assert(orphans.length === 0, "no orphan tool-blocks");
            // Footer completed
            const completed = await page.$(".turn-status-footer.completed");
            assert(completed !== null, "footer marked completed");
        });
    });
});

test("multi-burst-text", async () => {
    await withConsole(MULTI_BURST, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page) => {
            await submit(page, "test");
            // Three distinct .text-block elements (one per burst)
            const blocks = await page.$$(".turn-events .text-block");
            assert(blocks.length === 3, `expected 3 text-blocks, got ${blocks.length}`);
            const texts = await Promise.all(
                blocks.map((el) => page.evaluate((e) => e.textContent.trim(), el))
            );
            assert(texts[0].includes("First"), `first burst: ${texts[0]}`);
            assert(texts[1].includes("Second"), `second burst: ${texts[1]}`);
            assert(texts[2].includes("Third"), `third burst: ${texts[2]}`);
            // Tool-blocks interleaved BETWEEN text-blocks (DOM order)
            const order = await page.evaluate(() => {
                const events = document.querySelector(".turn-events");
                return [...events.children].map((c) => c.className.split(" ")[0]);
            });
            // Expected pattern: text-block, tool-block, text-block, tool-block, text-block
            const expected = ["text-block", "tool-block", "text-block", "tool-block", "text-block"];
            assert(
                JSON.stringify(order) === JSON.stringify(expected),
                `arrival order wrong: got ${order.join(",")}`,
            );
        });
    });
});

test("markdown-table-rendering", async () => {
    await withConsole(MARKDOWN_TABLE, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page) => {
            await submit(page, "test");
            const table = await page.$(".text-block table");
            assert(table !== null, "table element rendered");
            const headers = await page.$$eval(".text-block table thead th",
                (els) => els.map((e) => e.textContent.trim()));
            assert(JSON.stringify(headers) === JSON.stringify(["Col A", "Col B"]),
                `headers: ${headers.join("|")}`);
            const cells = await page.$$eval(".text-block table tbody td",
                (els) => els.map((e) => e.textContent.trim()));
            assert(cells.length === 4 && cells[0] === "a1" && cells[3] === "b2",
                `cells: ${cells.join("|")}`);
        });
    });
});

test("session-restore-on-reload", async () => {
    await withConsole(SIMPLE_TEXT, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page) => {
            await submit(page, "first prompt");
            // Reload — session_id should persist via localStorage
            await page.reload({ waitUntil: "domcontentloaded" });
            await page.waitForSelector(".block", { timeout: 5000 });
            const userPrompts = await page.$$eval(".block .user-prompt",
                (els) => els.map((e) => e.textContent.trim()));
            assert(userPrompts.includes("first prompt"),
                `restored prompts: ${userPrompts.join("|")}`);
        });
    });
});

test("prompt-queue-during-in-flight", async () => {
    await withConsole(SLOW_TEXT, async ({ baseUrl }) => {
        await withPage(baseUrl, async (page) => {
            // Submit slow turn (don't await completion yet)
            await page.click("#prompt-input");
            await page.type("#prompt-input", "long one");
            await page.click("#send-btn");
            // Wait for footer to appear (turn started but not done)
            await page.waitForSelector(".turn-status-footer:not(.completed)");
            // Type + send a second prompt — should queue
            await page.click("#prompt-input");
            await page.type("#prompt-input", "queued prompt");
            await page.click("#send-btn");
            // Indicator should show queued
            await page.waitForSelector(".queue-indicator.queued", { timeout: 2000 });
            const queuedText = await page.$eval(".queue-indicator .queue-text",
                (e) => e.textContent.trim());
            assert(queuedText.includes("queued prompt"),
                `queued text: ${queuedText}`);
            // Wait for first turn to complete; queue should transition to ready
            await page.waitForSelector(".turn-status-footer.completed", { timeout: 10000 });
            await page.waitForSelector(".queue-indicator.ready", { timeout: 2000 });
            // Disposition buttons present
            const sendBtn = await page.$(".queue-indicator.ready .queue-action.send");
            const editBtn = await page.$(".queue-indicator.ready .queue-action.edit");
            const dropBtn = await page.$(".queue-indicator.ready .queue-action.drop");
            assert(sendBtn && editBtn && dropBtn,
                "send/edit/drop buttons present in ready state");
        });
    });
});

// ---- live-stack scenarios (--live flag required) ----
// These exercise the running agents service + chat console + Kroki.
// Real claude API calls happen, but bounded (hello-world is small).

liveTest("live-agents-dispatch-with-output", async () => {
    // Direct dispatch to agents service; verifies registry + output field.
    const r = await fetch(`${AGENTS_URL}/agents/hello-world/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "Say 'pong' and nothing else." }),
    });
    assert(r.ok, `dispatch failed: ${r.status}`);
    const { run_id } = await r.json();
    assert(run_id, "run_id returned");

    // Poll until done (cap 30s)
    let final;
    for (let i = 0; i < 30; i++) {
        const rr = await fetch(`${AGENTS_URL}/runs/${run_id}`);
        final = await rr.json();
        if (["done", "error", "cancelled"].includes(final.status)) break;
        await new Promise((r) => setTimeout(r, 1000));
    }
    assert(final.status === "done", `final status: ${final.status} error: ${final.error}`);
    assert(final.exit_code === 0, `exit_code: ${final.exit_code}`);
    assert(final.output && final.output.length > 0,
        "output field populated (was empty pre-602422f3)");

    // Confirm the run is in the registry list
    const list = await fetch(`${AGENTS_URL}/runs?limit=50`).then((r) => r.json());
    const found = list.some((x) => x.run_id === run_id);
    assert(found, "run visible in /runs list");
});

liveTest("live-diagram-render-via-kroki", async () => {
    // Round-trip through the chat console's Kroki proxy.
    const source = "graph TD; A[Live e2e] --> B[Kroki]; B --> C[SVG]";
    const r = await fetch(`${CONSOLE_URL}/render/diagram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine: "mermaid", source, format: "svg" }),
    });
    assert(r.ok, `render failed: ${r.status}`);
    const renderId = r.headers.get("X-Render-Id");
    assert(renderId, "X-Render-Id header present");
    const svg = await r.text();
    assert(svg.startsWith("<svg") || svg.startsWith("<?xml"),
        `svg body: ${svg.slice(0, 60)}`);

    // Content-addressable retrieval
    const get = await fetch(`${CONSOLE_URL}/render/diagram/${renderId}.svg`);
    assert(get.ok, `GET .svg: ${get.status}`);
    const png = await fetch(`${CONSOLE_URL}/render/diagram/${renderId}.png`);
    assert(png.ok, `GET .png: ${png.status}`);
});

// ---- runner ----
const liveProbed = RUN_LIVE
    ? {
        chat: await probe(`${CONSOLE_URL}/healthz`),
        agents: await probe(`${AGENTS_URL}/agents`),
      }
    : null;

let passed = 0, failed = 0, skipped = 0;
const start = Date.now();
for (const t of tests) {
    if (FILTER && !t.name.includes(FILTER)) continue;
    if (t.live && !RUN_LIVE) {
        console.log(`# skipped (no --live) - ${t.name}`);
        skipped++;
        continue;
    }
    if (t.live && (!liveProbed.chat || !liveProbed.agents)) {
        console.log(`# skipped (live stack unreachable: chat=${liveProbed.chat} agents=${liveProbed.agents}) - ${t.name}`);
        skipped++;
        continue;
    }
    try {
        await t.fn();
        console.log(`ok - ${t.name}`);
        passed++;
    } catch (e) {
        console.log(`not ok - ${t.name}`);
        console.log(`  # ${e.message.replace(/\n/g, "\n  # ")}`);
        failed++;
    }
}
const elapsed = ((Date.now() - start) / 1000).toFixed(1);
const total = passed + failed;
const skipNote = skipped > 0 ? `, ${skipped} skipped` : "";
console.log(`\n# ${total} tests, ${passed} passed, ${failed} failed${skipNote}, ${elapsed}s`);
process.exit(failed === 0 ? 0 : 1);
