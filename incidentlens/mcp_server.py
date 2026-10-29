"""Read-only MCP boundary. Lab mutation APIs are deliberately not exposed here."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from incidentlens.store import db_path, metrics, read_events

mcp = FastMCP("IncidentLens")
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
RUNBOOK = {
    "service": "orders-api",
    "steps": [
        "Compare baseline and incident query p95 within the same experiment.",
        "Correlate deployment order with latency; timing alone is not proof.",
        "Inspect the recorded query plan for a table scan versus an index search.",
        "If a required index was removed, propose restoring it after human approval.",
        "Verify recovery using fresh samples and check write overhead before production use.",
    ],
    "limitations": "Local SQLite lab. Query latency is not HTTP latency or a production SLO.",
}


@mcp.tool(annotations=READ_ONLY)
def query_metrics(experiment_id: str) -> dict:
    """Read measured query timings for one experiment, grouped by phase, in milliseconds."""
    return metrics(experiment_id)


@mcp.tool(annotations=READ_ONLY)
def search_logs(experiment_id: str, limit: int = 12) -> dict:
    """Read bounded request telemetry for one experiment. No arbitrary SQL or filesystem access."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    rows = read_events(experiment_id, "request")
    return {"experiment_id": experiment_id, "requests": rows[-limit:]}


@mcp.tool(annotations=READ_ONLY)
def list_deployments(experiment_id: str) -> dict:
    """Read the lab deployment timeline and migration SQL for an experiment."""
    return {"experiment_id": experiment_id, "deployments": read_events(experiment_id, "deployment")}


@mcp.tool(annotations=READ_ONLY)
def inspect_query_plan(experiment_id: str) -> dict:
    """Read query plans recorded during incident/recovery. These are historical snapshots."""
    return {"experiment_id": experiment_id, "plans": read_events(experiment_id, "query_plan")}


@mcp.tool(annotations=READ_ONLY)
def get_runbook() -> dict:
    """Read the orders-api troubleshooting runbook and lab limitations."""
    return RUNBOOK


@mcp.resource("runbook://orders-api")
def runbook_resource() -> str:
    """Service investigation runbook, also exposed as an MCP resource."""
    import json

    return json.dumps(RUNBOOK)


def main():
    if not db_path().exists():
        raise SystemExit(
            "Lab database missing. Run `incidentlens serve` and start a baseline first.",
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
