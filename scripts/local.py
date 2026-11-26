"""Install and operate the single-user Omni OS local alpha."""
import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".omni-local"
PG = STATE / "postgres"
SOCKET = STATE / "socket"
REGISTRY = STATE / "registry.json"


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def preflight():
    uv = shutil.which("uv")
    configs = [shutil.which("pg_config")]
    for prefix in ("/opt/homebrew", "/usr/local"):
        configs.extend(str(p) for p in sorted(Path(prefix, "opt").glob("postgresql@*/bin/pg_config"), reverse=True))
    for config in filter(None, configs):
        bindir = Path(subprocess.check_output([config, "--bindir"], text=True).strip())
        if all((bindir / tool).is_file() for tool in ("pg_ctl", "initdb", "psql", "createdb", "postgres")):
            version = subprocess.check_output([bindir / "postgres", "--version"], text=True).split()[-1]
            if int(version.split(".")[0]) >= 16:
                break
    else:
        raise SystemExit("Install PostgreSQL 16+ including server tools. Put pg_config on PATH.")
    if not uv:
        raise SystemExit("Install uv and Python 3.12, then rerun ./install.sh.")
    if os.getuid() == 0:
        raise SystemExit("Run as the local user who will own the cluster.")
    if len(os.fsencode(SOCKET / ".s.PGSQL.5432")) >= 104:
        raise SystemExit("Use a shorter checkout path for the PostgreSQL socket.")
    print("PostgreSQL", version, "and uv found.", flush=True)
    return uv, bindir


def python(component):
    return STATE / component / "bin/python"


def dependencies(uv):
    packages = {"api": ["-r", ROOT / "atma/api/requirements.txt", "-e", ROOT / "lib"],
                "app": ["-r", ROOT / "atma/app/requirements.txt"],
                "base": ["-e", ROOT / "core", "numpy", "scikit-learn"]}
    for component, deps in packages.items():
        if not python(component).exists():
            run(uv, "venv", "--python", "3.12", STATE / component)
        run(uv, "pip", "install", "--python", python(component), *deps)


def cluster(bindir, env):
    SOCKET.mkdir(exist_ok=True, mode=0o700)
    if not (PG / "PG_VERSION").exists():
        run(bindir / "initdb", "-D", PG, "-A", "trust", "--encoding=UTF8", "--locale=C")
        with (PG / "postgresql.conf").open("a") as conf:
            socket_dir = str(SOCKET).replace("'", "''")
            conf.write("\nlisten_addresses = ''\nunix_socket_directories = '" + socket_dir + "'\nport = 5432\n")
    if subprocess.run([bindir / "pg_ctl", "-D", PG, "status"], stdout=subprocess.DEVNULL).returncode:
        run(bindir / "pg_ctl", "-D", PG, "-l", STATE / "postgres.log", "-w", "start")
    for db in ("atma", "omni"):
        exists = run(bindir / "psql", "-XAt", "-d", "postgres", "-c",
                     "select 1 from pg_database where datname='" + db + "'", env=env, capture_output=True)
        if not exists.stdout.strip():
            run(bindir / "createdb", db, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install","check","start","stop-db","refresh","add","complete","status"], default="install", nargs="?")
    parser.add_argument("value", nargs="?", help="Task title or task ID")
    args = parser.parse_args()
    uv, bindir = preflight()
    if args.action == "check":
        return
    if args.action == "stop-db":
        run(bindir / "pg_ctl", "-D", PG, "-w", "stop")
        return
    os.umask(0o077)
    STATE.mkdir(exist_ok=True)
    if args.action == "install":
        dependencies(uv)
    if not python("api").exists():
        raise SystemExit("Run ./install.sh first.")
    token = STATE / "owner-token"
    if not token.exists():
        with token.open("x") as stream:
            stream.write(secrets.token_urlsafe(32))
    api_port = int(os.getenv("OMNI_LOCAL_API_PORT", "18702"))
    app_port = int(os.getenv("OMNI_LOCAL_APP_PORT", "18701"))
    env = {k:v for k,v in os.environ.items() if not k.startswith(("PG", "ATMA_", "OMNI_", "PYTHON")) and not k.endswith(("_API_KEY","_TOKEN"))}
    for key in ("OMNI_AI_PROVIDER","OMNI_AI_MODEL","OMNI_LOCAL_BASE_URL"):
        if key in os.environ:
            env[key] = os.environ[key]
    if env.get("OMNI_AI_PROVIDER") == "openrouter" and "OPENROUTER_API_KEY" in os.environ:
        env["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    env.update(PGHOST=str(SOCKET), PGPORT="5432", ATMA_AGENT_TOKEN=token.read_text(),
               ATMA_DATABASE_URL="dbname=atma", OMNI_DATABASE_URL="dbname=omni", ATMA_GOVERNANCE="1",
               PYTHON_DOTENV_DISABLED="1")
    base = "http://127.0.0.1:" + str(api_port)
    if args.action in ("add","complete","status"):
        if args.action != "status" and not args.value:
            parser.error("Supply a title or task ID")
        url = base + "/api/agent/tasks"
        body = None
        if args.action == "add":
            body = {"title": args.value}
        elif args.action == "complete":
            url += "/" + str(int(args.value)) + "/complete"
            body = {}
        req = Request(url, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type":"application/json","Authorization":"Bearer "+token.read_text()})
        with urlopen(req, timeout=20) as res:
            print(res.read().decode())
        return
    if args.action == "refresh":
        run(STATE/"base/bin/omni", "--registry", REGISTRY, "run", "mindmap", env=env)
        return
    if api_port == app_port:
        parser.error("API and dashboard need distinct ports")
    for port in (api_port, app_port):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1",port))
    cluster(bindir, env)
    run(python("api"), ROOT/"atma/api/scripts/migrate.py", env=env)
    run(bindir/"psql","-X","-v","ON_ERROR_STOP=1","-d","atma","-c",
        "INSERT INTO users(name) SELECT 'Me' WHERE NOT EXISTS (SELECT 1 FROM users WHERE id=1)",env=env)
    REGISTRY.write_text(json.dumps({"version":1,"harnesses":{"script":{"kind":"script"}},
        "domains":{"atma":{"workdir":str(ROOT)}},"jobs":{"mindmap":{"domain":"atma","harness":"script",
        "command":[str(python("base")),str(ROOT/"mindmap.py")]}}}))
    cli = [STATE/"base/bin/omni","--registry",REGISTRY]
    for args_ in (["migrate"],["check"],["run","mindmap"]):
        run(*cli,*args_,env=env)
    procs = []
    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        for name, module, port in (("api","main:app",api_port),("app","server:app",app_port)):
            procs.append(subprocess.Popen([python(name),"-m","uvicorn",module,"--host","127.0.0.1","--port",str(port)],
                         cwd=ROOT/"atma"/name, env=env))
        print(f"Atma dashboard http://127.0.0.1:{app_port} | API {base}/docs | Ctrl-C to stop both", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(0.3)
        raise SystemExit("A service exited. Check its startup output.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            p.wait()


if __name__ == "__main__":
    main()
