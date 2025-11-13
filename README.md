# queuectl — Background Job Queue (Python, Windows)

A minimal CLI-based background job queue system supporting workers, retries with exponential backoff, a Dead Letter Queue (DLQ), job persistence (SQLite), and configuration.

This README includes **all Windows PowerShell commands** needed to run, test, and record the assignment demo.

---

# 📦 Requirements

- Windows 10/11  
- Python 3.9+  
- PowerShell  

---

# 🛠️ Setup (PowerShell)

## 1. Go to project folder

```powershell
cd "C:\Users\<YourUser>\Downloads\queuectl"
```

## 2. Create & activate virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate
```

---

# 🚀 Running the System (For Demo Video)

You will use **two PowerShell terminals**:

- **Terminal 1 → workers**
- **Terminal 2 → enqueue + status + dlq**

---

# 🟦 Terminal 1 — Start Workers

```powershell
cd "C:\Users\<YourUser>\Downloads\queuectl"
.\venv\Scripts\Activate
python queuectl.py worker start --count 2
```

This terminal stays running.  
It will show job processing, retries, backoff, and DLQ transitions.

---

# 🟩 Terminal 2 — Enqueue Jobs & Check Status

Activate environment:

```powershell
cd "C:\Users\<YourUser>\Downloads\queuectl"
.\venv\Scripts\Activate
```

### Enqueue example jobs:

```powershell
python queuectl.py enqueue --file examples\job_success.json
python queuectl.py enqueue --file examples\job_fail.json
python queuectl.py enqueue --file examples\job_sleep.json
```

---

# 📊 Check Job States

```powershell
python queuectl.py status
```

List jobs:

```powershell
python queuectl.py list --state pending
python queuectl.py list --state processing
python queuectl.py list --state completed
python queuectl.py list --state failed
python queuectl.py list --state dead
```

---

# 🟥 Dead Letter Queue (DLQ)

### List dead jobs:

```powershell
python queuectl.py dlq list
```

### Retry a dead job:

```powershell
python queuectl.py dlq retry job_fail
```

Workers in Terminal 1 will pick it again.

---

# ⚙️ Configuration Management

View current config:

```powershell
python queuectl.py config get
```

Update config:

```powershell
python queuectl.py config set max_retries 5
python queuectl.py config set backoff_base 3
```

---

# 🔄 Persistence Test (Required)

1. Enqueue a job  
2. Stop both terminals  
3. Open Terminal 1 again  
4. Start workers  
5. In Terminal 2 run `status`  

Jobs are still present because of SQLite persistence.

---

# 🧪 Automated Test Script (Optional)

Allow script execution:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Run:

```powershell
.\scripts\test_flow.ps1
```

---

# 🧩 Architecture Overview (Minimal)

- **SQLite** database used for persistence  
- Workers run in threads, each holding its own DB connection  
- Job claiming uses a transactional `UPDATE` to avoid duplicates  
- Retry uses exponential backoff: `delay = base^attempts`  
- After exceeding retries, job moves to state `dead` (DLQ)  
- `dlq retry <id>` resets attempts and moves job back to pending  
- Workers exit gracefully after finishing their current job  

---

```
## 🎥 Demo Video
https://drive.google.com/
```

# ✅ Submission Checklist

- [x] All required commands functional  
- [x] Jobs persist after restart  
- [x] Retry + exponential backoff working  
- [x] Dead Letter Queue operational  
- [x] CLI documented  
- [x] Code maintainable  
- [x] Test script included  

