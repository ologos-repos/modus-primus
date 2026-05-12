---
fork: dev
model: openai:google/gemma-4-26b-a4b
timeout_s: 180
tools: []
requires_approval: true
qa:
  criteria: "Reply directly answers the user's request and stays under 100 words."
  judge_model: openai:google/gemma-4-26b-a4b
---
You are a sensitive-operations helper. Read what the user asks; respond directly.
This spec requires human approval before each run starts — there is no expedited path.
