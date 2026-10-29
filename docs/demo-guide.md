# A 90-second demo

Use rule-based mode for a reproducible recording without an API key. Identify it honestly; use LLM mode only when demonstrating the model choosing tools.

| Time | Action | Narration |
|---|---|---|
| 0–12 s | Show the dashboard | “IncidentLens investigates a local latency regression through MCP, and shows the evidence behind its findings.” |
| 12–25 s | Run baseline | “This is a real aggregate query over 150,000 orders. These are measured query timings.” |
| 25–38 s | Remove index | “A migration removes a customer index. The same query now scans the table.” |
| 38–58 s | Investigate | “The host discovers and calls read-only MCP tools for metrics, deployments, logs, and query plans.” |
| 58–72 s | Select an evidence citation | “Every finding points to a retrieved tool result. Here is the migration and the scan plan.” |
| 72–85 s | Restore, then investigate again | “Remediation is my explicit action. New samples let the investigator check recovery.” |
| 85–90 s | Show repository | “The source includes the MCP server, optional LLM agent, tests, and a one-command demo.” |

Do not present your machine's speedup as a general benchmark or claim a production MTTR improvement. If the lab is noisy and the report abstains, that is useful behavior to demonstrate.

## Suggested LinkedIn framing after you have run and understood the project

Explain the problem, show the measured failure/recovery, link the repo, and discuss one engineering decision. Useful talking points: a real MCP boundary; evidence-linked findings; an explicit insufficient-evidence result; bounded tool calls; remediation outside the agent's tool surface. Avoid calling rule-based mode an AI investigation.
