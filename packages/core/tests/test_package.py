import pids_core


def test_version_is_exposed() -> None:
    assert pids_core.__version__ == "0.1.0"
