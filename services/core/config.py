"""Runtime configuration. Every secret comes from the environment; nothing is hard-coded."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "packages" / "shared-types" / "seed" / "agents.json"
DISTRICTS_PATH = REPO_ROOT / "packages" / "world-engine" / "src" / "districts.json"
SAMPLE_REPO_PATH = REPO_ROOT / "services" / "api" / "sample_repo"


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("AICIV_DATA_DIR", REPO_ROOT / ".data")).resolve())
    api_token: str = field(default_factory=lambda: os.environ.get("AICIV_API_TOKEN", ""))
    supabase_jwt_secret: str = field(default_factory=lambda: os.environ.get("SUPABASE_JWT_SECRET", ""))
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", ""))
    # Supabase projects created since 2025 sign sessions with asymmetric keys (ES256/RS256), published as JWKS.
    supabase_jwks_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_JWKS_URL", "") or (
        os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/.well-known/jwks.json" if os.environ.get("SUPABASE_URL") else ""))
    supabase_service_role_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.environ.get("AICIV_ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    openai_model: str = field(default_factory=lambda: os.environ.get("AICIV_OPENAI_MODEL", "gpt-4.1-mini"))
    default_mission_budget_usd: float = field(default_factory=lambda: _float("AICIV_MISSION_BUDGET_USD", 1.0))
    daily_budget_usd: float = field(default_factory=lambda: _float("AICIV_DAILY_BUDGET_USD", 5.0))
    cost_warning_ratio: float = field(default_factory=lambda: _float("AICIV_COST_WARNING_RATIO", 0.8))
    tool_timeout_seconds: int = field(default_factory=lambda: int(_float("AICIV_TOOL_TIMEOUT_SECONDS", 60)))
    max_concurrent_missions: int = field(default_factory=lambda: int(_float("AICIV_MAX_CONCURRENT_MISSIONS", 2)))
    allowed_origins: list[str] = field(
        default_factory=lambda: [o for o in os.environ.get("AICIV_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o]
    )
    # Movement delay (seconds) between "movement requested" and "arrived" — purely cosmetic pacing so the
    # world can animate. 0 in tests.
    travel_seconds: float = field(default_factory=lambda: _float("AICIV_TRAVEL_SECONDS", 1.5))

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'aiciv.db'}"

    @property
    def workspaces_dir(self) -> Path:
        p = self.data_dir / "workspaces"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def dev_auth(self) -> bool:
        """No token and no Supabase auth configured → local single-user dev mode."""
        return not self.api_token and not self.supabase_jwt_secret and not self.supabase_jwks_url

    @property
    def model_available(self) -> bool:
        from services.model_gateway import plans
        return bool(self.anthropic_api_key or self.openai_api_key) or plans.enabled()


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_seed() -> dict:
    return json.loads(SEED_PATH.read_text())


@lru_cache
def load_districts() -> list[dict]:
    return json.loads(DISTRICTS_PATH.read_text())["districts"]
