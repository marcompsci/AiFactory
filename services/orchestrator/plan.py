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


# ---------------------------------------------------------------- V4 mission templates
def research_graph(agent_key: str) -> list[TaskSpec]:
    return [TaskSpec("research", agent_key, "Research the market", "data-observatory", "observatory-lens",
                     ["query_market_source", "create_artifact"], expected_outputs={"opportunity_id": "str|null"},
                     validation={"cites_sources": True}, timeout_seconds=180)]


BUILD_PROTOTYPE_GRAPH: list[TaskSpec] = [
    TaskSpec("scaffold", "developer", "Build the prototype from the approved spec", "code-forge", "forge-anvil",
             ["scaffold_prototype", "list_files", "read_file"], expected_outputs={"files": "list[str]"},
             validation={"matches_spec": True}),
    TaskSpec("bundle", "developer", "Package a release bundle", "code-forge", "forge-anvil",
             ["build_release_bundle"], depends_on=["scaffold"], expected_outputs={"artifact_id": "str", "digest": "sha256"}),
]

QA_PROTOTYPE_GRAPH: list[TaskSpec] = [
    TaskSpec("qa_verify", "qa", "Test the exact release bundle", "sentinel-citadel", "citadel-testbay",
             ["stage_bundle", "run_tests", "run_build", "create_artifact"], expected_outputs={"passed": "int", "failed": "int", "bundle_digest": "sha256"},
             validation={"all_tests_pass": True, "tests_ran_on_reviewed_digest": True}),
]

RELEASE_GRAPH: list[TaskSpec] = [
    TaskSpec("release", "commander", "Release the owner-approved bundle", "nexus-spire", "nexus-command",
             ["submit_release", "create_artifact"], expected_outputs={"destination": "str"}, validation={"owner_authorized": True},
             max_attempts=1),
]

# ---------------------------------------------------------------- V5 AI Central Bank mission templates
REQUEST_TOOL_GRAPH: list[TaskSpec] = [
    TaskSpec("request_tool", "developer", "Ask the AI Central Bank for a paid tool", "code-forge", "forge-blueprint",
             ["request_purchase"], expected_outputs={"packet_id": "str"}, max_attempts=1),
]


def cost_research_graph(agent_key: str) -> list[TaskSpec]:
    return [TaskSpec("research_costs", agent_key, "Research legitimate alternatives", "data-observatory", "observatory-lens",
                     ["research_cost_alternatives"], expected_outputs={"count": "int"}, validation={"cites_sources": True})]


COST_ANALYSIS_GRAPH: list[TaskSpec] = [
    TaskSpec("analyze_costs", "savings_strategist", "Compare options and costs", "central-bank", "bank-savings",
             ["read_ledger_summary", "record_cost_findings"], expected_outputs={"action": "str"}),
    TaskSpec("recommend_cost", "cfo", "Recommend and prepare exact approval requests", "central-bank", "bank-executive",
             ["classify_cost", "propose_financial_action"], depends_on=["analyze_costs"], expected_outputs={"count": "int"}),
]

FINANCE_EXECUTE_GRAPH: list[TaskSpec] = [
    TaskSpec("execute_action", "bill_manager", "Carry out the owner-approved action", "central-bank", "bank-payables",
             ["execute_financial_action"], expected_outputs={"status": "str"}, validation={"owner_approved_exact_terms": True},
             max_attempts=1),
]

# ---------------------------------------------------------------- V5.1 free-alternative investigation (read-only)
ALT_RESEARCH_GRAPH = [TaskSpec("alt_research", "research_apps", "Find up to five legitimate alternatives", "data-observatory", "observatory-lens",
                               ["investigate_alternatives"], expected_outputs={"count": "int"}, validation={"cites_sources": True})]
ALT_EVALUATION_GRAPH = [TaskSpec("alt_evaluation", "savings_strategist", "Score candidates and build the shortlist", "central-bank", "bank-savings",
                                 ["score_alternatives"], expected_outputs={"shortlist": "list"})]
ALT_SANDBOX_GRAPH = [TaskSpec("alt_sandbox", "developer", "Test the strongest candidate in a disposable sandbox", "code-forge", "forge-anvil",
                              ["sandbox_evaluate_candidate"], expected_outputs={"status": "str"}, validation={"isolated": True}, max_attempts=1)]
ALT_QA_GRAPH = [TaskSpec("alt_qa", "qa", "Review the sandbox evidence", "sentinel-citadel", "citadel-testbay",
                         ["review_sandbox_evidence"], expected_outputs={"verdict": "str"})]
INVESTIGATION_KINDS = ("alt_research", "alt_evaluation", "alt_sandbox", "alt_qa")

KINDS = ("fix_failing_test", "market_research", "build_prototype", "qa_prototype", "release",
         "request_tool", "cost_research", "cost_analysis", "finance_execute", *INVESTIGATION_KINDS)


def plan_for(kind: str = "fix_failing_test", params: dict | None = None) -> list[TaskSpec]:
    params = params or {}
    if kind in ("fix_failing_test", "") or kind not in KINDS:
        graph = FIX_FAILING_TEST_GRAPH
    elif kind == "market_research":
        graph = research_graph(params.get("agent_key", "research_apps"))
    elif kind == "build_prototype":
        graph = BUILD_PROTOTYPE_GRAPH
    elif kind == "qa_prototype":
        graph = QA_PROTOTYPE_GRAPH
    elif kind == "request_tool":
        graph = REQUEST_TOOL_GRAPH
    elif kind == "cost_research":
        graph = cost_research_graph(params.get("agent_key", "research_apps"))
    elif kind == "cost_analysis":
        graph = COST_ANALYSIS_GRAPH
    elif kind == "finance_execute":
        graph = FINANCE_EXECUTE_GRAPH
    elif kind == "alt_research":
        graph = [TaskSpec(**{**ALT_RESEARCH_GRAPH[0].__dict__, "agent_key": params.get("agent_key", "research_apps")})]
    elif kind == "alt_evaluation":
        graph = ALT_EVALUATION_GRAPH
    elif kind == "alt_sandbox":
        graph = ALT_SANDBOX_GRAPH
    elif kind == "alt_qa":
        graph = ALT_QA_GRAPH
    else:
        graph = RELEASE_GRAPH
    validate_graph(graph)
    return graph
