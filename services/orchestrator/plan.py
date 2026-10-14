"""Mission validation and task-graph planning.

The task graph is built from a validated template rather than free-form model output: every task gets
explicit inputs, permitted tools, expected outputs and validation rules, and the graph is checked for
cycles and for tools the assigned agent cannot use. A model (when configured) contributes the
Commander's written plan rationale and the Developer's patch — never the permissions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.core.config import load_districts, load_seed


class PlanError(ValueError):
    pass


@dataclass
class TaskSpec:
    key: str
    agent_key: str
    title: str
    district: str
    workstation: str
    permitted_tools: list[str]
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    timeout_seconds: int = 180
    max_attempts: int = 2


FIX_FAILING_TEST_GRAPH: list[TaskSpec] = [
    TaskSpec("inspect", "architect", "Inspect repository structure", "code-forge", "forge-blueprint",
             ["inspect_repository", "list_files", "read_file", "search_code"],
             expected_outputs={"source_files": "list[str]", "test_command": "str"},
             validation={"requires": ["source_files"]}),
    TaskSpec("reproduce", "qa", "Reproduce the failing test", "sentinel-citadel", "citadel-testbay",
             ["run_tests"],
             expected_outputs={"failing_tests": "list[str]", "output": "str"},
             validation={"tests_executed": True}),
    TaskSpec("implement", "developer", "Implement a fix in an isolated worktree", "code-forge", "forge-anvil",
             ["create_worktree", "list_files", "read_file", "search_code", "edit_file", "inspect_diff"],
             depends_on=["inspect", "reproduce"],
             expected_outputs={"diff": "str"}, validation={"worktree": True}, max_attempts=2, timeout_seconds=300),
    TaskSpec("verify", "qa", "Rerun the test suite on the fix", "sentinel-citadel", "citadel-testbay",
             ["run_tests", "run_build", "create_artifact"], depends_on=["implement"],
             expected_outputs={"passed": "int", "failed": "int"}, validation={"all_tests_pass": True}),
    TaskSpec("review", "architect", "Review the diff", "code-forge", "forge-blueprint",
             ["inspect_diff", "read_file", "create_artifact"], depends_on=["verify"],
             expected_outputs={"artifact_id": "str"}),
    TaskSpec("publish", "commander", "Publish the reviewable change", "nexus-spire", "nexus-command",
             ["prepare_pull_request", "create_artifact"], depends_on=["review"],
             expected_outputs={"commit": "str"}, validation={"requires_approval": True}, timeout_seconds=600),
    TaskSpec("archive", "researcher", "Archive results to the Memory Vault", "memory-vault", "vault-archive",
             ["create_artifact"], depends_on=["publish"], expected_outputs={"memory_ids": "list[str]"}),
]


def validate_graph(graph: list[TaskSpec]) -> None:
    agents = {a["key"]: a for a in load_seed()["agents"]}
    districts = {d["id"]: d for d in load_districts()}
    keys = [t.key for t in graph]
    if len(keys) != len(set(keys)):
        raise PlanError("duplicate task keys")
    for t in graph:
        if t.agent_key not in agents:
            raise PlanError(f"unknown agent {t.agent_key}")
        if t.district not in districts:
            raise PlanError(f"unknown district {t.district}")
        if t.workstation not in {w["id"] for w in districts[t.district]["workstations"]}:
            raise PlanError(f"unknown workstation {t.workstation}")
        missing = set(t.permitted_tools) - set(agents[t.agent_key]["tools"])
        if missing:
            raise PlanError(f"{t.key}: agent {t.agent_key} cannot use {sorted(missing)}")
        for d in t.depends_on:
            if d not in keys:
                raise PlanError(f"{t.key} depends on unknown task {d}")
    # cycle check (Kahn)
    indeg = {t.key: len(t.depends_on) for t in graph}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for t in graph:
        for d in t.depends_on:
            children[d].append(t.key)
    ready = [k for k, n in indeg.items() if n == 0]
    seen = 0
    while ready:
        k = ready.pop()
        seen += 1
        for c in children[k]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    if seen != len(keys):
        raise PlanError("task graph has a cycle")


def validate_prompt(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if len(prompt) < 8:
        raise PlanError("describe the mission in a sentence or more")
    if len(prompt) > 4000:
        raise PlanError("mission prompt is too long (4000 characters max)")
    return prompt


def plan_for(prompt: str) -> list[TaskSpec]:
    """Only one mission template ships in the vertical slice: repair failing tests in the selected repository."""
    graph = FIX_FAILING_TEST_GRAPH
    validate_graph(graph)
    return graph
