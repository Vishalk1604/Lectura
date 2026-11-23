"""Launcher used by PyInstaller (and handy for running from source)."""

import sys

from lectura.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
