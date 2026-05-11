// Boot a real chat-console TestServer in a Python subprocess on a free
// port, with a deterministic mock generator. Yields the base URL; caller
// kills the process on cleanup.
//
// Why a subprocess: aiohttp + asyncio in Python is the production server.
// Driving puppeteer against the real wire (not a re-implementation) is
// what makes these tests catch real regressions.
//
// Per [ENTERPRISE: tracker ref].

import { spawn } from "node:child_process";
import net from "node:net";
import { setTimeout as sleep } from "node:timers/promises";

const REPO_ROOT = "[ENTERPRISE: deployment root]";
const CONSOLE_DIR = `${REPO_ROOT}/console`;

export async function freePort() {
    return new Promise((resolve, reject) => {
        const srv = net.createServer();
        srv.unref();
        srv.on("error", reject);
        srv.listen(0, "127.0.0.1", () => {
            const { port } = srv.address();
            srv.close(() => resolve(port));
        });
    });
}

/**
 * Spawn a chat console with a mock generator.
 * @param {object} opts
 * @param {string} opts.script - inline Python that defines `mock_gen` and
 *   passes it to build_app(). Receives `port` env var.
 * @returns {Promise<{ baseUrl: string, kill: () => void }>}
 */
export async function bootMockConsole({ script }) {
    const port = await freePort();
    const tmpHistory = `/tmp/e2e-history-${port}.sqlite`;
    const tmpTurns = `/tmp/e2e-turns-${port}`;

    const env = {
        ...process.env,
        CONSOLE_HOST: "127.0.0.1",
        CONSOLE_PORT: String(port),
        CHAT_CONSOLE_TURNS: tmpTurns,
        CHAT_CONSOLE_HISTORY: tmpHistory,
    };

    const child = spawn("/usr/bin/python3", ["-c", script], {
        cwd: CONSOLE_DIR,
        env,
        stdio: ["ignore", "pipe", "pipe"],
    });

    let stderr = "";
    child.stderr.on("data", (b) => { stderr += b.toString(); });
    child.stdout.on("data", () => {});  // drain

    // Poll healthz to know when server is up
    const baseUrl = `http://127.0.0.1:${port}`;
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
        try {
            const r = await fetch(`${baseUrl}/healthz`);
            if (r.ok) {
                return {
                    baseUrl,
                    kill: () => {
                        child.kill("SIGTERM");
                        try { require("fs").unlinkSync(tmpHistory); } catch {}
                    },
                };
            }
        } catch { /* not ready yet */ }
        await sleep(100);
    }
    child.kill("SIGTERM");
    throw new Error(`server never came up. stderr:\n${stderr}`);
}
