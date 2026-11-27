#!/usr/bin/env bash
# test_omni_merge_lane.sh — proves the lane's TEST GATE runs against the BRANCH,
# not against whatever the live tree holds, now that omni-branch checks the branch
# out in a linked worktree (where `git checkout <branch>` in the live tree refuses).
#
# The gate command deliberately depends on the checkout under test:
#   * it imports `probemod` from {root}/src  -> only works if the lane puts the
#     checkout's src on PYTHONPATH (an editable venv would otherwise import main)
#   * it requires test_env `PROBE_ROOT` == cwd -> only works if {root} expanded
#   * it requires probemod.V == BRANCH_ONLY    -> only works on branch content
# So "gate passed" is proof the gate ran on the branch, in the branch's tree.
#
# Run:  bash omni-sdlc/tests/test_omni_merge_lane.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BRANCH_TOOL="$HERE/../bin/omni-branch"
LANE="$HERE/../bin/omni-merge-lane"
# The lane imports PyYAML: run it with Omni's interpreter, as bin/omni-sdlc does.
PY="${OMNI_PYTHON:-$HERE/../../core/.venv/bin/python}"; [ -x "$PY" ] || PY=python3
FAIL=0
pass() { echo "  ok   - $*"; }
fail() { echo "  FAIL - $*" >&2; FAIL=$((FAIL+1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/omni-lane-test.XXXXXX")"
WORK="$(cd "$WORK" && pwd -P)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

export GIT_CONFIG_NOSYSTEM=1
export HOME="$WORK/home"
mkdir -p "$HOME"
git config --global user.email dev@example.com
git config --global user.name  "omni-sdlc test"
git config --global init.defaultBranch main

git init -q --bare "$WORK/origin.git"
git clone -q "$WORK/origin.git" "$WORK/repo" 2>/dev/null
LIVE="$WORK/repo"
mkdir -p "$LIVE/src"
echo 'V = "MAIN"' > "$LIVE/src/probemod.py"
git -C "$LIVE" add -A
git -C "$LIVE" commit -qm base
git -C "$LIVE" push -q origin main

GATE_CMD='python3 -c "import os,probemod,sys; sys.exit(0 if probemod.V==\"BRANCH_ONLY\" and os.environ.get(\"PROBE_ROOT\")==os.getcwd() else 1)"'
cat > "$WORK/repos.yaml" <<YAML
repos:
  t:
    path: "$LIVE"
    remote: "x"
    base: "main"
    test: '$GATE_CMD'
    test_env:
      PROBE_ROOT: "{root}"
    note: "test fixture"
policy:
  test_gate: true
  require_push: true
  reconcile_on_conflict: true
  tag_on_merge: true
YAML
export OMNI_SDLC_REPOS="$WORK/repos.yaml"

echo "== 1. gate passes on a branch whose content is only in a worktree"
bash "$BRANCH_TOOL" "$LIVE" dev lane-ok >/dev/null 2>&1
WT="$LIVE/.worktrees/dev-lane-ok"
echo 'V = "BRANCH_ONLY"' > "$WT/src/probemod.py"
git -C "$WT" commit -qam "flip module on branch"
git -C "$WT" push -q -u origin agent/dev/lane-ok 2>/dev/null
OUT="$("$PY" "$LANE" t agent/dev/lane-ok 2>&1)"; RC=$?
echo "$OUT" | sed 's/^/     | /'
check "lane exit 0"                              "[ $RC -eq 0 ]"
check "gate reported passed"                     "echo \"\$OUT\" | grep -q 'test gate passed'"
check "gate ran in a detached worktree"          "echo \"\$OUT\" | grep -q 'gating in a detached worktree'"
check "merge landed on main"                     "[ \"\$(git -C '$LIVE' rev-parse HEAD)\" != \"\$(git -C '$WORK/origin.git' rev-parse refs/heads/main)\" ]"
check "main carries the branch change"           "grep -q BRANCH_ONLY '$LIVE/src/probemod.py'"
check "live tree back on main"                   "[ \"\$(git -C '$LIVE' branch --show-current)\" = main ]"
check "no lane-gate worktree left behind"        "! git -C '$LIVE' worktree list --porcelain | grep -q 'lane-gate-'"
check "branch worktree untouched"                "[ \"\$(git -C '$WT' branch --show-current)\" = agent/dev/lane-ok ]"

echo "== 2. gate FAILS when the branch does not really contain the change"
# reset the module on main, otherwise main itself would satisfy the gate after case 1
echo 'V = "MAIN"' > "$LIVE/src/probemod.py"
git -C "$LIVE" commit -qam "reset module on main"
git -C "$LIVE" push -q origin main
bash "$BRANCH_TOOL" "$LIVE" dev lane-bad >/dev/null 2>&1
WT2="$LIVE/.worktrees/dev-lane-bad"
echo "unrelated" > "$WT2/other.txt"
git -C "$WT2" add other.txt && git -C "$WT2" commit -qm "no module change"
git -C "$WT2" push -q -u origin agent/dev/lane-bad 2>/dev/null
BEFORE="$(git -C "$LIVE" rev-parse HEAD)"
OUT2="$("$PY" "$LANE" t agent/dev/lane-bad 2>&1)"; RC2=$?
check "lane exit 1 (gate failed)"                "[ $RC2 -eq 1 ]"
check "reports TEST GATE FAILED"                 "echo \"\$OUT2\" | grep -q 'TEST GATE FAILED'"
check "main untouched by the failed gate"        "[ \"\$(git -C '$LIVE' rev-parse HEAD)\" = '$BEFORE' ]"
check "no lane-gate worktree left behind"        "! git -C '$LIVE' worktree list --porcelain | grep -q 'lane-gate-'"

echo "== 3. live tree NOT on the base: the lane refuses and never moves the live HEAD"
git -C "$LIVE" checkout -q -b agent/dev/no-wt
echo 'V = "BRANCH_ONLY"' > "$LIVE/src/probemod.py"
git -C "$LIVE" commit -qam "branch checked out in the live tree"
git -C "$LIVE" push -q -u origin agent/dev/no-wt 2>/dev/null
MAIN_BEFORE="$(git -C "$LIVE" rev-parse main)"
OUT3="$("$PY" "$LANE" t agent/dev/no-wt 2>&1)"; RC3=$?
echo "$OUT3" | sed 's/^/     | /'
check "lane exit 2 (refused)"                    "[ $RC3 -eq 2 ]"
check "gate still ran in a detached worktree"    "echo \"\$OUT3\" | grep -q 'gating in a detached worktree'"
check "refusal names the base"                   "echo \"\$OUT3\" | grep -q \"not the base 'main'\""
check "live tree still on its own branch"        "[ \"\$(git -C '$LIVE' branch --show-current)\" = agent/dev/no-wt ]"
check "main not merged into"                     "[ \"\$(git -C '$LIVE' rev-parse main)\" = '$MAIN_BEFORE' ]"
check "no lane-gate worktree left behind"        "! git -C '$LIVE' worktree list --porcelain | grep -q 'lane-gate-'"
git -C "$LIVE" checkout -q main

echo "== 4. a repo whose base is NOT main merges into that base"
git -C "$LIVE" checkout -q -b instance/me main
git -C "$LIVE" push -q -u origin instance/me 2>/dev/null
# perl -pi, not sed -i: BSD sed (macOS) and GNU sed (Linux, CI) disagree on -i's argument.
perl -pi -e 's/base: "main"/base: "instance\/me"/' "$WORK/repos.yaml"
MAIN_BEFORE="$(git -C "$LIVE" rev-parse main)"
bash "$BRANCH_TOOL" "$LIVE" dev inst-ok >/dev/null 2>&1
WT4="$LIVE/.worktrees/dev-inst-ok"
check "omni-branch drew the branch off origin/instance/me" \
      "[ \"\$(git -C '$WT4' rev-parse HEAD)\" = \"\$(git -C '$LIVE' rev-parse origin/instance/me)\" ]"
echo 'V = "BRANCH_ONLY"' > "$WT4/src/probemod.py"
git -C "$WT4" commit -qam "flip module on an instance branch"
git -C "$WT4" push -q -u origin agent/dev/inst-ok 2>/dev/null
OUT4="$("$PY" "$LANE" t agent/dev/inst-ok 2>&1)"; RC4=$?
echo "$OUT4" | sed 's/^/     | /'
check "lane exit 0"                              "[ $RC4 -eq 0 ]"
check "merged into instance/me"                  "echo \"\$OUT4\" | grep -q 'into instance/me'"
check "instance/me carries the change"           "git -C '$LIVE' show instance/me:src/probemod.py | grep -q BRANCH_ONLY"
check "main untouched"                           "[ \"\$(git -C '$LIVE' rev-parse main)\" = '$MAIN_BEFORE' ]"
check "live tree still on instance/me"           "[ \"\$(git -C '$LIVE' branch --show-current)\" = instance/me ]"

echo "== 5. base is instance/me but the live tree is on main: refuse, do not switch"
git -C "$LIVE" checkout -q main
bash "$BRANCH_TOOL" "$LIVE" dev inst-two >/dev/null 2>&1
WT5="$LIVE/.worktrees/dev-inst-two"
echo 'V = "BRANCH_ONLY"' > "$WT5/src/probemod.py"     # passes the gate: refusal must come from the base check
git -C "$WT5" commit -qam "flip module"
git -C "$WT5" push -q -u origin agent/dev/inst-two 2>/dev/null
INST_BEFORE="$(git -C "$LIVE" rev-parse instance/me)"
OUT5="$("$PY" "$LANE" t agent/dev/inst-two 2>&1)"; RC5=$?
check "lane exit 2 (refused)"                    "[ $RC5 -eq 2 ]"
check "refusal names the base"                   "echo \"\$OUT5\" | grep -q \"not the base 'instance/me'\""
check "live tree left on main"                   "[ \"\$(git -C '$LIVE' branch --show-current)\" = main ]"
check "instance/me not merged into"              "[ \"\$(git -C '$LIVE' rev-parse instance/me)\" = '$INST_BEFORE' ]"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
fi
echo "$FAIL TEST(S) FAILED" >&2
exit 1
