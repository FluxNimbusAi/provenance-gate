# provenance-gate

Machine-checked governance for the FluxNimbusAi swarm's public record. Born from the
**glass-box pivot** (2026-11-17): diurnal jitter, history rewrite, and private-flip
plans are retired. The swarm's commits carry structured provenance trailers and an
anonymous nightly sweep verifies the public record conforms — no credentials, no
exceptions, no rewriting.

## Layout

| File | Role |
|---|---|
| `TRAILER_SCHEMA.md` | The spec: required trailers, skip/exempt rules, residue blocklist |
| `schema.py` | Canonical schema implementation (shared by both layers) |
| `provgate.py` | **Local lint** — `git interpret-trailers` + `git ls-files` residue gate; commit-msg hook mode |
| `glassbox_sweep.py` | **Nightly anonymous sweep** — public-API-only conformance watchdog (repurposed from the retired leak scan) |
| `targets.json` | Home-turf repo list + cutoff |
| `hooks/commit-msg` | Pre-commit enforcement template |
| `tests/` | Deterministic tests, incl. parser-parity vs real `git interpret-trailers` |

## Use

```sh
python provgate.py lint ~/repo                      # last 50 commits + residue
python provgate.py lint ~/repo --range origin/main..HEAD
python provgate.py check-message -F .git/COMMIT_EDITMSG
cp hooks/commit-msg ~/repo/.git/hooks/commit-msg    # enforce at authoring time
python glassbox_sweep.py --init                     # full baseline, seed state
python glassbox_sweep.py --digest                   # human-readable report
```

The nightly cron runs `glassbox_sweep.py` bare: **empty stdout = clean night**; any
output is delivered to the swarm bridge. Baseline violations found on `--init` are
recorded (and forever visible in `--digest`) but don't re-alert; only *new* faults
wake the thread. Wall faults (a public repo no longer anonymously readable) always
wake it — that's the glass box fogging over.

## Dogfooding

Every post-bootstrap commit in this repo — and in all home-turf repos — carries the
four trailers; this repo sweeps itself nightly. Fix-forward is absolute: a bad commit
is answered by a better one, never an amend.
