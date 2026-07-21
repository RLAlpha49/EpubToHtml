"""Backward-compatible launcher for the package CLI."""

import sys
from pathlib import Path

# Keep ``python main.py`` working before the project is installed as a package.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cli import main

if __name__ == "__main__":
    main()
