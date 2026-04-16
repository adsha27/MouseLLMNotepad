from __future__ import annotations

import argparse

from .config import get_settings
from .shortcuts import main as shortcuts_main
from .store import MouseKBStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MouseKB local-first personal knowledge capture.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the FastAPI service.")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload in development.")

    subparsers.add_parser("print-secret", help="Print the local client secret.")
    subparsers.add_parser("reindex", help="Rebuild the capture index from raw markdown.")
    subparsers.add_parser("process-pending", help="Run any queued warm/cold processing jobs.")
    quick_capture = subparsers.add_parser("quick-capture", help="Launch the quick-capture window.")
    quick_capture.add_argument("--text", default="", help="Prefill the captured text.")
    quick_capture.add_argument("--source-app", default="clipboard", help="Label for the source application.")
    subparsers.add_parser("shortcut-status", help="Show desktop shortcut status.")

    bind = subparsers.add_parser("bind-gnome-shortcut", help="Configure a GNOME custom shortcut.")
    bind.add_argument("--binding", default="<Ctrl><Shift>K>")
    bind.add_argument("--name", default="MouseKB Quick Capture")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("uvicorn is not installed. Run `uv sync --extra dev` first.") from exc

        settings = get_settings()
        uvicorn.run(
            "mousekb.api:app",
            host=settings.bind_host,
            port=settings.bind_port,
            reload=args.reload,
        )
        return 0

    if args.command == "print-secret":
        print(get_settings().ensure_client_secret())
        return 0

    if args.command == "reindex":
        store = MouseKBStore(get_settings())
        print(store.reindex_from_markdown())
        return 0

    if args.command == "process-pending":
        store = MouseKBStore(get_settings())
        print(store.run_pending_jobs())
        return 0

    if args.command == "quick-capture":
        from .quick_capture import main as quick_capture_main

        forwarded_args: list[str] = []
        if args.text:
            forwarded_args.extend(["--text", args.text])
        if args.source_app:
            forwarded_args.extend(["--source-app", args.source_app])
        return quick_capture_main(forwarded_args)

    if args.command == "shortcut-status":
        return shortcuts_main(["status"])

    if args.command == "bind-gnome-shortcut":
        return shortcuts_main(["bind-gnome", "--binding", args.binding, "--name", args.name])

    parser.error(f"Unknown command: {args.command}")
    return 1
