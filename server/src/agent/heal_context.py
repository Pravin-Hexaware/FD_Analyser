from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from services.logging_service import logging_service


ROOT = Path(__file__).resolve().parents[1]
AGENT_RUNS_DIR = ROOT / "logs" / "agent_runs"
BASELINES_DIR = ROOT / "cache" / "baselines"
HEAL_DIR = ROOT / "heal"
PLANS_DIR = ROOT / "cache" / "plans"
RAW_DIR = ROOT / "cache" / "raw"
STAGING_MODULE = ROOT / "cache" / "staging_results_portal.py"
PRODUCTION_MODULE = ROOT / "automation" / "results_portal.py"
# Canonical pre-heal source for POST /heal/revert (stable; not overwritten by heal runs).
PRE_HEAL_MODULE = HEAL_DIR / "results_portal_pre_heal.py"
LAST_PRE_HEAL = BASELINES_DIR / "results_portal_last_pre_heal.py"
LAST_GOOD = BASELINES_DIR / "results_portal_last_good.py"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class ThoughtSummary:
    agent: str
    summary: str
    decisions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=_iso_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "decisions": list(self.decisions),
            "warnings": list(self.warnings),
            "timestamp": self.timestamp,
        }


@dataclass
class HealRunContext:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    target_url: str = ""
    test_input: str = ""
    trigger_reason: str = ""
    thoughts: List[ThoughtSummary] = field(default_factory=list)
    log_path: Optional[Path] = None
    baseline_path: Optional[Path] = None
    staging_path: Path = field(default_factory=lambda: STAGING_MODULE)
    promoted: bool = False
    status: str = "started"

    def __post_init__(self) -> None:
        AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H-%M-%S")
        self.log_path = AGENT_RUNS_DIR / f"AgentRun-{stamp}_{self.run_id}.log"
        self._write_line(f"=== HEAL RUN {self.run_id} START {_iso_now()} ===")
        self._write_line(f"target_url={self.target_url}")
        self._write_line(f"test_input={self.test_input}")
        self._write_line(f"trigger_reason={self.trigger_reason or 'n/a'}")
        # Dedicated agent session (separate from app SessionLog)
        try:
            agent_session = logging_service.start_agent_session(
                run_id=self.run_id,
                target_url=self.target_url,
                test_input=self.test_input,
                trigger_reason=self.trigger_reason or "n/a",
                agent_run_log=str(self.log_path),
            )
            self._write_line(f"agent_session_log={agent_session}")
            logging_service.log_phase(
                "agent_session",
                "started",
                run_id=self.run_id,
                agent_session_log=str(agent_session),
                agent_run_log=str(self.log_path),
            )
        except Exception:
            pass

    def _write_line(self, line: str) -> None:
        if not self.log_path:
            return
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
        try:
            logging_service.log_agent_session(line)
        except Exception:
            pass

    def log(self, event: str, **details: Any) -> None:
        payload = {"event": event, "ts": _iso_now(), **details}
        self._write_line(json.dumps(payload, ensure_ascii=False, default=str))

    def add_thought(
        self,
        agent: str,
        summary: str,
        *,
        decisions: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ThoughtSummary:
        thought = ThoughtSummary(
            agent=agent,
            summary=summary,
            decisions=decisions or [],
            warnings=warnings or [],
        )
        self.thoughts.append(thought)
        self.log("thought", **thought.to_dict())
        return thought

    def thoughts_for_prompt(self, *, max_items: int = 8) -> str:
        if not self.thoughts:
            return "None"
        items = self.thoughts[-max_items:]
        return json.dumps([t.to_dict() for t in items], indent=2, ensure_ascii=False)

    def finish(self, status: str, **details: Any) -> None:
        self.status = status
        self.log("run_finished", status=status, promoted=self.promoted, **details)
        self._write_line(f"=== HEAL RUN {self.run_id} END status={status} ===")
        try:
            logging_service.log_phase(
                "agent_session",
                "success" if status == "success" else "failed",
                run_id=self.run_id,
                status=status,
                **details,
            )
            logging_service.end_agent_session(run_id=self.run_id, status=status, **details)
        except Exception:
            pass


def snapshot_pre_heal(source: Path, run_id: str) -> Path:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    run_snap = BASELINES_DIR / f"results_portal_pre_heal_{run_id}.py"
    run_snap.write_text(text, encoding="utf-8")
    LAST_PRE_HEAL.write_text(text, encoding="utf-8")
    return run_snap


def mark_last_good(source: Path) -> Path:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    LAST_GOOD.write_text(text, encoding="utf-8")
    return LAST_GOOD


def list_baselines() -> List[Dict[str, Any]]:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    if PRE_HEAL_MODULE.exists():
        rows.append(
            {
                "id": PRE_HEAL_MODULE.stem,
                "path": str(PRE_HEAL_MODULE),
                "bytes": PRE_HEAL_MODULE.stat().st_size,
                "mtime": datetime.fromtimestamp(PRE_HEAL_MODULE.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
                "source": "heal",
                "default_for_revert": True,
            }
        )
    for path in sorted(BASELINES_DIR.glob("*.py"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows.append(
            {
                "id": path.stem,
                "path": str(path),
                "bytes": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                "source": "cache_baselines",
            }
        )
    return rows


def list_agent_runs(limit: int = 50) -> List[Dict[str, Any]]:
    AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    files = sorted(AGENT_RUNS_DIR.glob("AgentRun-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:limit]:
        # AgentRun-YYYYMMDD_HH-MM-SS_<run_id>.log
        name = path.stem
        run_id = name.split("_")[-1] if "_" in name else name
        rows.append(
            {
                "run_id": run_id,
                "path": str(path),
                "bytes": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return rows


def read_agent_run(run_id: str) -> Optional[Dict[str, Any]]:
    AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    matches = list(AGENT_RUNS_DIR.glob(f"AgentRun-*_{run_id}.log"))
    if not matches:
        # allow exact filename stem match
        matches = [p for p in AGENT_RUNS_DIR.glob("AgentRun-*.log") if run_id in p.name]
    if not matches:
        return None
    path = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return {
        "run_id": run_id,
        "path": str(path),
        "content": path.read_text(encoding="utf-8"),
    }


def resolve_baseline(snapshot_id: Optional[str] = None) -> Path:
    """
    Resolve a portal baseline for revert.

    Default (no snapshot_id): prefer heal/results_portal_pre_heal.py, then
    cache last_pre_heal / last_good.
    """
    if snapshot_id:
        sid = snapshot_id.strip()
        # Explicit aliases for the canonical heal-folder baseline
        if sid in {
            "pre_heal",
            "results_portal_pre_heal",
            PRE_HEAL_MODULE.stem,
            "heal",
        }:
            if PRE_HEAL_MODULE.exists():
                return PRE_HEAL_MODULE
            raise FileNotFoundError(f"Canonical pre-heal module missing: {PRE_HEAL_MODULE}")

        candidate = BASELINES_DIR / f"{sid}.py"
        if not candidate.exists():
            candidate = BASELINES_DIR / sid
        if not candidate.exists() and (HEAL_DIR / f"{sid}.py").exists():
            candidate = HEAL_DIR / f"{sid}.py"
        if not candidate.exists():
            raise FileNotFoundError(f"Baseline snapshot not found: {snapshot_id}")
        return candidate

    if PRE_HEAL_MODULE.exists():
        return PRE_HEAL_MODULE
    if LAST_PRE_HEAL.exists():
        return LAST_PRE_HEAL
    if LAST_GOOD.exists():
        return LAST_GOOD
    raise FileNotFoundError(
        f"No baseline snapshot available. Expected {PRE_HEAL_MODULE} or a cache baseline."
    )
