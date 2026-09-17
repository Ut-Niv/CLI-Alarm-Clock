# CLI Alarm Clock
A pure-Python command-line alarm clock built for a 30-minute senior software engineer exercise.

## Features

- **Flexible time input**
  - Absolute: `07:30`, `14:15:00`, `2026-09-18 09:00`
  - Relative: `+25m`, `+1h30m`, `+90s`, `+2d`
- Multiple concurrent alarms
- Interactive REPL (`set`, `list`, `cancel`, `clear`, `help`, `quit`)
- One-shot mode via flags (`--set`)
- Snooze (5 minutes) or dismiss when an alarm fires
- Cross-platform sound (Windows `winsound.Beep`, terminal bell elsewhere)
- Live remaining-time display
- Clean Ctrl+C handling
- Optional `rich` for prettier tables (falls back gracefully)

## Requirements
- Optional: `pip install rich` for nicer output

## Usage

```bash
# Interactive mode (recommended)
python alarm_clock.py

# One-shot alarm
python alarm_clock.py --set 07:30
python alarm_clock.py --set +10m --label "tea break"
python alarm_clock.py -s 14:00:00 -l "standup"
```

### Interactive commands

```
alarm> set 07:30 Morning
  ✓ Alarm #1 set for 2026-09-18 07:30:00 (in 20:45:12)

alarm> set +25m tea
  ✓ Alarm #2 set for ...

alarm> list
  (shows table of pending alarms)

alarm> cancel 2
  Cancelled alarm #2

alarm> clear
  Cleared 1 alarm(s)

alarm> quit
```

When an alarm fires you will see a loud visual + audio alert and be prompted:

```
  [S]nooze 5m / [D]ismiss / enter=dismiss >
```

## Future improvements (if more time)

- Persistent storage (JSON / SQLite)
- Custom snooze duration
- Recurring alarms (daily / weekdays)
- Desktop notifications via `plyer` or platform APIs
- Proper event queue between worker and main thread
