#!/usr/bin/env bash
# Demonstrates basic flows. Run workers in a separate terminal.
set -euo pipefail
python3 queuectl.py enqueue '{"id":"job1","command":"echo Hello; exit 0","max_retries":2}'
python3 queuectl.py enqueue '{"id":"job2","command":"bash -c \"exit 1\"","max_retries":2}'
python3 queuectl.py enqueue '{"id":"job3","command":"sleep 2 && echo done","max_retries":1}'
# Start workers in background for demo (you can also start in a separate terminal)
python3 queuectl.py worker start --count 2 &
sleep 1
python3 queuectl.py status
sleep 6
python3 queuectl.py status
python3 queuectl.py dlq list
