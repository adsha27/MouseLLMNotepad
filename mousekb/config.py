from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
CLIENT_SECRET_HEADER = "x-mousekb-client-secret"


@dataclass(slots=True)
class Settings:
    project_root: Path
    bind_host: str = DEFAULT_HOST
    bind_port: int = DEFAULT_PORT

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def vault_dir(self) -> Path:
        return self.project_root / "vault"

    @property
    def raw_dir(self) -> Path:
        return self.vault_dir / "raw"

    @property
    def inbox_dir(self) -> Path:
        return self.vault_dir / "inbox"

    @property
    def profile_dir(self) -> Path:
        return self.vault_dir / "profile"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def secret_path(self) -> Path:
        return self.data_dir / "client_secret.txt"

    @property
    def approved_profile_path(self) -> Path:
        return self.profile_dir / "approved.md"

    @property
    def pending_profile_path(self) -> Path:
        return self.profile_dir / "pending.md"

    @classmethod
    def from_root(cls, project_root: Path, *, bind_host: str = DEFAULT_HOST, bind_port: int = DEFAULT_PORT) -> "Settings":
        return cls(project_root=project_root, bind_host=bind_host, bind_port=bind_port)

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def ensure_client_secret(self) -> str:
        self.ensure_layout()
        if self.secret_path.exists():
            return self.secret_path.read_text(encoding="utf-8").strip()
        secret = secrets.token_urlsafe(32)
        self.secret_path.write_text(secret + "\n", encoding="utf-8")
        return secret


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_root = os.environ.get("MOUSEKB_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[1]

    bind_host = os.environ.get("MOUSEKB_HOST", DEFAULT_HOST)
    bind_port = int(os.environ.get("MOUSEKB_PORT", DEFAULT_PORT))
    settings = Settings.from_root(root, bind_host=bind_host, bind_port=bind_port)
    settings.ensure_layout()
    settings.ensure_client_secret()
    return settings
