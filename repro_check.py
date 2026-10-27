#!/usr/bin/env python3
"""Step 10: regenerate twice with the same seed and compare row counts + SHA-256 checksums.

    python repro_check.py --profile full --seed 20261022
    python repro_check.py --profile starter --compare data/starter     # also compare to committed data

Also demonstrates the converse: a different seed must produce different checksums.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(profile, seed, out):
    subprocess.run([sys.executable, os.path.join(HERE, "generate.py"), "--profile", profile,
                    "--seed", str(seed), "--out", out], check=True, stdout=subprocess.DEVNULL)
    with open(os.path.join(out, "manifest.json")) as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="starter")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--compare", help="existing data dir to compare against as a third run")
    ap.add_argument("--report", help="write JSON report here")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        m1 = run(a.profile, a.seed, os.path.join(tmp, "run1"))
        m2 = run(a.profile, a.seed, os.path.join(tmp, "run2"))
        m3 = run(a.profile, a.seed + 1, os.path.join(tmp, "other_seed"))
    runs = {"run1": m1, "run2": m2}
    if a.compare:
        with open(os.path.join(a.compare, "manifest.json")) as fh:
            runs["committed"] = json.load(fh)
    rows = []
    ok = True
    for f in sorted(m1["files"]):
        same = all(r["files"].get(f, {}).get("sha256") == m1["files"][f]["sha256"] for r in runs.values())
        diff_seed = m3["files"][f]["sha256"] != m1["files"][f]["sha256"] if f.startswith("csv/applicant") else None
        ok &= same
        rows.append((f, same, m1["files"][f]["sha256"][:12]))
    counts_same = all(r["row_counts"] == m1["row_counts"] for r in runs.values())
    ok &= counts_same
    seed_sensitive = m3["files"]["csv/applicant.csv"]["sha256"] != m1["files"]["csv/applicant.csv"]["sha256"]
    print(f"{'file':44s}{'identical across runs':>24s}  sha256[:12]")
    for f, same, h in rows:
        print(f"{f:44s}{str(same):>24s}  {h}")
    print(f"\nrow counts identical : {counts_same}")
    print(f"different seed changes output (sanity): {seed_sensitive}")
    print(f"compared runs: {', '.join(runs)}")
    print("REPRODUCIBLE" if ok and seed_sensitive else "NOT REPRODUCIBLE")
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(dict(profile=a.profile, seed=a.seed, runs=list(runs), row_counts=m1["row_counts"],
                           identical=ok, files={f: dict(identical=s, sha256=m1["files"][f]["sha256"]) for f, s, _ in rows},
                           seed_sensitive=seed_sensitive), fh, indent=2)
    sys.exit(0 if ok and seed_sensitive else 1)


if __name__ == "__main__":
    main()
