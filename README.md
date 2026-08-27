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
| `help`       | `h`   | Show help |

Tab completion is available when `readline` is installed.

## License

This project is licensed under the Apache License, Version 2.0 —
see the [LICENSE](LICENSE) file for details.

