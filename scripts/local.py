"""Install and operate the single-user Omni OS local alpha."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

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
            version = subprocess.check_output([bindir / "postgres", "--version"], text=True).split()[2]
            major = int(version.split(".")[0])
            installed = PG / "PG_VERSION"
            if major >= 16 and (not installed.exists() or str(major) == installed.read_text().strip()):
                break
    else:
        raise SystemExit("Install PostgreSQL 16+ including server tools. Put pg_config on PATH.")
    if not uv:
        raise SystemExit("Install uv and Python 3.12, then rerun ./install.sh.")
    if os.getuid() == 0:
        raise SystemExit("Run as the local user who will own the cluster.")
    if len(os.fsencode(SOCKET / ".s.PGSQL.5432")) >= 104:
        raise SystemExit("Use a shorter checkout path for the PostgreSQL socket.")

    return uv, bindir


def python(component):
    return STATE / component / "bin/python"


def dependencies(uv):
    packages = {"api": ["-r", ROOT / "atma/api/requirements.txt", "-e", ROOT / "lib"],
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
        run(bindir / "pg_ctl", "-D", PG, "-l", STATE / "postgres.log", "-w", "start", env=env)
    for db in ("atma", "omni"):
        exists = run(bindir / "psql", "-XAt", "-d", "postgres", "-c",
                     "select 1 from pg_database where datname='" + db + "'", env=env, capture_output=True)
        if not exists.stdout.strip():
            run(bindir / "createdb", db, env=env)


def runtime_env():
    env = {k:v for k,v in os.environ.items() if not k.startswith(("PG","ATMA_","PYTHON"))}
    env.update(LC_ALL="C", PGHOST=str(SOCKET), PGPORT="5432", ATMA_DATABASE_URL="dbname=atma",
               OMNI_DATABASE_URL="dbname=omni", ATMA_GOVERNANCE="1", PYTHON_DOTENV_DISABLED="1")
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install","check","test"], default="install", nargs="?")
    args = parser.parse_args()
    uv, bindir = preflight()
    if args.action == "check":
        run(uv,"python","find","3.12")
        run("xcrun","--find","swiftc")
        return
    os.umask(0o077)
    STATE.mkdir(exist_ok=True)
    env = runtime_env()
    if args.action == "test":
        cluster(bindir, env)
        env["ATMA_TEST_SERVER_URL"] = "dbname=postgres"
        # Test fixtures inherit this install's private socket and create disposable databases.
        for component, directory in (("api","atma/api"),):
            cwd = ROOT / directory
            run(uv,"pip","install","--python",python(component),"-r","requirements-dev.txt",cwd=cwd)
            run(python(component),"-m","pytest","-q","tests",cwd=cwd,env=env)
        run(uv,"pip","install","--python",python("base"),"pytest","-e",ROOT/"lib")
        run(python("base"),"-m","pytest","-q","core/tests","classify/tests","lib/tests","tests",cwd=ROOT,env=env)
        for suite in ("test_omni_branch.sh","test_omni_merge_lane.sh"):
            run("bash",ROOT/"omni-sdlc/tests"/suite,cwd=ROOT,
                env={**env,"OMNI_PYTHON":str(python("base"))})
        return
    dependencies(uv)
    cluster(bindir, env)
    run(python("api"), ROOT/"atma/api/scripts/migrate.py", env=env)
    run(bindir/"psql","-X","-v","ON_ERROR_STOP=1","-d","atma","-c",
        "INSERT INTO users(name) SELECT 'Me' WHERE NOT EXISTS (SELECT 1 FROM users WHERE id=1)",env=env)
    run(STATE/"base/bin/omni","migrate",env=env)
    from bundles import install_apps
    install_apps(ROOT, STATE)


if __name__ == "__main__":
    main()
