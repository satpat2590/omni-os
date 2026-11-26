#!/usr/bin/env bash
# test_omni_branch.sh — proves omni-branch creates a LINKED WORKTREE and never
# moves the live tree's HEAD. Self-contained: builds throwaway repos + bare origin
# under a temp dir; no network, touches no real repo.
#
# Run:  bash omni-sdlc/tests/test_omni_branch.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BRANCH_TOOL="$HERE/../bin/omni-branch"
FAIL=0
pass() { echo "  ok   - $*"; }
fail() { echo "  FAIL - $*" >&2; FAIL=$((FAIL+1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/omni-branch-test.XXXXXX")"
WORK="$(cd "$WORK" && pwd -P)"   # resolve /var -> /private/var on macOS
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

export GIT_CONFIG_NOSYSTEM=1
export HOME="$WORK/home"          # keep any global git config out of the picture
mkdir -p "$HOME"
git config --global user.email dev@example.com
git config --global user.name  "omni-sdlc test"
git config --global init.defaultBranch main

# ---- fixture: bare origin + one clone (the "live" repo) -----------------------
git init -q --bare "$WORK/origin.git"
git clone -q "$WORK/origin.git" "$WORK/repo" 2>/dev/null
LIVE="$WORK/repo"
echo base > "$LIVE/file.txt"
git -C "$LIVE" add file.txt
git -C "$LIVE" commit -qm "base commit"
git -C "$LIVE" push -q origin main
git -C "$LIVE" fetch -q origin main
BASE="$(git -C "$LIVE" rev-parse origin/main)"

echo "== 1. branch on a DIRTY live tree stays a worktree op"
echo "unrelated work" >> "$LIVE/file.txt"          # live tree dirty: used to abort
OUT="$(bash "$BRANCH_TOOL" "$LIVE" dev probe-xyz 2>&1)"; RC=$?
echo "$OUT" | sed 's/^/     | /'
check "exit 0 despite dirty live tree"            "[ $RC -eq 0 ]"
check "live tree still on main"                   "[ \"\$(git -C '$LIVE' branch --show-current)\" = main ]"
check "live tree dirt untouched"                  "grep -q 'unrelated work' '$LIVE/file.txt'"
WT="$WORK/repo/.worktrees/dev-probe-xyz"
check "worktree path exists: $WT"                 "[ -d '$WT/.git' -o -f '$WT/.git' ]"
check "prints WORKTREE: path"                     "echo \"\$OUT\" | grep -qx 'WORKTREE: $WT'"
check "branch is agent/dev/probe-xyz"           "[ \"\$(git -C '$WT' branch --show-current)\" = agent/dev/probe-xyz ]"
check "branch based on origin/main"               "[ \"\$(git -C '$WT' rev-parse HEAD)\" = '$BASE' ]"
check "git worktree list knows the path"          "git -C '$LIVE' worktree list --porcelain | grep -qx 'worktree $WT'"
check ".worktrees/ excluded from live status"     "! git -C '$LIVE' status --porcelain | grep -q 'worktrees'"
check "live tree has no new commits"              "[ \"\$(git -C '$LIVE' rev-parse HEAD)\" = '$BASE' ]"

echo "== 2. committing in the worktree leaves the live tree alone"
echo change > "$WT/work.txt"
git -C "$WT" add work.txt && git -C "$WT" commit -qm "work in worktree"
check "worktree commit landed"                    "[ \"\$(git -C '$WT' rev-parse HEAD)\" != '$BASE' ]"
check "live HEAD unchanged by the commit"         "[ \"\$(git -C '$LIVE' rev-parse HEAD)\" = '$BASE' ]"

echo "== 3. re-running is idempotent (reuses the worktree)"
OUT2="$(bash "$BRANCH_TOOL" "$LIVE" dev probe-xyz 2>&1)"; RC2=$?
check "exit 0 on re-entry"                        "[ $RC2 -eq 0 ]"
check "reports EXISTS"                            "echo \"\$OUT2\" | grep -q '^EXISTS'"
check "still exactly one worktree for the branch" "[ \"\$(git -C '$LIVE' worktree list --porcelain | grep -c 'refs/heads/agent/dev/probe-xyz')\" -eq 1 ]"
check "commits preserved across re-entry"         "[ \"\$(git -C '$WT' rev-parse HEAD)\" != '$BASE' ]"

echo "== 4. --push publishes the branch and sets upstream"
OUT3="$(bash "$BRANCH_TOOL" "$LIVE" dev probe-xyz --push 2>&1)"; RC3=$?
check "exit 0 with --push"                        "[ $RC3 -eq 0 ]"
check "origin has the branch"                     "[ \"\$(git -C '$WORK/origin.git' rev-parse refs/heads/agent/dev/probe-xyz)\" = \"\$(git -C '$WT' rev-parse HEAD)\" ]"
check "upstream configured in the worktree"       "[ \"\$(git -C '$WT' rev-parse --abbrev-ref --symbolic-full-name @{u})\" = origin/agent/dev/probe-xyz ]"
check "base branch untouched on origin"           "[ \"\$(git -C '$WORK/origin.git' rev-parse refs/heads/main)\" = '$BASE' ]"

echo "== 5. slug/agent sanitisation"
bash "$BRANCH_TOOL" "$LIVE" Dev "Probe XYZ!!" >/dev/null 2>&1; RC4=$?
check "sanitised slug accepted"                   "[ $RC4 -eq 0 ]"
check "branch agent/dev/probe-xyz exists"       "git -C '$LIVE' rev-parse --verify -q refs/heads/agent/dev/probe-xyz >/dev/null"

echo "== 6. refuses when the branch is checked out in the live tree"
git -C "$LIVE" checkout -q file.txt 2>/dev/null || true
git -C "$LIVE" stash -q -u 2>/dev/null || true      # clean, so we can move HEAD
git -C "$LIVE" checkout -q -B agent/dev/live-demo "$BASE"
OUT5="$(bash "$BRANCH_TOOL" "$LIVE" dev live-demo 2>&1)"; RC5=$?
check "refuses with exit 2"                       "[ $RC5 -eq 2 ]"
check "says the live tree holds the branch"       "echo \"\$OUT5\" | grep -q 'checked out in the live working tree'"

echo "== 7. collision on an unregistered path is a clear error"
git -C "$LIVE" checkout -q main
mkdir -p "$WORK/repo/.worktrees/dev-collide"
OUT6="$(bash "$BRANCH_TOOL" "$LIVE" dev collide 2>&1)"; RC6=$?
check "refuses with exit 2"                       "[ $RC6 -eq 2 ]"
check "names the path and the remedy"             "echo \"\$OUT6\" | grep -q 'worktree-reap'"

echo "== 8. the default base comes from repos.yaml; --base still overrides it"
git -C "$LIVE" branch -q instance/me "$BASE"
echo inst > "$WORK/inst.txt"
INST_WT="$WORK/inst-wt"
git -C "$LIVE" worktree add -q "$INST_WT" instance/me
cp "$WORK/inst.txt" "$INST_WT/" && git -C "$INST_WT" add inst.txt && git -C "$INST_WT" commit -qm inst
git -C "$INST_WT" push -q origin instance/me
INST_HEAD="$(git -C "$LIVE" rev-parse instance/me)"
cat > "$WORK/repos.yaml" <<YAML
repos:
  t:
    path: "$LIVE"
    base: "instance/me"
YAML
OUT8="$(OMNI_SDLC_REPOS="$WORK/repos.yaml" bash "$BRANCH_TOOL" "$LIVE" dev from-yaml 2>&1)"; RC8=$?
echo "$OUT8" | sed 's/^/     | /'
check "exit 0"                                    "[ $RC8 -eq 0 ]"
check "branch based on origin/instance/me"        "[ \"\$(git -C '$LIVE/.worktrees/dev-from-yaml' rev-parse HEAD)\" = '$INST_HEAD' ]"
check "reports the base it used"                  "echo \"\$OUT8\" | grep -q 'from origin/instance/me'"
OMNI_SDLC_REPOS="$WORK/repos.yaml" bash "$BRANCH_TOOL" "$LIVE" dev override --base origin/main >/dev/null 2>&1
check "--base origin/main overrides repos.yaml"   "[ \"\$(git -C '$LIVE/.worktrees/dev-override' rev-parse HEAD)\" = '$BASE' ]"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
fi
echo "$FAIL TEST(S) FAILED" >&2
exit 1
