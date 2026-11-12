"""Attach successful Windows runtime evidence to the tested portable archive."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import zipfile


folder=Path(sys.argv[1]).resolve()
report=Path(sys.argv[2]).resolve()
validation=json.loads(report.read_text(encoding="utf-8"))
if os.name!="nt" or validation.get("status")!="passed":raise RuntimeError("A successful Windows smoke report is required")
manifest_path=folder/"BUILD-MANIFEST.json"
manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["windows_runtime_test"]="passed"
manifest["windows_validation"]={**validation,"commit":os.environ.get("GITHUB_SHA"),
                                "run_url":os.environ.get("GITHUB_SERVER_URL","")+"/"+os.environ.get("GITHUB_REPOSITORY","")+"/actions/runs/"+os.environ.get("GITHUB_RUN_ID","")}
manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
(folder/"WINDOWS-VALIDATION.json").write_text(json.dumps(manifest["windows_validation"],indent=2),encoding="utf-8")
start=folder/"START HERE.txt"
text=start.read_text(encoding="utf-8")
text=text.replace("This Windows preview has been assembled and checked on Linux, but has not\nbeen run on Windows.",
                  "This Windows preview passed automated startup, encrypted database and read-only\nanalyzer checks on a Windows CI runner. This does not validate a rekordbox restore.")
start.write_text(text,encoding="utf-8")
output=Path("releases")
output.mkdir(exist_ok=True)
archive=output/("Library-Workbench-"+manifest["version"]+"-windows-x64-preview.zip")
with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as target:
    for file in sorted(folder.rglob("*")):
        if file.is_file():target.write(file,file.relative_to(folder.parent))
archive.with_suffix(".sha256").write_text(sha256(archive.read_bytes()).hexdigest()+"  "+archive.name+"\n",encoding="utf-8")
print(archive)
