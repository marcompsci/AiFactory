"""Container sandbox, for real: these run only where Docker and the sandbox image exist.

    docker build -f infrastructure/docker/sandbox.Dockerfile -t aiciv-sandbox:latest .
    AICIV_TEST_DOCKER=1 python -m pytest tests/integration/test_docker_sandbox.py

CI runs them in the `sandbox` job. Elsewhere they skip, and say so.
"""
import os
import shutil
import subprocess

import pytest

from tests.conftest import mission_status, wait_for

pytestmark = pytest.mark.skipif(
    os.environ.get("AICIV_TEST_DOCKER") != "1" or not shutil.which("docker"),
    reason="set AICIV_TEST_DOCKER=1 with Docker and the aiciv-sandbox image available",
)


@pytest.fixture
def sandbox():
    from services.tools.sandbox import DockerSandbox

    sb = DockerSandbox()
    if subprocess.run(["docker", "image", "inspect", sb.image], capture_output=True).returncode != 0:
        pytest.fail(f"sandbox image {sb.image} is missing; build infrastructure/docker/sandbox.Dockerfile")
    return sb


def test_container_has_no_network_and_a_read_only_root(sandbox, tmp_path):
    (tmp_path / "test_probe.py").write_text(
        "import socket, pathlib, pytest\n"
        "def test_no_network():\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "def test_root_is_read_only():\n"
        "    with pytest.raises(OSError):\n"
        "        pathlib.Path('/usr/evil').write_text('x')\n"
        "def test_workspace_is_writable():\n"
        "    pathlib.Path('out.txt').write_text('ok')\n"
        "def test_no_secrets_in_env():\n"
        "    import os\n"
        "    assert not [k for k in os.environ if 'KEY' in k or 'TOKEN' in k]\n"
    )
    r = sandbox.run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], tmp_path, 120, tmp_path)
    assert r.exit_code == 0, r.output
    assert "4 passed" in r.output
    assert (tmp_path / "out.txt").read_text() == "ok"
    assert (tmp_path / "out.txt").stat().st_uid == os.getuid()  # files stay owned by the worker


def test_timeout_kills_the_container(sandbox, tmp_path):
    (tmp_path / "test_sleep.py").write_text("import time\ndef test_sleep():\n    time.sleep(120)\n")
    r = sandbox.run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], tmp_path, 8, tmp_path)
    assert r.timed_out
    left = subprocess.run(["docker", "ps", "-q", "--filter", "name=aiciv-sbx-"], capture_output=True, text=True).stdout.strip()
    assert left == ""


def test_whole_mission_runs_its_tools_in_containers(monkeypatch, sandbox):
    from fastapi.testclient import TestClient

    from services.tools import sandbox as sbmod

    monkeypatch.setenv("AICIV_SANDBOX", "docker")
    calls = []
    real_run = sbmod.DockerSandbox.run

    def counting_run(self, argv, cwd, timeout, workspace_root):
        r = real_run(self, argv, cwd, timeout, workspace_root)
        calls.append((argv[:3], r.exit_code))
        return r

    monkeypatch.setattr(sbmod.DockerSandbox, "run", counting_run)
    from services.api.main import app

    app.state.gateway = None
    with TestClient(app) as client:
        mid = client.post("/api/missions", json={"prompt": "Inspect the sample project, find a failing test, implement a fix, rerun the tests, and prepare a reviewable code change."}).json()["id"]
        wait_for(lambda: mission_status(client, mid)["status"] == "WAITING_FOR_APPROVAL", timeout=240)
        tasks = {t["key"]: t for t in client.get(f"/api/missions/{mid}").json()["tasks"]}
        assert tasks["reproduce"]["outputs"]["failing_tests"] == ["tests/test_stats.py::test_median_even"]
        assert tasks["verify"]["outputs"]["failed"] == 0 and tasks["verify"]["outputs"]["passed"] == 5
        a = next(a for a in client.get("/api/snapshot").json()["approvals"] if a["mission_id"] == mid)
        client.post(f"/api/approvals/{a['id']}/grant")
        m = wait_for(lambda: (s := mission_status(client, mid))["status"] == "COMPLETED" and s, timeout=240)
        assert m["outcome"] == "published"
    assert any(c[0][0] == "git" for c in calls)  # repo init, worktree, diff and commit all ran in containers
    assert any(c[0][:3] == ["python", "-m", "pytest"] for c in calls)
    assert all(code in (0, 1) for _, code in calls), calls  # pytest exits 1 while the bug is still there
