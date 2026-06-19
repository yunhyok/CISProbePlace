import sys

from cisprobeplace import __version__
from cisprobeplace.gui import run_app


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"CIS Probe Placement Scriptor v{__version__}")
        raise SystemExit(0)
    if "--smoke" in sys.argv:
        raise SystemExit(0)
    raise SystemExit(run_app())
