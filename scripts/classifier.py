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
DEFAULT = {"mode":"offline","endpoint":"https://openrouter.ai/api/v1","model":"","limit":10,"daily":True,
           "currentState":"","idealState":"","shareContext":False}
LABEL = "dev.omni.atma-classifier"


def write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False,mode="w") as f:
        json.dump(data,f)
    os.replace(f.name,path)


def config():
    return DEFAULT | (json.loads(CONFIG.read_text()) if CONFIG.exists() else {})


def public():
    cfg = config()
    from nlp_assets import ASSETS
    ready = all((STATE/"nlp"/name).is_file() for name in ASSETS)
    return {"nlpReady":ready, **{k:cfg[k] for k in DEFAULT},"hasKey":bool(cfg.get("key")),
            "report":json.loads(REPORT.read_text()) if REPORT.exists() else {}}


def configure(data):
    from omnikit.providers import endpoint_url
    old = config()
    cfg = {k:data.get(k, old[k]) for k in DEFAULT}
    for key in ("currentState", "idealState"):
        if not isinstance(cfg[key], str) or len(cfg[key]) > 1000:
            raise ValueError("Use up to 1,000 characters for each growth context field.")
        cfg[key] = cfg[key].strip()
    if type(cfg["shareContext"]) is not bool:
        raise ValueError("Invalid sharing preference")
    cfg["endpoint"] = cfg["endpoint"].strip().rstrip("/")
    cfg["model"] = cfg["model"].strip()
    if cfg["mode"] not in ("offline","static","compatible","api") or type(cfg["limit"]) is not int or not 1<=cfg["limit"]<=100:
        raise ValueError("Select a supported mode and a limit between 1 and 100.")
    endpoint_url(cfg["endpoint"])
    if cfg["mode"] in ("compatible", "api") and not cfg["model"]:
        raise ValueError("Enter the model ID.")
    if cfg["endpoint"] != old["endpoint"]:
        cfg["shareContext"] = False
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
        os.environ.update(OMNI_AI_PROVIDER="compatible" if cfg["mode"] in ("compatible", "api") else "offline",OMNI_AI_BASE_URL=cfg["endpoint"],
                          OMNI_AI_MODEL=cfg["model"],OMNI_AI_KEY=cfg.get("key",""))
        status=dict(day=today,state="running")
        write(REPORT,status)
        try:
            semantic = None
            if cfg["mode"] in ("offline", "compatible"):
                from utils.semantic import SemanticClassifier
                semantic = SemanticClassifier(STATE/"nlp", cfg["currentState"], cfg["idealState"])
            profile = {key: cfg[key] for key in ("currentState","idealState") if cfg[key]}
            paid = cfg["mode"] in ("compatible","api")
            stats = classify(complete if paid else None, cfg["model"], cfg["limit"], semantic=semantic,
                             mode=cfg["mode"], profile=profile, share_context=cfg["shareContext"])
            write(REPORT,dict(status,**stats,state="finished"))
        except Exception as exc:
            write(REPORT,dict(status,state="failed",error=type(exc).__name__))
            raise


if __name__=="__main__":
    os.umask(0o077)
    run(sys.argv[1]=="manual")
