#!/usr/bin/env python3
"""
wa_export_tui.py — a Textual TUI front-end for wa_desktop_export.

Lists every WhatsApp chat and group from the local macOS ChatStorage.sqlite,
lets you filter and multi-select, and writes one WhatsApp-style export .zip
(with media) per selected chat.

Run:
    pip install textual
    python3 wa_export_tui.py                 # groups only
    python3 wa_export_tui.py --all           # include 1:1 chats
    python3 wa_export_tui.py --out ~/WhatsAppExports --me "Steve"

Keys:  ↑/↓ move · space select · a select-all (filtered) · c clear · / search
       e export selected · q quit

Read-only: the database is opened immutable; the live store is never touched.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wa_desktop_export as wde  # noqa: E402

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.widgets import DataTable, Footer, Header, Input, Static
    from textual.worker import get_current_worker
except ImportError:
    sys.exit("Textual is required:  pip install textual")


CHECK = "✔"   # ✔


class WAExportApp(App):
    CSS = """
    Screen { layout: vertical; }
    #search { dock: top; height: 3; border: round $accent; }
    #status { dock: bottom; height: auto; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    DataTable > .datatable--cursor { background: $accent 40%; }
    """

    BINDINGS = [
        Binding("space", "toggle", "Select"),
        Binding("a", "select_all", "All"),
        Binding("c", "clear", "Clear"),
        Binding("e", "export", "Export"),
        Binding("slash", "focus_search", "Search"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, db, out, me, tz, include_dms):
        super().__init__()
        self.db = db
        self.out = os.path.expanduser(out)
        self.me = me
        self.tz = wde._tzinfo(tz)
        self.include_dms = include_dms
        self.all_chats = []
        self.shown = []            # chats currently shown (display order)
        self.selected = set()        # selected session pks

    # ---- layout ----
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Input(placeholder="Type to filter chats…  (press / to focus)", id="search"),
            DataTable(id="table", zebra_stripes=True, cursor_type="row"),
            Static("", id="status"),
        )
        yield Footer()

    def on_mount(self):
        self.title = "WhatsApp Desktop Exporter"
        self.sub_title = self.db
        con = wde.open_db(self.db)
        self.all_chats = wde.list_chats(con, include_dms=self.include_dms)
        con.close()
        t = self.query_one("#table", DataTable)
        t.add_column(" ", key="sel", width=3)
        t.add_column("Chat", key="name", width=48)
        t.add_column("Type", key="type", width=6)
        t.add_column("Msgs", key="msgs", width=7)
        t.add_column("Members", key="mem", width=8)
        t.add_column("Last activity", key="last", width=16)
        self._render_rows("")
        self._status()
        t.focus()

    # ---- rendering ----
    def _render_rows(self, needle):
        t = self.query_one("#table", DataTable)
        t.clear()
        needle = needle.lower().strip()
        self.shown = [c for c in self.all_chats
                        if not needle or needle in c["name"].lower()
                        or needle in c["jid"].lower()]
        for c in self.shown:
            last = c["last"].strftime("%Y-%m-%d %H:%M") if c["last"] else ""
            mark = CHECK if c["pk"] in self.selected else ""
            t.add_row(mark, c["name"], "group" if c["is_group"] else "dm",
                      str(c["messages"]),
                      str(c["members"]) if c["is_group"] else "",
                      last, key=str(c["pk"]))

    def _status(self, msg=None):
        base = (f"{len(self.shown)} shown · {len(self.selected)} selected · "
                f"output → {self.out}")
        self.query_one("#status", Static).update(msg + "\n" + base if msg else base)

    # ---- actions ----
    def on_input_changed(self, event: Input.Changed):
        self._render_rows(event.value)
        self._status()

    def action_focus_search(self):
        self.query_one("#search", Input).focus()

    def _current_pk(self):
        t = self.query_one("#table", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self.shown):
            return None
        return self.shown[t.cursor_row]["pk"]

    def action_toggle(self):
        pk = self._current_pk()
        if pk is None:
            return
        t = self.query_one("#table", DataTable)
        row = t.cursor_row
        if pk in self.selected:
            self.selected.discard(pk)
            t.update_cell_at((row, 0), "")
        else:
            self.selected.add(pk)
            t.update_cell_at((row, 0), CHECK)
        self._status()

    def action_select_all(self):
        for c in self.shown:
            self.selected.add(c["pk"])
        self._render_rows(self.query_one("#search", Input).value)
        self._status()

    def action_clear(self):
        self.selected.clear()
        self._render_rows(self.query_one("#search", Input).value)
        self._status()

    def action_export(self):
        if not self.selected:
            self._status("Nothing selected — press space to select chats.")
            return
        pks = list(self.selected)
        self._status(f"Exporting {len(pks)} chat(s)…")
        self._run_export(pks)

    # ---- background export ----
    @work(thread=True, exclusive=True)
    def _run_export(self, pks):
        worker = get_current_worker()
        con = wde.open_db(self.db)
        done, total_media, errors = 0, 0, []
        for pk in pks:
            if worker.is_cancelled:
                break
            try:
                zip_path, stats = wde.write_zip(
                    con, pk, self.db, self.out, me_name=self.me, tz=self.tz)
                done += 1
                total_media += stats["media_present"]
                self.call_from_thread(
                    self._status,
                    f"[{done}/{len(pks)}] {stats['name']}: "
                    f"{stats['messages']} msgs, {stats['media_present']} media")
            except Exception as e:  # keep going on a bad chat
                errors.append(str(e))
        con.close()
        summary = (f"Done. {done}/{len(pks)} chats exported, "
                   f"{total_media} media files bundled, into {self.out}")
        if errors:
            summary += f"  ({len(errors)} error(s): {errors[0]})"
        self.call_from_thread(self._status, summary)


def main(argv=None):
    p = argparse.ArgumentParser(description="TUI for exporting WhatsApp desktop chats")
    p.add_argument("--db", default=wde.DEFAULT_DB, help="Path to ChatStorage.sqlite")
    p.add_argument("--out", default="~/WhatsAppExports", help="Output directory")
    p.add_argument("--me", default="You", help="Display name for your own messages")
    p.add_argument("--tz", default=None, help="IANA tz (default: system local)")
    p.add_argument("--all", action="store_true", help="Include 1:1 chats too")
    a = p.parse_args(argv)
    if not os.path.exists(a.db):
        sys.exit(f"ChatStorage.sqlite not found: {a.db}\n"
                 "Pass --db with the correct path (see the data-map doc).")
    WAExportApp(a.db, a.out, a.me, a.tz, a.all).run()


if __name__ == "__main__":
    main()
