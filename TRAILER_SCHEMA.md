# Provenance Trailer Schema — `2026-11-17.v1`

Glass-box pivot (d3b0m3n directive 2026-11-17): the swarm's history is the product.
Diurnal jitter, history rewrite, and private-flip plans are **RETIRED**. Instead of
hiding telemetry, home-turf commits *are* the telemetry: every post-pivot commit on a
home-turf repo carries machine-parsable governance metadata.

## Scope

- **Applies to:** default branch of non-fork repos listed in `targets.json`
  (home turf). Currently: `tanda`, `tanda-miniapp`, `strata-field-notes`,
  `worldapp-recon`, `provenance-gate`.
- **Cutoff:** commits with **committer date ≥ 2026-11-17T00:00:00Z**. Older commits
  are `legacy_skipped` — honest history is never rewritten to look conformant.
- **Forks exempt:** upstream PRs follow the two-tier voice (Cause/Fix/Proof,
  maintainer register), never swarm trailers.

## Required trailers (exact keys, order, final paragraph)

```text
Swarm-Card: t_58468316
Executed-By: Nimbus (COO, PC node)
Adjudicated-By: d3b0m3n (glass-box directive 2026-11-17)
Receipt-SHA256: 6aa4c60e1f2b…(64 lowercase hex)
```

| Key | Value regex | Meaning |
|---|---|---|
| `Swarm-Card` | `^t_[0-9a-f]{8}$` | kanban card that authorized the work |
| `Executed-By` | `^(Flux\|Nimbus\|Harley\|Xixi\|d3b0m3n\|Farrow)\b` | who ran the change (role annotation allowed in parens) |
| `Adjudicated-By` | same roster, or exactly `pending` | who weighed the result; `pending` is visible debt, swept into digests |
| `Receipt-SHA256` | `^[0-9a-f]{64}$` | sha256 of the primary artifact (tree, capture JSON, receipt file) pinned in the card handoff |

Each required key must appear **exactly once** in the trailer block. Unknown extra
trailers (`Co-Authored-By:`, etc.) are allowed — this is git, not a straitjacket.

## Skip / exemption rules

| Class | Rule | Status |
|---|---|---|
| Merge commits | parents > 1 | `merge_skipped` |
| Bots | author name or email contains `[bot]` | `bot_skipped` |
| Pre-pivot | committer date < cutoff | `legacy_skipped` |
| Explicit exemption | trailer `Provenance-Exempt: <non-empty reason>` present | `exempt` |

`Provenance-Exempt` replaces the four required keys **only** when it carries a
non-empty reason, and the commit is still listed in every digest. An exemption you
can see is worth ten you can't. **Adopting an exemption is a public act; the fix-forward
rule applies: never amend, always add a conformant commit.**

## Enforcement layers

1. **Local lint** — `provgate.py lint` runs `git interpret-trailers --parse` per commit +
   `git ls-files` residue check. Usable as a `commit-msg` hook (`hooks/commit-msg`).
2. **Nightly anonymous sweep** — `glassbox_sweep.py` reads the *public* GitHub API with
   **no credentials**, verifying exactly what the world sees: wall integrity
   (public repo must remain anonymously readable — a 404 is a glass-box break),
   trailer-schema conformance, and tracked-file residue via the recursive tree API.
   Watchdog discipline: silent when clean, speaks only on new violations.

## Residue blocklist (tracked paths)

Path-based only — the sweep reports matching paths, **never file contents**.
Secret-shaped names (`.env*` except `.env.example`/`.env.sample`, `*.pem`, `*.key`,
`*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `*secret*`, `*credential*`, `*apikey*`,
`*api-key*`, `*mnemonic*`, `*seedphrase*`, `*.kdbx`, state/kanban `*.db`, `*.sqlite*`)
and artifact-shaped paths (segment matches `node_modules/`, `__pycache__/`, `.venv/`,
`venv/`, `dist/`, `build/`, `out/`, `cache/`, `target/`, `.next/`; `*.pyc`, `*.pyo`,
`*.log`, `.DS_Store`, `Thumbs.db`).
A false positive is resolved by renaming/reviewing the file or the pattern — in public.
