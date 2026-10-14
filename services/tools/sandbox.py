"""Sandboxed command execution.

Agents never get a shell. Tools build an argv from a fixed allowlist and run it through a Sandbox:

  ProcessSandbox (local default)
    * argv only, never `shell=True`; executable must be on the allowlist
    * cwd pinned inside the mission workspace; env scrubbed (no API keys, tokens or host HOME)
    * rlimits: CPU seconds, address space, file size, open files; own process group, killed on timeout
    * network: if `unshare --net` works on this host the command runs in an empty network namespace
      (no egress at all); otherwise `network_isolated` is reported False in the tool result

  DockerSandbox (production, AICIV_SANDBOX=docker)
    * disposable `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges
      --pids-limit --memory --cpus --user <worker uid>` with only the workspace bind-mounted
    * the worker process talks to the container runtime; agents and their tools never see the socket
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class SandboxViolation(PermissionError):
    pass


ALLOWED_EXECUTABLES = {"python", "git"}
ALLOWED_GIT_SUBCOMMANDS = {"init", "add", "commit", "diff", "status", "worktree", "rev-parse", "log", "checkout", "branch", "config"}
ALLOWED_PYTHON_MODULES = {"pytest", "compileall"}

SAFE_ENV_KEYS = {"LANG", "LC_ALL", "TZ"}


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    network_isolated: bool

    @property
    def output(self) -> str:
        return (self.stdout + ("\n" + self.stderr if self.stderr.strip() else "")).strip()


def confine(root: Path, relative: str) -> Path:
    """Resolve `relative` under `root`, refusing absolute paths, `..` escapes and symlink escapes."""
    if not relative or os.path.isabs(relative) or "\x00" in relative:
        raise SandboxViolation(f"path not allowed: {relative!r}")
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise SandboxViolation(f"path escapes workspace: {relative!r}")
    if any(part in {".git"} for part in Path(relative).parts):
        raise SandboxViolation("direct access to .git is not allowed")
    return target


@lru_cache
def _unshare_available() -> bool:
    if not shutil.which("unshare") or sys.platform != "linux":
        return False
    try:
        return subprocess.run(["unshare", "--net", "--map-root-user", "true"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _validate_argv(argv: list[str]) -> None:
    if not argv or argv[0] not in ALLOWED_EXECUTABLES:
        raise SandboxViolation(f"executable not allowed: {argv[:1]}")
    if argv[0] == "git":
        rest = argv[1:]
        while rest and rest[0] == "-C":
            rest = rest[2:]
        sub = rest[0] if rest else None
        if sub not in ALLOWED_GIT_SUBCOMMANDS:
            raise SandboxViolation(f"git subcommand not allowed: {sub}")
    if argv[0] == "python":
        if len(argv) < 3 or argv[1] != "-m" or argv[2] not in ALLOWED_PYTHON_MODULES:
            raise SandboxViolation("python may only run allowlisted modules")


class ProcessSandbox:
    name = "process"

    def __init__(self, cpu_seconds: int = 60, memory_mb: int = 1024, file_size_mb: int = 50) -> None:
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb
        self.file_size_mb = file_size_mb

    def _preexec(self) -> None:  # pragma: no cover - runs in the child
        import resource

        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_seconds, self.cpu_seconds))
        mem = self.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        fsz = self.file_size_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsz, fsz))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    def run(self, argv: list[str], cwd: Path, timeout: int, workspace_root: Path) -> CommandResult:
        _validate_argv(argv)
        cwd = cwd.resolve()
        root = workspace_root.resolve()
        if cwd != root and root not in cwd.parents:
            raise SandboxViolation("cwd outside workspace")
        for i, a in enumerate(argv[:-1]):
            if a == "-C":
                p = Path(argv[i + 1]).resolve()
                if p != root and root not in p.parents:
                    raise SandboxViolation("git -C path outside workspace")
        exe =sys.executable if argv[0] == "python" else shutil.which("git")
        if not exe:
            raise SandboxViolation(f"{argv[0]} not installed")
        real = [exe, *argv[1:]]
        env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
        env.update({
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "AI Civilization Agent", "GIT_AUTHOR_EMAIL": "agents@aiciv.local",
            "GIT_COMMITTER_NAME": "AI Civilization Agent", "GIT_COMMITTER_EMAIL": "agents@aiciv.local",
        })
        isolated = _unshare_available()
        if isolated:
            real = ["unshare", "--net", "--map-root-user", *real]
        started = time.monotonic()
        proc = subprocess.Popen(real, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, preexec_fn=self._preexec, text=True)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        return CommandResult(argv, proc.returncode if not timed_out else -9, out[-20000:], err[-8000:],
                             int((time.monotonic() - started) * 1000), timed_out, isolated)


class DockerSandbox:
    """One disposable container per command (AICIV_SANDBOX=docker).

    * `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, pids/memory/cpu limits,
      a small tmpfs for /tmp, and nothing from the host environment (no keys, no tokens)
    * runs as the worker's own uid:gid so files it writes in the workspace stay owned by the worker
    * the workspace (and, for a git worktree, the repository's shared .git directory) is bind-mounted at the
      same absolute path it has on the host, so `git -C <path>` and worktree links resolve unchanged
    * on timeout the container is killed by name, not just abandoned
    Image: infrastructure/docker/sandbox.Dockerfile (Python 3.12, pytest, git), name from AICIV_SANDBOX_IMAGE.
    """

    name = "docker"

    def __init__(self, image: str | None = None, memory_mb: int = 1024, cpus: float = 1.0, pids: int = 128) -> None:
        self.image = image or os.environ.get("AICIV_SANDBOX_IMAGE", "aiciv-sandbox:latest")
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.pids = pids

    @staticmethod
    def _mounts(workspace_root: Path) -> list[Path]:
        root = workspace_root.resolve()
        mounts = [root]
        dotgit = root / ".git"
        if dotgit.is_file():  # a worktree: its objects and refs live in the main repository's .git
            gitdir = Path(dotgit.read_text().split("gitdir:", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            common = gitdir
            if (gitdir / "commondir").exists():
                common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
            if root not in common.parents:
                mounts.append(common)
        return mounts

    def command(self, argv: list[str], cwd: Path, workspace_root: Path, name: str = "aiciv-sbx") -> list[str]:
        _validate_argv(argv)
        root = workspace_root.resolve()
        cwd = cwd.resolve()
        if cwd != root and root not in cwd.parents:
            raise SandboxViolation("cwd outside workspace")
        for i, a in enumerate(argv[:-1]):
            if a == "-C":
                p = Path(argv[i + 1]).resolve()
                if p != root and root not in p.parents:
                    raise SandboxViolation("git -C path outside workspace")
        uid = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "65534:65534"
        cmd = [
            "docker", "run", "--rm", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", str(self.pids),
            "--memory", f"{self.memory_mb}m", "--cpus", str(self.cpus), "--user", uid,
            "--tmpfs", "/tmp:rw,size=64m", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "GIT_CONFIG_NOSYSTEM=1", "-e", "GIT_TERMINAL_PROMPT=0",
            "-e", "GIT_AUTHOR_NAME=AI Civilization Agent", "-e", "GIT_AUTHOR_EMAIL=agents@aiciv.local",
            "-e", "GIT_COMMITTER_NAME=AI Civilization Agent", "-e", "GIT_COMMITTER_EMAIL=agents@aiciv.local",
        ]
        for m in self._mounts(root):
            cmd += ["-v", f"{m}:{m}:rw"]
        return [*cmd, "-w", str(cwd), self.image, *argv]

    def run(self, argv: list[str], cwd: Path, timeout: int, workspace_root: Path) -> CommandResult:
        import uuid

        name = f"aiciv-sbx-{uuid.uuid4().hex[:12]}"
        cmd = self.command(argv, cwd, workspace_root, name)
        started = time.monotonic()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return CommandResult(argv, p.returncode, p.stdout[-20000:], p.stderr[-8000:], int((time.monotonic() - started) * 1000), False, True)
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return CommandResult(argv, -9, out[-20000:], "timeout", int((time.monotonic() - started) * 1000), True, True)


def default_sandbox():
    return DockerSandbox() if os.environ.get("AICIV_SANDBOX") == "docker" else ProcessSandbox()
