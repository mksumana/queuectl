# queuectl — Background Job Queue (Python starter)

This repository contains a **single-file, production-minded starter** implementation of the `queuectl` CLI described in the assignment. It implements job persistence (SQLite), workers, retries with exponential backoff, a dead letter queue (DLQ), config management and a small test script.

## Files included

- `queuectl.py` — Main CLI program (Python 3.9+). Run this file for all operations.
- `test_flow.sh` — Small shell script that demonstrates the main flows.
- `README.md` — This file.

## Quick start

Make the main script executable and run workers:

```bash
chmod +x queuectl.py
./queuectl.py worker start --count 2
```

Enqueue a job in another terminal:

```bash
./queuectl.py enqueue '{"id":"job-hello","command":"echo Hello World","max_retries":3}'
```

List pending jobs:

```bash
./queuectl.py list --state pending
```

View DLQ:

```bash
./queuectl.py dlq list
```

Retry a DLQ job:

```bash
./queuectl.py dlq retry <job-id>
```

Set configuration (globally stored in DB):

```bash
./queuectl.py config set max_retries 5
./queuectl.py config set backoff_base 3
./queuectl.py config get
```

Stop workers (from another terminal):

```bash
./queuectl.py worker stop
```

## Architecture notes

- **Persistence**: SQLite (`queue.db`) with WAL mode. Jobs stored with available_at epoch seconds so retries can be delayed.
- **Workers**: Each `worker start` runs a single process with N threads (use `--count N`). Within each thread jobs are claimed using a short `BEGIN IMMEDIATE` transaction to avoid races.
- **Locking**: Claiming a job uses `UPDATE` inside a transaction to ensure only one worker gets it.
- **Retry/backoff**: On failure, `attempts` increments. If `attempts > max_retries` job is moved to `dead`. Otherwise job state becomes `failed` and `available_at` is set to `now + base^attempts`.
- **DLQ**: `state='dead'` represents the DLQ. `dlq retry` resets attempts and moves job back to pending.
- **Graceful shutdown**: `SIGINT`/`SIGTERM` sets a stop flag so workers finish current job then exit.

## Testing instructions

1. Run `chmod +x queuectl.py` and `./queuectl.py worker start --count 2` in one terminal.
2. In another terminal run the `test_flow.sh` example or enqueue jobs manually.
3. Observe the worker terminal processing jobs, failing and moving to DLQ after retries.
4. Restart the worker process and verify jobs persist.

## Next improvements / bonus tasks

- Job timeout handling (kill long-running jobs)
- Job priority and scheduled jobs (run_at)
- Job output logging files
- Small web dashboard for live monitoring
- Unit tests with a temporary SQLite DB and mocking subprocess

