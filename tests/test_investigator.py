import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, TextContent

from incidentlens.investigator import (
    Finding,
    Report,
    ToolRunner,
    investigate,
    llm_report,
    mcp_connection,
    rules_report,
    validate_evidence,
)
from incidentlens.store import baseline, change_index


def evidence(tool, data, n):
    return {"id": f"E{n}", "tool": tool, "ok": True, "result": data}


def known_incident():
    return [
        evidence(
            "query_metrics",
            {
                "phases": {
                    "baseline": {"samples": 30, "p95_ms": 1, "first_event": 2, "last_event": 31},
                    "incident": {"samples": 30, "p95_ms": 40, "first_event": 33, "last_event": 62},
                }
            },
            1,
        ),
        evidence(
            "list_deployments",
            {
                "deployments": [
                    {"event_id": 32, "sql": "DROP INDEX idx_orders_customer", "action": "incident"},
                ]
            },
            2,
        ),
        evidence(
            "inspect_query_plan",
            {
                "plans": [
                    {"phase": "incident", "plan": ["SCAN orders"]},
                ]
            },
            3,
        ),
    ]


def test_rules_require_corroboration():
    trace = known_incident()
    assert rules_report(trace).status == "suspected_cause"
    assert rules_report(trace[:1]).status == "insufficient_evidence"
    assert rules_report([]).status == "insufficient_evidence"
    trace[1]["result"]["deployments"][0]["event_id"] = 100
    assert rules_report(trace).status == "insufficient_evidence"


def test_rules_verify_restoration_before_recovery_claim():
    trace = known_incident()
    trace[0]["result"]["phases"]["recovery"] = {
        "samples": 30,
        "p95_ms": 1,
        "first_event": 65,
        "last_event": 94,
    }
    assert rules_report(trace).status == "suspected_cause"
    trace[1]["result"]["deployments"].append(
        {
            "event_id": 64,
            "action": "recovery",
            "sql": "CREATE INDEX idx_orders_customer",
        }
    )
    assert rules_report(trace).status == "recovered"


def test_evidence_validator_rejects_invented_citations():
    report = Report(
        status="suspected_cause",
        title="Unsupported",
        findings=[
            Finding(statement="A claim", evidence=["E999"]),
        ],
        next_steps=[],
        limitations=[],
    )
    with pytest.raises(ValueError, match="not successfully retrieved"):
        validate_evidence(report, known_incident())


async def test_timeout_is_bounded_and_preserves_partial_trace():
    async def slow(*args):
        await asyncio.sleep(1)

    session = SimpleNamespace(call_tool=slow)
    runner = ToolRunner(session, {"query_metrics"}, timeout=0.01)
    result = await runner.call("query_metrics", {})
    assert not result["ok"]
    assert runner.trace[0]["attempts"] == 2
    assert runner.trace[0]["duration_ms"] < 1000
    with pytest.raises(ValueError, match="allowlist"):
        await runner.call("delete_database", {})


async def test_tool_errors_are_not_retried_or_citable():
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=CallToolResult(
                content=[TextContent(type="text", text="invalid input")],
                isError=True,
            )
        )
    )
    runner = ToolRunner(session, {"search_logs"})
    assert not (await runner.call("search_logs", {"limit": 99}))["ok"]
    assert session.call_tool.await_count == 1


async def test_real_mcp_discovery_resource_and_investigation(lab):
    experiment = baseline()["experiment_id"]
    async with mcp_connection() as session:
        names = {t.name for t in (await session.list_tools()).tools}
        assert names == {
            "query_metrics",
            "list_deployments",
            "inspect_query_plan",
            "search_logs",
            "get_runbook",
        }
        assert all("restore" not in name and "delete" not in name for name in names)
        resource = await session.read_resource("runbook://orders-api")
        assert "orders-api" in resource.contents[0].text
        invalid = await session.call_tool("search_logs", {"experiment_id": experiment, "limit": 51})
        assert invalid.isError
    report = await investigate(experiment)
    assert report["report"]["status"] == "insufficient_evidence"
    change_index(experiment, restore=False)
    report = await investigate(experiment)
    assert len(report["trace"]) == 5
    assert all(e["ok"] for e in report["trace"])
    assert report["mode"] == "rules"


async def test_llm_mode_requires_key(lab):
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await investigate("example", "llm")


class FakeMessage:
    def __init__(self, calls=None, content=None):
        self.tool_calls, self.content = calls, content

    def model_dump(self, **kwargs):
        return {"role": "assistant", "content": self.content}


async def test_llm_loop_routes_calls_through_mcp_and_checks_citations():
    # Provider mocked; MCP routing and report validation are exercised without paid API calls.
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="query_metrics",
            arguments=json.dumps({"experiment_id": "exp-1"}),
        ),
    )
    final = Report(
        status="insufficient_evidence",
        title="Need more evidence",
        findings=[
            Finding(statement="No samples were returned", evidence=["E1"]),
        ],
        next_steps=["Collect samples"],
        limitations=["Local lab"],
    )
    responses = [FakeMessage([tool_call]), FakeMessage(content=final.model_dump_json())]
    create = AsyncMock(
        side_effect=[SimpleNamespace(choices=[SimpleNamespace(message=m)]) for m in responses]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=CallToolResult(
                content=[],
                structuredContent={"phases": {}},
            )
        )
    )
    runner = ToolRunner(session, {"query_metrics"})
    tool = SimpleNamespace(name="query_metrics", description="Read metrics", inputSchema={})
    report = await llm_report(runner, [tool], "exp-1", client)
    assert report.status == "insufficient_evidence"
    session.call_tool.assert_awaited_once_with("query_metrics", {"experiment_id": "exp-1"})
    assert create.await_count == 2


async def test_llm_cannot_cross_experiment_boundary():
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="query_metrics",
            arguments='{"experiment_id":"other"}',
        ),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=FakeMessage([call]))],
        )
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runner = ToolRunner(SimpleNamespace(), {"query_metrics"})
    with pytest.raises(ValueError, match="different experiment"):
        await llm_report(runner, [], "exp-1", client)
