# Zero Hour Replay Analyzer

Upload a Command & Conquer Generals Zero Hour replay (`.rep`) and get a quick breakdown of what each player did.

## What it does

- Parses `GENREP` replay files (Generals / Zero Hour format).
- Extracts replay metadata (map, version, start/end time, credits).
- Reads replay command chunks and groups actions by player.
- Reports top actions and estimated APM per player.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run web uploader

```powershell
uvicorn replay_tool.web:app --reload
```

Open `http://127.0.0.1:8000` and upload a `.rep` file.

## Easy Windows launcher

Double-click:

```text
Run-ReplayTool.bat
```

It installs dependencies and starts the app automatically.

## Build single EXE (to share)

Double-click:

```text
Build-Exe.bat
```

After build, send:

```text
dist\ReplayTool.exe
```

## Run CLI analyzer

```powershell
python main.py analyze path\to\replay.rep
```

## Build template ID -> name map (recommended)

```powershell
python main.py build-id-map "C:\Path\To\Zero Hour"
```

## Notes

- APM is estimated from replay timecodes using 30 ticks/second.
- Some unknown replay order IDs may appear as `Unknown<id>`.
- Unit/building names for `template_id` can be mapped in `replay_tool/id_lookup.json`.
