from __future__ import annotations

from mousekb import cli, quick_capture


def test_cli_quick_capture_accepts_prefill_arguments():
    parser = cli.build_parser()
    args = parser.parse_args(["quick-capture", "--text", "copied text", "--source-app", "terminal"])

    assert args.command == "quick-capture"
    assert args.text == "copied text"
    assert args.source_app == "terminal"


def test_quick_capture_module_imports_without_gtk_in_current_interpreter():
    parser = quick_capture.build_parser()
    args = parser.parse_args(["--text", "hello", "--source-app", "browser"])

    assert args.text == "hello"
    assert args.source_app == "browser"
