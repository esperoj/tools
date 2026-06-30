#!/usr/bin/env python3
"""Command-line interface for the Wayback Machine."""

import argparse
import json
import sys
import threading
from typing import Any

try:
    import curses
except ImportError:
    curses = None

from wayback_machine import WaybackMachine


class Reporter:
    """Unified UI reporting system for basic logs, JSON pipelines, and Curses."""

    def __init__(self, mode: str, workers: int):
        self.mode = mode
        self.workers = workers
        self.lock = threading.Lock()
        self.stdscr = None

    def __enter__(self):
        if self.mode == "curses" and sys.stdout.isatty() and curses:
            self.stdscr = curses.initscr()
            curses.noecho()
            curses.cbreak()
            curses.curs_set(0)
            self.stdscr.clear()
            self._write(0, f"=== Wayback Machine: SPN2 ({self.workers} Workers) ===", curses.A_REVERSE)
        return self

    def __exit__(self, *args):
        if self.stdscr:
            curses.nocbreak()
            curses.echo()
            curses.curs_set(1)
            curses.endwin()

    def handle(self, url: str, slot: int, status: str, msg: str):
        with self.lock:
            if self.mode == "json":
                print(json.dumps({"url": url, "slot": slot, "status": status, "message": msg}))
                sys.stdout.flush()
            
            elif self.mode == "basic":
                if status in ("OK", "FAIL"):
                    print(f"[{slot}] [{status:4}] {url} -> {msg}", file=sys.stderr)
                elif status == "INIT":
                    print(f"[{slot}] [{status:4}] {url}", file=sys.stderr)
            
            elif self.stdscr:
                try:
                    y = 2 + (slot * 3)
                    if y + 1 >= curses.LINES: return
                    icon = "▶" if status in ("INIT","WAIT","SAVE","POLL") else "✅" if status == "OK" else "❌"
                    self._write(y, f"{icon} W{slot+1} | {url}", curses.A_BOLD)
                    self._write(y + 1, f"[{status}] {msg}", curses.A_NORMAL)
                    self.stdscr.refresh()
                except curses.error: pass

    def hold(self):
        if self.stdscr:
            self._write(curses.LINES - 1, "Finished. Press any key to exit...", curses.A_REVERSE)
            self.stdscr.refresh()
            self.stdscr.getch()

    def _write(self, y: int, text: str, attr: int):
        clean = text.replace("\n", "")[:curses.COLS - 1].ljust(curses.COLS - 1)
        self.stdscr.addstr(y, 0, clean, attr)


def parse_inputs(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Merges URLs from positional args, --json, and stdin into a unified list of dicts."""
    raw_inputs = []
    
    if args.json:
        try:
            parsed = json.loads(args.json)
            raw_inputs.extend(parsed if isinstance(parsed, list) else [parsed])
        except json.JSONDecodeError:
            print("[!] Invalid JSON passed to --json", file=sys.stderr)
            sys.exit(1)
            
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            try:
                parsed = json.loads(data)
                raw_inputs.extend(parsed if isinstance(parsed, list) else [parsed])
            except json.JSONDecodeError:
                raw_inputs.extend([line for line in data.splitlines() if line.strip()])

    raw_inputs.extend(args.urls)

    return [j if isinstance(j, dict) else {"url": j} for j in raw_inputs if j]


def run_save(args: argparse.Namespace):
    """Executes the 'save' sub-command."""
    jobs = parse_inputs(args)
    if not jobs:
        print("[!] No URLs provided to save.", file=sys.stderr)
        sys.exit(1)

    try:
        client = WaybackMachine(
            api_key=args.api_key, api_secret=args.api_secret,
            proxy_prefix=args.proxy, max_workers=args.workers, dry_run=args.dry_run
        )
    except ValueError as e:
        print(f"[!] Initialization Error: {e}", file=sys.stderr)
        sys.exit(1)

    ui_mode = args.ui if not (args.ui == "curses" and not curses) else "basic"
    reporter = Reporter(mode=ui_mode, workers=args.workers)
    default_opts = {"capture_outlinks": args.capture_outlinks}

    with reporter:
        results = client.save_batch(jobs, default_opts, on_event=reporter.handle)
        reporter.hold()

    if args.ui != "json":
        print("\n--- Final Results ---", file=sys.stderr)
        for r in results:
            if r["archive_url"]:
                print(r["archive_url"], file=sys.stdout)
            else:
                print(f"[FAIL] {r['url']} -> {r['error']}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Wayback Machine CLI Client.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Global options parser (to share across future commands)
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--proxy", default="https://proxy.esperoj.workers.dev/", help="Proxy prefix")
    global_parser.add_argument("--workers", type=int, default=4, help="Concurrent workers")
    global_parser.add_argument("--ui", choices=["basic", "json", "curses"], default="basic", help="Output format")

    # Command: save
    save_parser = subparsers.add_parser("save", parents=[global_parser], help="Archive URLs via SPN2 API")
    save_parser.add_argument("urls", nargs="*", help="URLs to archive (or via stdin)")
    save_parser.add_argument("--json", help="Pass a JSON payload array/object")
    save_parser.add_argument("--api-key", help="SPN2 Access Key")
    save_parser.add_argument("--api-secret", help="SPN2 Secret Key")
    save_parser.add_argument("--dry-run", action="store_true", help="Simulate execution")
    save_parser.add_argument("--capture-outlinks", type=int, choices=[0, 1], default=0, help="Archive outlinks")

    # Setup for future commands (e.g. CDX, Check)
    # cdx_parser = subparsers.add_parser("cdx", parents=[global_parser], help="Search CDX Index")

    args = parser.parse_args()

    if args.command == "save":
        run_save(args)


if __name__ == "__main__":
    main()
