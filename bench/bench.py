from __future__ import annotations

import math
import os
import platform
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from croniter import croniter as upstream_croniter  # noqa: E402
from mojo_croniter import croniter as mojo_croniter  # noqa: E402


def timeit(function, repeat: int = 2) -> float:
    best = math.inf
    for _ in range(repeat):
        started = time.perf_counter()
        function()
        best = min(best, time.perf_counter() - started)
    return best


def scalar(implementation, expression: str, count: int, start: datetime) -> None:
    iterator = implementation(expression, start)
    for _ in range(count):
        iterator.get_next()


def bulk_mojo(expression: str, count: int, start: datetime) -> None:
    mojo_croniter(expression, start).get_next_n(count)


CASES = [
    ("Every minute, scalar", "* * * * *", 50_000, False),
    ("Every 10 seconds, scalar", "*/10 * * * * *", 50_000, False),
    ("Business hours, scalar", "*/15 9-17 * * mon-fri", 50_000, False),
    ("Every minute, bulk", "* * * * *", 200_000, True),
    ("Business hours, bulk", "*/15 9-17 * * mon-fri", 100_000, True),
]


def cpu_name() -> str:
    path = "/proc/cpuinfo"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown CPU"


def main() -> None:
    start = datetime(2024, 1, 1)
    print(f"Machine: {cpu_name()}; {platform.system()} {platform.machine()}; Python {platform.python_version()}")
    print()
    print("| case | occurrences | mojo-croniter | croniter 6.2.4 | speedup |")
    print("|---|---:|---:|---:|---:|")
    for name, expression, count, bulk in CASES:
        if bulk:
            ours = lambda e=expression, n=count: bulk_mojo(e, n, start)
        else:
            ours = lambda e=expression, n=count: scalar(mojo_croniter, e, n, start)
        theirs = lambda e=expression, n=count: scalar(upstream_croniter, e, n, start)
        ours()
        theirs()
        mojo_seconds = timeit(ours)
        python_seconds = timeit(theirs)
        print(
            f"| {name} | {count:,} | {mojo_seconds * 1000:.2f} ms | "
            f"{python_seconds * 1000:.2f} ms | {python_seconds / mojo_seconds:.2f}x |"
        )


if __name__ == "__main__":
    main()
