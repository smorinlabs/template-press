"""One synthetic test; no product, Git, filesystem or network operations."""

import os


def test_probe() -> None:
    case = os.environ.get("P11A_CASE", "pass")
    if case == "worker-loss":
        os._exit(17)
    if case == "fail":
        raise AssertionError("fixture assertion failure")
