"""glassbox_sweep.py — nightly ANONYMOUS public-record sweep (watchdog cron job).

Repurposed per the 2026-11-17 glass-box pivot: the old plan was an anonymous
LEAK SCAN ("what of ours is visible?"). There is nothing to hide anymore.
This sweep asks the inverse: "is the glass box still glass, and does the
visible record conform?"

Checks per target repo (api.github.com, ZERO credentials):
  1. WALL    — repo must remain anonymously readable (404/451/private = glass-box
               break: the retired private-flip haunting). default_branch must match
               targets/config state.
  2. TRAILERS— every new default-branch commit (committer date >= cutoff, post-cursor)
               conforms to schema.py (git interpret-trailers semantics mirrored).
  3. RESIDUE — tracked files at HEAD (recursive tree API) vs the residue blocklist.
               Paths + matched pattern only; file contents are NEVER fetched/printed.

Output discipline (no_agent cron watchdog): stdout EMPTY when clean -> silent night.
New faults print a terse report -> delivered to the swarm thread.
Baseline faults discovered on the first (full-history) run are recorded in the state
file and only surface via --digest, so one legacy miss doesn't cry wolf nightly.
Exit code is always 0; delivery is driven by stdout, not status.

  python glassbox_sweep.py            # nightly mode (incremental + wall + residue)
  python glassbox_sweep.py --digest   # full human report, no state mutation
  python glassbox_sweep.py --init     # first full run from cutoff, seed baseline
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema  # noqa: E402

API = "https://api.github.com"
UA = "glassbox-sweep/1.0 (anonymous conformance watchdog)"
MAX_PAGES = 4          # 100 commits/page cap per repo-run
HERE = os.path.dirname(os.path.abspath(__file__))


def load_targets():
    with open(os.path.join(HERE, "targets.json"), encoding="utf-8") as f:
        return json.load(f)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if s.get("schema_version") != schema.SCHEMA_VERSION:
            return {"schema_version": schema.SCHEMA_VERSION, "repos": {}}
        return s
    except Exception:
        return {"schema_version": schema.SCHEMA_VERSION, "repos": {}}


def api_get(url):
    """Anonymous GET. Returns (status, json|None). 2nd chance on 5xx once."""
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt == 0:
                time.sleep(3)
                continue
            return e.code, None
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
                continue
            return f"ERR {type(e).__name__}", None


def iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sweep_repo(owner, name, cfg, cutoff, cursor_iso):
    """Returns dict: faults[], violations[], residue[], exempt[], checked, wall, head."""
    faults, violations, exempt, checked = [], [], [], 0
    st, repo = api_get(f"{API}/repos/{owner}/{name}")
    if st != 200 or not repo:
        faults.append(f"WALL {owner}/{name}: anonymous read broken (HTTP {st}) — "
                      "public record must stay anonymously readable")
        return {"faults": faults, "violations": [], "residue": [], "exempt": [],
                "checked": 0, "head": None, "default_branch": None}
    db = repo.get("default_branch")
    if repo.get("private"):
        faults.append(f"WALL {owner}/{name}: API reports private=true")
    since = cursor_iso or cutoff
    commits, head, truncated = [], None, False
    pages = range(1, MAX_PAGES + 1) if since else []   # since=None => trailers off
    for page in pages:
        url = (f"{API}/repos/{owner}/{name}/commits?sha={db}&since={since}"
               f"&per_page=100&page={page}")
        st2, data = api_get(url)
        if st2 != 200:
            faults.append(f"API {owner}/{name} commits p{page}: HTTP {st2}")
            data = None
        if not data:
            break
        commits.extend(data)
        if len(data) == 100 and page == MAX_PAGES:
            truncated = True
        if len(data) < 100:
            break
    if commits:
        head = commits[0]["sha"]

    seen_shas = set()
    for c in commits:
        sha = c["sha"]
        if sha in seen_shas:
            continue
        seen_shas.add(sha)
        meta = c.get("commit", {})
        author = meta.get("author") or {}
        committer = meta.get("committer") or {}
        parents = " ".join(p["sha"] for p in c.get("parents", []))
        ane = (c.get("author") or {}).get("login") or ""
        msg = meta.get("message", "")
        subject = msg.split("\n", 1)[0]
        pairs = schema.parse_trailer_block(msg)
        v = schema.evaluate(sha[:9], subject, committer.get("date", "1970-01-01T00:00:00Z"),
                            parents, author.get("name", ane), author.get("email", ""),
                            pairs, cutoff)
        checked += 1
        if v["status"] == "violations":
            violations.append({**v, "committer": committer.get("date", "")})
        elif v["status"] == "exempt":
            exempt.append(v)

    residue, tree_truncated = [], False
    if cfg.get("residue", True) and head:
        st3, tree = api_get(f"{API}/repos/{owner}/{name}/git/trees/{head}?recursive=1")
        if st3 != 200 or not tree:
            faults.append(f"API {owner}/{name} tree: HTTP {st3}")
        else:
            tree_truncated = bool(tree.get("truncated"))
            for e in tree.get("tree", []):
                if e.get("type") == "blob":
                    pat = schema.residue_hit(e["path"])
                    if pat:
                        residue.append({"path": e["path"], "pattern": pat})

    return {"faults": faults, "violations": violations, "residue": residue,
            "exempt": exempt, "checked": checked, "head": head,
            "default_branch": db, "truncated_commits": truncated,
            "tree_truncated": tree_truncated}


def needed_calls(n_repos):
    return 1 + n_repos * (1 + MAX_PAGES + 1)  # rate + repo + pages + tree (upper bound)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--init", action="store_true", help="full run since cutoff; seed baseline faults")
    a = ap.parse_args()

    cfg = load_targets()
    state_path = os.path.join(HERE, ".glassbox_sweep_state.json")
    state = load_state(state_path)
    owner = cfg["owner"]
    cutoff = cfg.get("cutoff_utc", schema.CUTOFF_UTC)
    repos = cfg["repos"]

    # rate-budget check BEFORE burning calls
    st, rl = api_get(f"{API}/rate_limit")
    remaining = (rl or {}).get("resources", {}).get("core", {}).get("remaining", 60)
    need = sum(1 for r in repos) * 3 + 1
    if remaining < need:
        print(f"SKIP glassbox-sweep: anon rate limit {remaining} < ~{need} needed; "
              "retry next night")
        return 0

    now = iso_z(datetime.now(timezone.utc))
    lines, mut = [], {}
    for rcfg in repos:
        name = rcfg["name"]
        rs = state["repos"].setdefault(name, {})
        cursor = None if a.init else rs.get("cursor_iso")
        since = max(filter(None, [cutoff, cursor]), key=lambda s: s) if (cursor and not a.init) else cutoff
        res = sweep_repo(owner, name, rcfg, cutoff, since if rcfg.get("trailers", True) else None)
        mut[name] = {"cursor_iso": now, "head": res["head"], "default_branch": res["default_branch"]}

        known_v = set(rs.get("baseline_violations", []))
        known_r = set(f'{x["path"]}|{x["pattern"]}' for x in rs.get("baseline_residue", []))
        if a.init:   # seeding a baseline must not cry wolf: everything current is baseline
            known_v |= {v["sha"] for v in res["violations"]}
            known_r |= {f'{r["path"]}|{r["pattern"]}' for r in res["residue"]}
        new_v = [v for v in res["violations"] if v["sha"] not in known_v]
        new_r = [r for r in res["residue"] if f'{r["path"]}|{r["pattern"]}' not in known_r]
        if a.init:
            mut[name]["baseline_violations"] = [v["sha"] for v in res["violations"]]
            mut[name]["baseline_residue"] = res["residue"]
        mut[name]["exempt_seen"] = sorted(set(rs.get("exempt_seen", [])) |
                                          {e["sha"] for e in res["exempt"]})
        mut[name]["counts"] = {"checked": res["checked"],
                               "violations_total": len(res["violations"]),
                               "residue_total": len(res["residue"])}

        if a.digest:
            print(f"== {owner}/{name} :: head={(res['head'] or '-')[:9]} "
                  f"checked={res['checked']} violations={len(res['violations'])} "
                  f"exempt={len(res['exempt'])} residue={len(res['residue'])}"
                  + (" [commits TRUNCATED]" if res.get("truncated_commits") else "")
                  + (" [tree TRUNCATED]" if res.get("tree_truncated") else ""))
            for f_ in res["faults"]:
                print("  FAULT " + f_)
            for v in res["violations"]:
                print(f"  VIOL  {v['sha']} {v['committer']} \"{v['subject'][:58]}\" :: "
                      + "; ".join(v["reasons"]))
            for e in res["exempt"]:
                print(f"  EXEM  {e['sha']} :: {e['reasons'][0]}")
            for r in res["residue"]:
                print(f"  RESD  {r['path']} (matched {r['pattern']})")
        else:
            for f_ in res["faults"]:
                lines.append(f_ if f_.startswith(("WALL", "SKIP")) else f"API-FAULT {f_}")
            for v in new_v:
                lines.append(f"NEW VIOLATION {owner}/{name} {v['sha']} "
                             f"\"{v['subject'][:58]}\" :: " + "; ".join(v["reasons"]))
            for r in new_r:
                lines.append(f"NEW RESIDUE {owner}/{name} {r['path']} (matched {r['pattern']})")

    # persist state on every non-digest run
    if not a.digest:
        state["repos"].update({k: {**state["repos"].get(k, {}), **v} for k, v in mut.items()})
        state["last_run_utc"] = now
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, state_path)

    if lines:
        print(f"GLASSBOX SWEEP ({schema.SCHEMA_VERSION}) — {len(lines)} issue(s), "
              f"{now}:")
        for l in lines:
            print("  " + l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
