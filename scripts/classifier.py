"""Omni's daily Atma maintenance. Owns settings, scheduling and run summaries."""
import fcntl
import json
import os
import plistlib
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from local import ROOT, STATE, runtime_env

CONFIG = STATE / "classifier.json"
REPORT = STATE / "classification-report.json"
DEFAULT = {"mode":"offline","endpoint":"https://openrouter.ai/api/v1","model":"","limit":10,"daily":True}
LABEL = "dev.omni.atma-classifier"


def write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False,mode="w") as f:
        json.dump(data,f)
    os.replace(f.name,path)


def config():
    return DEFAULT | (json.loads(CONFIG.read_text()) if CONFIG.exists() else {})


def public():
    cfg = config()
    return {**{k:cfg[k] for k in DEFAULT},"hasKey":bool(cfg.get("key")),
            "report":json.loads(REPORT.read_text()) if REPORT.exists() else {}}


def configure(data):
    from omnikit.providers import endpoint_url
    cfg = {k:data[k] for k in DEFAULT}
    cfg["endpoint"] = cfg["endpoint"].strip().rstrip("/")
    cfg["model"] = cfg["model"].strip()
    if cfg["mode"] not in ("offline","compatible") or type(cfg["limit"]) is not int or not 1<=cfg["limit"]<=100:
        raise ValueError("Select a supported mode and a limit between 1 and 100.")
    endpoint_url(cfg["endpoint"])
    if cfg["mode"]=="compatible" and not cfg["model"]:
        raise ValueError("Enter the model ID.")
    old = config()
    if data.get("key"):
        cfg["key"] = data["key"].strip()
    elif old["endpoint"]==cfg["endpoint"] and not data.get("forgetKey"):
        cfg["key"] = old.get("key","")
    write(CONFIG,cfg)


def install_schedule():
    path = Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
    path.parent.mkdir(parents=True,exist_ok=True)
    spec = {"Label":LABEL,"ProgramArguments":[str(STATE/"api/bin/python"),str(Path(__file__).resolve()),"scheduled"],
            "StartCalendarInterval":{"Hour":3,"Minute":0},"RunAtLoad":True}
    path.write_bytes(plistlib.dumps(spec))
    domain = f"gui/{os.getuid()}"
    if subprocess.run(["launchctl","print",domain],capture_output=True).returncode==0:
        if subprocess.run(["launchctl","print",domain+"/"+LABEL],capture_output=True).returncode==0:
            subprocess.run(["launchctl","bootout",domain+"/"+LABEL],check=True)
        subprocess.run(["launchctl","bootstrap",domain,str(path)],check=True)


def run(manual):
    cfg=config()
    if not manual and not cfg["daily"]:
        return
    os.environ.update(runtime_env())
    # Postgres stopped by the user stays stopped.
    with (STATE/"classifier.lock").open("a") as lock,(STATE/"jobs.lock").open("a") as jobs:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(jobs,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        today=datetime.now().date().isoformat()
        last = public()["report"]
        if not manual and last.get("day")==today and last.get("state")=="finished":
            return
        if not (STATE/"postgres/postmaster.pid").exists():
            return
        sys.path.insert(0,str(ROOT/"atma/api"))
        from utils.daily import run as classify
        from omnikit.providers import complete
        os.environ.update(OMNI_AI_PROVIDER=cfg["mode"],OMNI_AI_BASE_URL=cfg["endpoint"],
                          OMNI_AI_MODEL=cfg["model"],OMNI_AI_KEY=cfg.get("key",""))
        status=dict(day=today,state="running")
        write(REPORT,status)
        try:
            stats=classify(complete if cfg["mode"]=="compatible" else None,cfg["model"],cfg["limit"])
            write(REPORT,dict(status,**stats,state="finished"))
        except Exception as exc:
            write(REPORT,dict(status,state="failed",error=type(exc).__name__))
            raise


if __name__=="__main__":
    os.umask(0o077)
    run(sys.argv[1]=="manual")
