# pyvp — Python Virtual Platform Controller

[![Lint](https://github.com/machineware-gmbh/pyvp/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/machineware-gmbh/pyvp/actions/workflows/lint.yml)
[![Format](https://github.com/machineware-gmbh/pyvp/actions/workflows/format.yml/badge.svg?branch=main)](https://github.com/machineware-gmbh/pyvp/actions/workflows/format.yml)

`pyvp` is an interactive command-line tool for controlling
[VCML](https://github.com/machineware-gmbh/vcml)-based virtual platforms.
It connects to a running simulation over a TCP socket and lets you inspect
module hierarchies, read/write attributes, run commands, step execution,
and set breakpoints.

## Requirements

- Python 3.9+
- A running VCML simulation with VSP server enabled
- `readline` (optional, enables tab completion)

## Usage

```
./pyvp.py [<host>:]<port>
```

Connect to a simulation listening on `localhost:5555`:
```
./pyvp.py 5555
```

Connect to a remote simulation:
```
./pyvp.py myhost:5555
```

## Commands

| Command      | Alias | Description |
|--------------|-------|-------------|
| `connect`    | `t`   | Connect to a simulation |
| `disconnect` | `d`   | Disconnect without terminating |
| `quit`       | `q`   | Disconnect and exit |
| `kill`       | `k`   | Terminate the simulation |
| `info`       | `i`   | Show simulation info |
| `step`       | `s`   | Step to next timestamp |
| `stepi`      | `si`  | Step one instruction |
| `run`        | `c`   | Run until interrupted |
| `list`       | `l`, `ls` | List module hierarchy |
| `ll`         |       | Long listing with types |
| `cd`         |       | Change current module |
| `read`       | `r`   | Read attribute(s) |
| `exec`       | `x`   | Execute a module command |
| `break`      | `b`   | Set a breakpoint |
| `delete`     |       | Delete a breakpoint |
| `events`     |       | Show, add or remove event handlers: `events add\|rm trace\|led\|uart <module>...`, `events log [file]` |
| `sessions`   |       | List local simulation sessions |
| `trace`      |       | Print transactions of all ports below the given modules (default: current module) |
| `untrace`    |       | Stop tracing the given modules |
| `watch`      |       | Show the LEDs below the given modules (default: current module) |
| `unwatch`    |       | Stop watching the given modules |
| `follow`     |       | Show terminal output below the given modules, line by line (default: current module) |
| `unfollow`   |       | Stop following the given modules |
| `help`       | `h`   | Show help |

Tab completion is available when `readline` is installed.

## Session events

Simulators publish events for selected objects: `trace` for the transactions
of ports, sockets and registers, `led` for `vcml::gpio::leds` and `uart` for
`vcml::serial::terminal`. A handler on a module receives the events of all
publishers below it; handlers can only be changed while the simulation is
stopped. Events are delivered with the status updates, so all events up to a
stop have been delivered once `step()` or `stop()` returns.

```python
import vcml

info = vcml.Session.local_sessions()[0]
sess = vcml.Session(info.address())

cpu = sess.find_module("system.cpu0")
if cpu.is_traceable():
    # all protocols
    cpu.on_trace(lambda info, tx: print(vcml.format_trace(info, tx)))

    # only TLM transactions, tx is a vcml.TraceTlm
    cpu.on_trace(lambda info, tx: print(info.dir, hex(tx.address)), vcml.TraceTlm)

sess.on_events_dropped(lambda n: print(f"{n} events dropped"))
sess.step(10_000)

cpu.on_trace(None)  # unsubscribe
```

Times are in picoseconds. `Session.local_sessions()` also removes the announce
files of simulations of the current user that ended without cleaning up.

## Testing

```
pip install pytest
SIMPLEVP=/path/to/simplevp pytest tests
```

Tests that need a simulator are skipped when `SIMPLEVP` is not set.

## License

This project is licensed under the Apache License, Version 2.0 —
see the [LICENSE](LICENSE) file for details.

