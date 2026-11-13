"""Runtime settings for the services (API, flows in containers). Science/pipeline settings stay in params.yaml.

Every field can be set with an environment variable FLARE_<NAME> (Docker Compose `environment:`, Kubernetes ConfigMap).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLARE_", extra="ignore")

    bundle_dir: Path = Field(ROOT / "model_bundle", description="exported model bundle (models + replay days)")
    predictions_dir: Path = Field(ROOT / "data" / "predictions", description="predictions store (Parquet + SQLite)")
    drift_file: Path = Field(
        ROOT / "reports" / "drift" / "latest.json", description="live drift summary (falls back to the bundle copy)"
    )
    cors_origins: str = Field("http://localhost:5173,http://localhost:8080,http://127.0.0.1:8080", description="comma list")
    log_level: str = "INFO"
    max_replay_speed: float = Field(600.0, description="highest allowed replay speed (replay seconds per wall second)")
    stream_max_frames: int = Field(8640, description="cap on frames per SSE stream (one day of 10-s steps)")
    production_start: str = Field("2026-11-13", description="first production day: the day after holdout2 (locked before it)")
    raw_solexs_dir: Path | None = Field(None, description="SoLEXS L1 day folders for production (FITS); None = not mounted")
    inbox_dir: Path | None = Field(ROOT / "data" / "inbox", description="cleaned 1-s counts <YYYY-MM-DD>.parquet (CI / tests)")
    ingest_dvc: bool = Field(False, description="daily_ingest also re-runs changed DVC data stages (developer machine only)")
    prefect_api_url: str | None = Field(None, description="Prefect server API, for /pipeline/status")
    mlflow_url: str | None = Field(None, description="MLflow tracking server (read-only use), for /pipeline/status")
    environment: str = Field("local", description="local | compose | k8s | ci")
    git_sha: str = Field("unknown", description="set at image build time")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
