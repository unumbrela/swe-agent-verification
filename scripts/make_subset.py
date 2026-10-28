"""Stratified-by-repo subset of a SWE-bench split: every repo gets >= 1 instance, the rest proportional (largest remainder)."""

import random
from collections import defaultdict
from pathlib import Path

import typer
from datasets import load_dataset


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    total = sum(counts.values())
    quota = {r: n * c / total for r, c in counts.items()}
    alloc = {r: max(1, int(q)) for r, q in quota.items()}
    for r in sorted(counts, key=lambda r: quota[r] - int(quota[r]), reverse=True):
        if sum(alloc.values()) >= n:
            break
        if alloc[r] < counts[r]:
            alloc[r] += 1
    while sum(alloc.values()) > n:
        alloc[max(alloc, key=alloc.get)] -= 1
    return alloc


def main(
    dataset: str = "princeton-nlp/SWE-Bench_Verified",
    split: str = "test",
    n: int = 50,
    seed: int = 42,
    output: Path = Path("configs/subset_verified_50.txt"),
):
    by_repo = defaultdict(list)
    for inst in load_dataset(dataset, split=split):
        by_repo[inst["repo"]].append(inst["instance_id"])
    rng = random.Random(seed)
    alloc = allocate({r: len(ids) for r, ids in by_repo.items()}, n)
    picked = sorted(iid for r in sorted(by_repo) for iid in rng.sample(sorted(by_repo[r]), alloc[r]))
    output.write_text("\n".join(picked) + "\n")
    for r in sorted(alloc, key=alloc.get, reverse=True):
        print(f"{r:28s} {alloc[r]:3d} / {len(by_repo[r])}")
    print(f"{len(picked)} instances -> {output}")


if __name__ == "__main__":
    typer.run(main)
