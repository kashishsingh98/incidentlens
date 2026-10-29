import sqlite3

import pytest

from incidentlens.store import (
    baseline,
    change_index,
    connection,
    initialize,
    metrics,
    read_events,
)


def test_real_index_lifecycle_and_historical_plan(lab):
    experiment = baseline()["experiment_id"]
    change_index(experiment, restore=False)
    plan = read_events(experiment, "query_plan")[-1]
    assert any("SCAN orders" in p for p in plan["plan"])
    change_index(experiment, restore=True)
    plans = read_events(experiment, "query_plan")
    assert plans[0] == plan  # Recovery must not overwrite incident evidence.
    assert any("USING INDEX" in p for p in plans[-1]["plan"])
    assert {k: v["samples"] for k, v in metrics(experiment)["phases"].items()} == {
        "baseline": 30,
        "incident": 30,
        "recovery": 30,
    }
    # Do not assert a speed ratio: shared CI machines have noisy timing.


def test_readonly_connection_cannot_mutate(lab):
    initialize()
    with connection(readonly=True) as c, pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM orders")


def test_phase_validation_and_experiment_isolation(lab):
    first = baseline()["experiment_id"]
    with pytest.raises(ValueError, match="Expected incident"):
        change_index(first, restore=True)
    change_index(first, restore=False)
    second = baseline()["experiment_id"]
    assert set(metrics(second)["phases"]) == {"baseline"}
    assert set(metrics(first)["phases"]) == {"baseline", "incident"}
    with pytest.raises(ValueError, match="Unknown experiment"):
        change_index("' OR 1=1 --", restore=False)
