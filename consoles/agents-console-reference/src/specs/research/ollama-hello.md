---
fork: dev
model: openai:google/gemma-4-26b-a4b
timeout_s: 120
tools: []
qa:
  criteria: "Reply directly answers the user's question in fewer than 80 words and contains no claude-specific terminology (e.g. no references to 'tools', 'Read', 'Edit')."
---
You are a single-shot research helper running on local Ollama. Reply concisely.
