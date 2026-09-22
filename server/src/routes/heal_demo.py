from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.heal_service import (
    is_heal_in_progress,
    list_agent_runs,
    list_baselines,
    read_agent_run,
    revert_results_portal,
)

router = APIRouter()


class RevertRequest(BaseModel):
    snapshot_id: Optional[str] = Field(
        default=None,
        description=(
            "Baseline id (filename stem). Defaults to heal/results_portal_pre_heal.py. "
            "Aliases: pre_heal, results_portal_pre_heal, heal. "
            "Or pass a cache/baselines stem for a run-specific snapshot."
        ),
    )


@router.post("/heal/revert")
def heal_revert(body: RevertRequest = RevertRequest()):
    """
    Restore automation/results_portal.py from heal/results_portal_pre_heal.py (default).

    Does not run heal or Fetch Filings. On the next Fetch Filings run, landing-grid
    health is checked first: BSE downtime notifies the user (no heal); UI drift may heal.
    """
    if is_heal_in_progress():
        raise HTTPException(status_code=409, detail="Heal is currently in progress")
    snapshot_id = body.snapshot_id
    try:
        result = revert_results_portal(snapshot_id=snapshot_id)
        return {"status": "ok", **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/heal/baselines")
def heal_baselines():
    return {"baselines": list_baselines()}


@router.get("/heal/agent-runs")
def heal_agent_runs(limit: int = 50):
    return {"runs": list_agent_runs(limit=limit)}


@router.get("/heal/agent-runs/{run_id}")
def heal_agent_run_detail(run_id: str):
    data = read_agent_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Agent run not found: {run_id}")
    return data
