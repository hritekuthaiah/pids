"""PIDS domain core.

Everything in this package is pure computation over typed values: no network,
database, filesystem or clock access. That keeps the decision logic — the part
of the system the evaluation and the paper stand on — deterministic, fast to
test, and identical whether it runs on the edge node, the server or inside the
offline evaluation harness.
"""

__version__ = "0.1.0"
