from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

from .config import CLIENT_SECRET_HEADER, get_settings


def post_clipboard_capture(payload: dict[str, str | None]) -> dict[str, object]:
    settings = get_settings()
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://{settings.bind_host}:{settings.bind_port}/captures/clipboard",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            CLIENT_SECRET_HEADER: settings.ensure_client_secret(),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def read_clipboard_text() -> str:
    return ""


class QuickCaptureWindow(Gtk.Application):
    def __init__(self, *, initial_text: str = "", source_app: str = "clipboard") -> None:
        super().__init__(application_id="dev.mousekb.quickcapture")
        self.initial_text = initial_text
        self.source_app = source_app
        self.window: Gtk.ApplicationWindow | None = None
        self.status_label: Gtk.Label | None = None
        self.text_buffer: Gtk.TextBuffer | None = None
        self.note_buffer: Gtk.TextBuffer | None = None
        self.source_entry: Gtk.Entry | None = None
        self.sensitivity_dropdown: Gtk.DropDown | None = None
        self.clipboard_prefilled = bool(initial_text)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("MouseKB Quick Capture")
        self.window.set_default_size(620, 520)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)
        outer.set_margin_start(18)
        outer.set_margin_end(18)

        heading = Gtk.Label(label="Save copied text to your inbox")
        heading.add_css_class("title-3")
        heading.set_xalign(0)
        outer.append(heading)

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        source_label = Gtk.Label(label="Source app")
        source_label.set_xalign(0)
        source_label.set_width_chars(12)
        source_row.append(source_label)

        self.source_entry = Gtk.Entry(text=self.source_app)
        source_row.append(self.source_entry)
        outer.append(source_row)

        outer.append(self._make_section_label("Copied text"))
        text_view = Gtk.TextView()
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_buffer = text_view.get_buffer()
        self.text_buffer.set_text(self.initial_text)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_child(text_view)
        text_scroll.set_vexpand(True)
        outer.append(text_scroll)

        outer.append(self._make_section_label("Optional note"))
        note_view = Gtk.TextView()
        note_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.note_buffer = note_view.get_buffer()
        note_scroll = Gtk.ScrolledWindow()
        note_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        note_scroll.set_min_content_height(120)
        note_scroll.set_child(note_view)
        outer.append(note_scroll)

        sensitivity_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sensitivity_row.append(self._make_section_label("Sensitivity override"))
        self.sensitivity_dropdown = Gtk.DropDown.new_from_strings(["default", "public", "private", "sensitive"])
        sensitivity_row.append(self.sensitivity_dropdown)
        outer.append(sensitivity_row)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda *_: self.quit())
        button_row.append(cancel_button)

        save_button = Gtk.Button(label="Save to MouseKB")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_save_clicked)
        button_row.append(save_button)
        outer.append(button_row)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        outer.append(self.status_label)

        self.window.set_child(outer)
        self.window.present()

        if not self.clipboard_prefilled:
            display = Gdk.Display.get_default()
            if display is not None:
                clipboard = display.get_clipboard()
                clipboard.read_text_async(None, self._on_clipboard_text_ready)

    def _make_section_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        return label

    def _buffer_text(self, buffer: Gtk.TextBuffer | None) -> str:
        if buffer is None:
            return ""
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, False).strip()

    def _on_save_clicked(self, *_args) -> None:
        copied_text = self._buffer_text(self.text_buffer)
        if not copied_text:
            if self.status_label:
                self.status_label.set_text("Nothing to save yet.")
            return

        payload: dict[str, str | None] = {
            "copied_text": copied_text,
            "source_app": self.source_entry.get_text().strip() if self.source_entry else "clipboard",
            "user_note": self._buffer_text(self.note_buffer) or None,
        }
        if self.sensitivity_dropdown:
            selected = self.sensitivity_dropdown.get_selected_item()
            if selected is not None:
                sensitivity_value = selected.get_string()
                if sensitivity_value != "default":
                    payload["sensitivity_override"] = sensitivity_value

        try:
            response = post_clipboard_capture(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            if self.status_label:
                self.status_label.set_text(f"Save failed: {detail}")
            return
        except OSError as exc:
            if self.status_label:
                self.status_label.set_text(f"Could not reach local API: {exc}")
            return

        if self.status_label:
            self.status_label.set_text(f"Saved {response['id']} to inbox.")

    def _on_clipboard_text_ready(self, clipboard: Gdk.Clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except Exception:
            text = None
        if text and self.text_buffer:
            self.text_buffer.set_text(text)

    def run_app(self) -> int:
        return self.run(sys.argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open the MouseKB quick-capture window.")
    parser.add_argument("--text", default="", help="Prefill the captured text instead of reading from the clipboard.")
    parser.add_argument("--source-app", default="clipboard", help="Label for the source application.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    initial_text = args.text or read_clipboard_text()
    window = QuickCaptureWindow(initial_text=initial_text, source_app=args.source_app)
    return window.run_app()


if __name__ == "__main__":
    raise SystemExit(main())
