"""V6.128: a tool that crashes (as the macOS sandbox did) fails the mission with a reason instead of looping until
LangGraph's recursion limit; the sandbox skips resource limits the OS refuses."""
import resource

from services.tools import sandbox as sb_mod
from tests.conftest import mission_status, wait_for
from tests.integration.test_missions import PROMPT


def test_a_crashing_tool_fails_the_mission_with_a_reason(client, monkeypatch):
    from services.tools import registry

    def boom(*a, **k):
        raise RuntimeError("Exception occurred in preexec_fn.")

    monkeypatch.setattr(registry, "_repo_root", boom)
    mid = client.post("/api/missions", json={"prompt": PROMPT}).json()["id"]
    m = wait_for(lambda: (x := mission_status(client, mid))["status"] in ("COMPLETED", "FAILED", "CANCELLED") and x, timeout=60)
    assert m["status"] == "FAILED"
    d = client.get(f"/api/missions/{mid}").json()
    errors = str(d)
    assert "unexpected error" in errors and "RuntimeError" in errors
    assert not any(t["status"] == "RUNNING" for t in d["tasks"])  # nothing left spinning


def test_sandbox_skips_limits_the_os_refuses(monkeypatch):
    calls = []

    def picky(which, lims):
        calls.append(which)
        if which == resource.RLIMIT_AS:
            raise ValueError("not allowed on this OS")
        return None  # record only: never lower the test runner's own limits

    monkeypatch.setattr(resource, "setrlimit", picky)
    monkeypatch.setattr(sb_mod.os, "setsid", lambda: None)
    sb = sb_mod.ProcessSandbox()
    sb._preexec()  # in-process: must not raise even though RLIMIT_AS is refused
    assert resource.RLIMIT_AS in calls and resource.RLIMIT_NOFILE in calls
