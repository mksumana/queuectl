#!/usr/bin/env python3
"""
queuectl.py

Background job queue system — Windows-safe version
(no escaped quotes, no special characters)
"""

import argparse
import sqlite3
import os
import sys
import threading
import time
import subprocess
import json
import uuid
import signal
from datetime import datetime, timezone

DB_PATH = os.environ.get("QUEUECTL_DB", "queue.db")
PID_FILE = os.environ.get("QUEUECTL_PID", "queuectl.pid")
DEFAULT_CONFIG = {"max_retries": 3, "backoff_base": 2}

stop_event = threading.Event()


def now_ts():
    return int(time.time())


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            created_at TEXT,
            updated_at TEXT,
            available_at INTEGER,
            last_error TEXT,
            worker TEXT,
            output TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    for k, v in DEFAULT_CONFIG.items():
        c.execute(
            "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)",
            (k, json.dumps(v)),
        )
    conn.commit()
    return conn


def get_config(conn, key):
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    if not row:
        return None
    return json.loads(row[0])


def set_config(conn, key, value):
    c = conn.cursor()
    c.execute("REPLACE INTO config(key,value) VALUES(?,?)", (key, json.dumps(value)))
    conn.commit()


def enqueue_job(conn, job_json: str):
    job = json.loads(job_json)

    if "id" not in job:
        job["id"] = str(uuid.uuid4())

    job.setdefault("state", "pending")
    job.setdefault("attempts", 0)
    job.setdefault(
        "max_retries",
        get_config(conn, "max_retries") or DEFAULT_CONFIG["max_retries"],
    )

    ts = iso_now()
    job["created_at"] = job.get("created_at", ts)
    job["updated_at"] = ts

    available_at = now_ts()

    c = conn.cursor()
    c.execute(
        """
        INSERT INTO jobs(id,command,state,attempts,max_retries,created_at,updated_at,available_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            job["id"],
            job["command"],
            job["state"],
            job["attempts"],
            job["max_retries"],
            job["created_at"],
            job["updated_at"],
            available_at,
        ),
    )
    conn.commit()
    print(f"Enqueued job {job['id']}")


def list_jobs(conn, state=None):
    c = conn.cursor()
    if state:
        c.execute(
            """SELECT id,command,state,attempts,max_retries,created_at,updated_at,available_at,last_error
               FROM jobs WHERE state=? ORDER BY created_at""",
            (state,),
        )
    else:
        c.execute(
            """SELECT id,command,state,attempts,max_retries,created_at,updated_at,available_at,last_error
               FROM jobs ORDER BY created_at"""
        )

    rows = c.fetchall()
    for r in rows:
        print(
            json.dumps(
                {
                    "id": r[0],
                    "command": r[1],
                    "state": r[2],
                    "attempts": r[3],
                    "max_retries": r[4],
                    "created_at": r[5],
                    "updated_at": r[6],
                    "available_at": r[7],
                    "last_error": r[8],
                }
            )
        )


def status(conn):
    c = conn.cursor()
    c.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state")
    counts = {row[0]: row[1] for row in c.fetchall()}

    print("Job states:")
    for st in ["pending", "processing", "completed", "failed", "dead"]:
        print(f"  {st}: {counts.get(st, 0)}")

    pid = read_pid()
    active = False

    if pid:
        try:
            os.kill(pid, 0)
            active = True
        except Exception:
            active = False

    print(f"Active worker process: {active} (pid: {pid})")


def claim_next_job(conn, worker_name):
    """
    Atomically selects a job for a worker.
    """

    c = conn.cursor()
    now = now_ts()

    try:
        c.execute("BEGIN IMMEDIATE")

        c.execute(
            """
            SELECT id,command,attempts,max_retries
            FROM jobs
            WHERE state IN ('pending','failed')
            AND available_at <= ?
            ORDER BY created_at
            LIMIT 1
            """,
            (now,),
        )

        row = c.fetchone()
        if not row:
            conn.commit()
            return None

        job_id = row[0]

        c.execute(
            """
            UPDATE jobs
            SET state='processing', worker=?, updated_at=?
            WHERE id=? AND state IN ('pending','failed')
            """,
            (worker_name, iso_now(), job_id),
        )

        if c.rowcount == 0:
            conn.commit()
            return None

        conn.commit()

        return {
            "id": row[0],
            "command": row[1],
            "attempts": row[2],
            "max_retries": row[3],
        }

    except sqlite3.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def update_job_on_success(conn, job_id, output):
    c = conn.cursor()
    c.execute(
        """
        UPDATE jobs
        SET state='completed', updated_at=?, output=?, worker=NULL
        WHERE id=?
        """,
        (iso_now(), output, job_id),
    )
    conn.commit()


def update_job_on_failure(conn, job, returncode, stderr):
    c = conn.cursor()

    attempts = job["attempts"] + 1
    max_retries = job["max_retries"]
    base = get_config(conn, "backoff_base") or DEFAULT_CONFIG["backoff_base"]

    if attempts > max_retries:
        c.execute(
            """
            UPDATE jobs
            SET state='dead', attempts=?, last_error=?, updated_at=?, worker=NULL
            WHERE id=?
            """,
            (attempts, f"Exit {returncode}: {stderr}", iso_now(), job["id"]),
        )
        conn.commit()
        return "dead"

    delay = int(base) ** attempts
    new_time = now_ts() + delay

    c.execute(
        """
        UPDATE jobs
        SET state='failed', attempts=?, last_error=?, updated_at=?, available_at=?, worker=NULL
        WHERE id=?
        """,
        (attempts, f"Exit {returncode}: {stderr}", iso_now(), new_time, job["id"]),
    )
    conn.commit()
    return "failed"


def run_command(command):
    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True
        )
        output = completed.stdout + completed.stderr
        return completed.returncode, output
    except Exception as e:
        return 1, str(e)


def worker_loop(worker_name, _):
    # Each worker gets its own SQLite connection to avoid thread errors
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")

    print(f"Worker {worker_name} started")
    print(f"Worker {worker_name} started")

    while not stop_event.is_set():
        job = claim_next_job(conn, worker_name)

        if not job:
            time.sleep(0.5)
            continue

        print(f"{worker_name} picked job {job['id']}: {job['command']}")

        rc, out = run_command(job["command"])

        if rc == 0:
            print(f"Job {job['id']} completed")
            update_job_on_success(conn, job["id"], out)
        else:
            new_state = update_job_on_failure(conn, job, rc, out[:500])
            print(f"Job {job['id']} failed → {new_state}")

    print(f"Worker {worker_name} exiting gracefully")


def start_workers(conn, count):
    pid = os.getpid()
    with open(PID_FILE, "w") as f:
        f.write(str(pid))

    threads = []
    for i in range(count):
        t = threading.Thread(
            target=worker_loop, args=(f"worker-{i+1}", conn), daemon=True
        )
        threads.append(t)
        t.start()

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping workers…")
        stop_event.set()

    for t in threads:
        t.join()

    try:
        os.remove(PID_FILE)
    except:
        pass


def stop_workers():
    pid = read_pid()
    if not pid:
        print("No active workers.")
        return

    print(f"Stopping worker process {pid}…")
    try:
        os.kill(pid, signal.SIGINT)
    except Exception:
        print("Could not stop process.")
        pass


def read_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        return int(open(PID_FILE).read().strip())
    except:
        return None


def dlq_list(conn):
    c = conn.cursor()
    c.execute(
        """
        SELECT id,command,attempts,max_retries,created_at,updated_at,last_error
        FROM jobs WHERE state='dead'
        ORDER BY created_at
        """
    )

    for r in c.fetchall():
        print(
            json.dumps(
                {
                    "id": r[0],
                    "command": r[1],
                    "attempts": r[2],
                    "max_retries": r[3],
                    "created_at": r[4],
                    "updated_at": r[5],
                    "last_error": r[6],
                }
            )
        )


def dlq_retry(conn, job_id):
    c = conn.cursor()
    c.execute("SELECT id FROM jobs WHERE id=? AND state='dead'", (job_id,))
    if not c.fetchone():
        print("Job not found in DLQ")
        return

    c.execute(
        """
        UPDATE jobs
        SET state='pending', attempts=0, available_at=?, updated_at=?, last_error=NULL
        WHERE id=?
        """,
        (now_ts(), iso_now(), job_id),
    )
    conn.commit()
    print(f"Requeued dead job {job_id}")


def config_set(conn, key, value):
    try:
        if key in ("max_retries", "backoff_base"):
            value = int(value)
        set_config(conn, key, value)
        print(f"Set config {key}={value}")
    except:
        print("Invalid config value")


def config_get(conn):
    c = conn.cursor()
    c.execute("SELECT key,value FROM config")
    for k, v in c.fetchall():
        print(f"{k}: {json.loads(v)}")


def main(argv):
    parser = argparse.ArgumentParser(prog="queuectl")
    sub = parser.add_subparsers(dest="cmd")

    p_enqueue = sub.add_parser("enqueue")
    p_enqueue.add_argument("job_json", nargs="?")
    p_enqueue.add_argument("--file", "-f", help="Path to job JSON file")

    p_worker = sub.add_parser("worker")
    wsub = p_worker.add_subparsers(dest="action")
    ws = wsub.add_parser("start")
    ws.add_argument("--count", type=int, default=1)
    wsub.add_parser("stop")

    sub.add_parser("status")

    p_list = sub.add_parser("list")
    p_list.add_argument("--state", default=None)

    p_dlq = sub.add_parser("dlq")
    dsub = p_dlq.add_subparsers(dest="action")
    dsub.add_parser("list")
    dr = dsub.add_parser("retry")
    dr.add_argument("job_id")

    p_conf = sub.add_parser("config")
    csub = p_conf.add_subparsers(dest="action")
    cs = csub.add_parser("set")
    cs.add_argument("key")
    cs.add_argument("value")
    csub.add_parser("get")

    args = parser.parse_args(argv)
    conn = ensure_db()

    if args.cmd == "enqueue":
        if args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                data = f.read()
            enqueue_job(conn, data)
        else:
            enqueue_job(conn, args.job_json)


    elif args.cmd == "worker":
        if args.action == "start":
            def handle(_1, _2):
                stop_event.set()

            signal.signal(signal.SIGINT, handle)
            signal.signal(signal.SIGTERM, handle)

            start_workers(conn, args.count)

        elif args.action == "stop":
            stop_workers()

    elif args.cmd == "status":
        status(conn)

    elif args.cmd == "list":
        list_jobs(conn, args.state)

    elif args.cmd == "dlq":
        if args.action == "list":
            dlq_list(conn)
        elif args.action == "retry":
            dlq_retry(conn, args.job_id)

    elif args.cmd == "config":
        if args.action == "set":
            config_set(conn, args.key, args.value)
        elif args.action == "get":
            config_get(conn)

    else:
        parser.print_help()


if __name__ == "__main__":
    main(sys.argv[1:])
