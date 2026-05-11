---
kind: workflow
description: Three-step demo — produce a fact, compress it, then rephrase it casually. Exercises chaining across three different agents (and providers, since ollama-hello uses a non-claude backend).
steps:
  - id: produce
    agent: hello-world
    prompt: "Tell me one sentence about: {input}"
  - id: compress
    agent: concise-summary
    prompt: "Compress to under 25 words, keep the key fact: {prev_output}"
  - id: rephrase
    agent: ollama-hello
    prompt: "Rephrase this in a casual, friendly tone (one sentence): {prev_output}"
---
Phase 8 smoke workflow. Demonstrates the linear-chain pattern: input flows
through three agents, each consuming the previous step's text output via
the `{prev_output}` placeholder. The final step uses Ollama (Tracy's
gemma3:12b) to prove cross-provider chaining works.
