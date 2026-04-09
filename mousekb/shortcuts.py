from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass

from .config import get_settings


@dataclass(slots=True)
class ShortcutStatus:
    xdg_session_type: str
    gsettings_path: str | None
    gdbus_path: str | None
    can_bind_gnome_shortcut: bool


def inspect_shortcut_status() -> ShortcutStatus:
    import os

    return ShortcutStatus(
        xdg_session_type=os.environ.get("XDG_SESSION_TYPE", "unknown"),
        gsettings_path=shutil.which("gsettings"),
        gdbus_path=shutil.which("gdbus"),
        can_bind_gnome_shortcut=bool(shutil.which("gsettings")),
    )


def bind_gnome_shortcut(*, binding: str, name: str = "MouseKB Quick Capture") -> dict[str, str]:
    gsettings_path = shutil.which("gsettings")
    if not gsettings_path:
        raise RuntimeError("gsettings is not available on this system")

    settings = get_settings()
    launcher = settings.project_root / "scripts" / "open_quick_capture.sh"
    command = str(launcher)
    base_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    custom_path = f"{base_path}/mousekb/"

    current = _gsettings_get("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings")
    current_paths = _parse_gsettings_list(current)
    if custom_path not in current_paths:
        current_paths.append(custom_path)
        _gsettings_set(
            "org.gnome.settings-daemon.plugins.media-keys",
            "custom-keybindings",
            json.dumps(current_paths),
        )

    schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    _gsettings_set(schema, "name", json.dumps(name), path=custom_path)
    _gsettings_set(schema, "command", json.dumps(command), path=custom_path)
    _gsettings_set(schema, "binding", json.dumps(binding), path=custom_path)
    return {"binding": binding, "command": command, "path": custom_path}


def _gsettings_get(schema: str, key: str, *, path: str | None = None) -> str:
    cmd = ["gsettings", "get", schema, key]
    if path:
        cmd = ["gsettings", "get", schema + ":" + path, key]
    return subprocess.check_output(cmd, text=True).strip()


def _gsettings_set(schema: str, key: str, value: str, *, path: str | None = None) -> None:
    cmd = ["gsettings", "set", schema, key, value]
    if path:
        cmd = ["gsettings", "set", schema + ":" + path, key, value]
    subprocess.check_call(cmd)


def _parse_gsettings_list(raw: str) -> list[str]:
    text = raw.strip()
    if text in {"@", "@as []"}:
        return []
    try:
        return json.loads(text.replace("'", '"'))
    except json.JSONDecodeError:
        return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and configure MouseKB desktop shortcuts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show shortcut capability information.")
    bind = subparsers.add_parser("bind-gnome", help="Bind a GNOME custom shortcut for quick capture.")
    bind.add_argument("--binding", default="<Ctrl><Shift>K>")
    bind.add_argument("--name", default="MouseKB Quick Capture")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        status = inspect_shortcut_status()
        print(json.dumps(asdict(status), indent=2))
        return 0
    if args.command == "bind-gnome":
        result = bind_gnome_shortcut(binding=args.binding, name=args.name)
        print(json.dumps(result, indent=2))
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
