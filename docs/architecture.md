# Architecture and interview notes

## Problem

Investigating a latency regression requires correlating multiple sources. A summary without evidence is difficult to audit. This lab makes the evidence retrieval boundary explicit through MCP, and keeps measurement separate from inference.

## Data flow

1. The lab seeds 150k orders with 10k customer IDs. An indexed aggregate query measures count and total for one customer.
2. A baseline operation records a deployment event and 30 request timings using `perf_counter_ns`.
3. A lab migration drops the customer index. The same workload runs and its query plan is snapshotted.
4. The host launches a separate MCP subprocess with the same absolute telemetry DB path. The SDK performs initialization and tool discovery.
5. Rules mode calls five tools in a fixed order. LLM mode maps discovered schemas into function tools and feeds each result back to the model.
6. A report schema and evidence reference validator gate output. The dashboard links each finding to its source tool response.
7. An explicit restore operation recreates the index and measures fresh recovery samples. No investigation tool can perform it.

## Storage

`orders` stores workload data. `experiments` identifies runs. `events` records deployments, request durations, and query plans, with monotonically increasing event IDs. Correlation uses event order rather than coarse wall-clock timestamps. SQL values are parameterized; dynamic DDL identifiers are fixed code constants.

Every DB connection is explicitly closed. WAL allows the MCP server to read without mutating the database. The API gate prevents an investigation from racing a lab mutation within the supported single-worker server. The CLI should not be used to mutate the same DB while the dashboard is active.

## Failure behavior

| Failure | Behavior |
|---|---|
| Tool timeout/disconnection | One bounded retry, then a failed trace entry |
| Missing telemetry | Rule-based report abstains from naming a cause |
| Unknown/invented evidence ID | Report rejected |
| Invalid tool arguments | SDK/tool validation error; no retry |
| Provider timeout or invalid model output | HTTP error; no fabricated fallback |
| Old browser experiment | HTTP 409 with refresh guidance |
| Concurrent lab operation | HTTP 409; user can retry |
| Full investigation deadline | HTTP 504 after 180 seconds |

## Trade-offs

SQLite and stdio make reproduction easy and remove infrastructure setup. They do not demonstrate distributed ingestion, remote OAuth, or production tenancy. A new MCP process per investigation simplifies lifecycle isolation but adds startup cost. The fixed workflow is reproducible but intentionally domain-specific. The LLM is more flexible but slower, nondeterministic, and needs semantic evaluation beyond schema validation.

MCP is useful here because the same typed, discoverable tools can serve the included host or another compatible MCP host. MCP does not replace telemetry storage, the model, scheduling, authorization policy, or causal inference.

## Security boundary

Localhost binding, Host/Origin checks, restrictive CSP, fixed tool names, read-only DB connections, bounded log responses, and no arbitrary execution tools keep the demo constrained. Tool result text is treated as untrusted data in the model prompt, but this is not a complete prompt-injection defense. Provider credentials are not forwarded to the MCP child. The server process is trusted application code, not an OS sandbox. Do not expose this API on a public network.

## What to explain to an interviewer

- Why an observation, a hypothesis, and a verified recovery are different.
- How evidence IDs support traceability but do not prove semantic correctness.
- Why retries are safe for these read-only calls and require a different policy for mutations.
- Why the shared lab uses one worker and what must change for isolated tenants.
- How to replace SQLite telemetry tools with Prometheus/Loki adapters without changing the host's MCP boundary.
