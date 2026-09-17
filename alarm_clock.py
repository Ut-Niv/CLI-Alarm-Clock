from __future__ import annotations


import argparse
import os
import platform
import re
import sys
import threading
import time

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta

# Optional pretty printing
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.live import Live

    RICH = True
    console = Console()
except ImportError:
    RICH = False
    console = None

_next_id = 1
_id_lock = threading.Lock()

def _parse_relative(spec: str) -> datetime:
    spec = re.sub(r"\s+", "", spec.lower())
    if not spec:
        raise ValueError("Empty relative duration")

    total = timedelta()
    # Match sequences of number + unit
    pattern = re.compile(r"(\d+)([dhms])")
    matches = pattern.findall(spec)

    if not matches or "".join(n + u for n, u in matches) != spec:
        raise ValueError(f"Invalid Relative Duration '{spec}'")

    for num_str, unit in matches:
        n = int(num_str)
        if unit == "d":
            total += timedelta(days=n)
        if unit == "h":
            total += timedelta(hours=n)
        if unit == "m":
            total += timedelta(minutes=n)
        if unit == "s":
            total += timedelta(seconds=n)

    if total.total_seconds() <= 0:
        raise ValueError("Duration must be positive")

    return datetime.now() + total

def parse_time_spec(spec: str) -> datetime:
    spec = spec.strip()

    if spec.startswith("+"):
        return _parse_relative(spec[1:])
    
    now = datetime.now()
    formats = [
        "%H:%M:%S",
        "%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(spec, fmt)
            if fmt in ("%H:%M", "%H:%M:%S"):
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
                if dt<=now:
                    dt +=timedelta(days=1)
            return dt
        except ValueError:
            continue
    
    raise ValueError(
        f"cannot parse time'{spec}'."
        "Use HH:MM, HH:MM:SS, YYYY-MM-DD HH:MM, or relative +25m / +1h30m"
    )

def print_help() -> None:
    help_text = """
Commands:
  set <time> [label...]   Set alarm. Examples:
                            set 07:30
                            set 14:15:00 Meeting
                            set +25m tea
                            set +1h30m
  list / ls               Show pending alarms
  cancel <id>             Cancel alarm by id
  clear                   Remove all alarms
  help                    Show this help
  quit / exit / q         Exit
"""
    print(help_text)

def print_alarms(alarms: list[Alarm]) -> None:
    if not alarms:
        print("  No alarms set.")
        return

    if RICH:
        table = Table(title="Pending Alarms")
        table.add_column("ID", justify="right")
        table.add_column("Target", style="green")
        table.add_column("Remaining")
        table.add_column("Label")
        table.add_column("Snoozes", justify="right")

        for alarm in alarms:
            rem = alarm.remaining()
            rem_str = "DUE" if rem.total_seconds() < 0 else str(rem).split(".")[0]
            table.add_row(
                str(alarm.id),
                alarm.target.strftime("%Y-%m-%d %H:%M:%S"),
                rem_str,
                alarm.label or "_",
                str(alarm.snooze),
            )
        console.print(table)
    else:
        print(f" {'ID':>4} {'Target':<19} {'Remaining':<12} {'Label'}")
        print("  " + "-" * 60)
        for a in alarms:
            print(f" {a}")

def interactive_loop(manager: AlarmManager) -> None:
    print("Alarm Clock Interactive Mode")
    print("Type 'help' for commands, 'exit' to quit.")
    manager.start_worker()

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                print("\nExiting interactive mode.")
                break

            if not line:
                continue

            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("exit", "quit", "q"):
                print("Exiting interactive mode.")
                break
            elif cmd == "help":
                print_help()
            elif cmd in ("list", "ls"):
                print_alarms(manager.list())
            elif cmd == "clear":
                n = manager.clear()
                print(f"  Cleared {n} alarm(s)")
            elif cmd == "cancel":
                if not arg:
                    print("  Usage: cancel <id>")
                    continue
                try:
                    aid = int(arg)
                except ValueError:
                    print("  ID must be an integer")
                    continue
                if manager.cancel(aid):
                    print(f"  Cancelled alarm #{aid}")
                else:
                    print(f"  No alarm with id #{aid}")
            elif cmd == "set":
                if not arg:
                    print("  Usage: set <time> [label]")
                    continue
                # Split time vs label
                tokens = arg.split(maxsplit=1)
                time_spec = tokens[0]
                label = tokens[1] if len(tokens) > 1 else ""
                try:
                    target = parse_time_spec(time_spec)
                    alarm = manager.add(target, label)
                    rem = alarm.remaining()
                    print(f"  ✓ Alarm #{alarm.id} set for {target.strftime('%Y-%m-%d %H:%M:%S')} "
                          f"(in {str(rem).split('.')[0]})")
                except ValueError as e:
                    print(f"  Error: {e}")
            else:
                print(f"  Unknown command '{cmd}'. Type 'help'.")
    finally:
        manager.stop_worker()
        print("Goodbye.")

def play_alarm_sound(repeat: int = 5) -> None:
    pass

def _get_next_id() -> int:
    global _next_id
    with _id_lock:
        id_ = _next_id
        _next_id += 1
        return id_

@dataclass
class Alarm:
    id: int
    target: datetime
    label: str = ""
    created: datetime = field(default_factory=datetime.now)
    snoozed: int = 0

    def remaining(self) -> timedelta:
        return self.target - datetime.now()

    def is_due(self) -> bool:
        return datetime.now() >= self.target

    def snooze(self, minutes: int = 5) -> None:
        self.target = datetime.now() + timedelta(minutes=minutes)
        self.snoozed += 1

    def __str__(self) -> str:
        rem = self.remaining()
        rem_str = "DUE" if rem.total_seconds() < 0 else str(rem).split(".")[0]
        return f"{self.id:>4} {self.target.strftime('%Y-%m-%d %H:%M:%S')} {rem_str:<12} {self.label or '_'} {self.snoozed}"

# Alarm Manager (thread safe for our use case)
class AlarmManager:
    def __init__(self) -> None:
        self._alarms: List[Alarm] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def add(self, target: datetime, label: str = "") -> Alarm:
        alarm = Alarm(id=_get_next_id(), target=target, label=label)
        with self._lock:
            self._alarms.append(alarm)
            self._alarms.sort(key=lambda a: a.target)
        return alarm

    def list(self) -> List[Alarm]:
        with self._lock:
            return list(self._alarms)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            due: List[Alarm] = []
            sleep_for = 1.0
            with self._lock:
                still_pending = []
                now = datetime.now()
                for alarm in self._alarms:
                    if alarm.target <= now:
                        due.append(alarm)
                    else:
                        still_pending.append(alarm)
                        rem = (alarm.target - now).total_seconds()
                        if rem < sleep_for:
                            sleep_for = max(0.05, rem)
                self._alarms = still_pending

            for alarm in due:
                self._fire(alarm)

    def _fire(self, alarm: Alarm) -> None:
        "Called from worker thread when an alarm is due."

        msg = f"ALARM #{alarm.id}"
        if alarm.label:
            msg += f" - {alarm.label}"
        print(f"\n{msg} - {alarm.target.strftime('%Y-%m-%d %H:%M:%S')}")

        if RICH:
            console.print(Panel(msg, style="bold red", title="WAKE UP"))
        else:
            print("\n" + "=" * 40)
            print(f" {msg} ")
            print("=" * 40 + "\n")

        play_alarm_sound(repeat=5)

        try:
            answer = input("Snooze for 5 minutes? (y/n): ").strip().lower()
            if answer in ("s", "snooze", "y", "yes"):
                alarm.snooze(minutes=5)
                with self._lock:
                    self._alarms.append(alarm)
                    self._alarms.sort(key=lambda a: a.target)
                print(f"  Snoozed alarm #{alarm.id} for 5 minutes.")
            else:
                print(f"  Alarm #{alarm.id} dismissed.")
        except EOFError:
            print(f"  Alarm #{alarm.id} dismissed.")

    def start_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def stop_worker(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)

    def clear(self) -> int:
        with self._lock:
            n = len(self._alarms)
            self._alarms.clear()
            return n

    def cancel(self, alarm_id: int) -> bool:
        with self._lock:
            for i, alarm in enumerate(self._alarms):
                if alarm.id == alarm_id:
                    del self._alarms[i]
                    return True
        return False

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI Alarm Clock - set one or more alarm from the terminal",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog="""
    Ex: 
        python alarm_clock.py
        python alarm_clock.py --set 07:30
        python alarm_clock.py --set +10m "tea"
    """
    )
    parser.add_argument(
        "--set", "-s",
        metavar="TIME",
        help="Set a single alarm and wait for it(then exit)",
    )
    parser.add_argument(
        "--label", "-1",
        default="",
        help="Optional label to set alarm",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="With --set: exit immediately after the alarm fires",
    )

    args = parser.parse_args()
    manager = AlarmManager()

    if args.set:
        try:
            target = parse_time_spec(args.set)
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        
        alarm = manager.add(target, args.label)
        print(f"Alarm #{alarm.id} set for {target.strftime('%Y-%m-%d %H:%M:%S')}")
        print("Waiting... (Ctrl+C to cancel)")
        manager.start_worker()

        try:
            while True:
                alarm = manager.list()
                if not alarm:
                    print("No more alarms. Exiting.")
                    break

                a = alarm[0]
                rem = a.remaining()
                if rem.total_seconds() > 0:
                    print(f"\rNext alarm #{a.id} in {rem}.", end="", flush=True)
                    time.sleep(0.5)

        except KeyboardInterrupt:
            print("\nCencelled.")
        finally:
            manager.stop_worker()
    else:
        interactive_loop(manager)


if __name__ == "__main__":
    main()
