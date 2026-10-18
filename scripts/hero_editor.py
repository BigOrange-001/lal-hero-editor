"""Run the desktop authoring tool from a source checkout or frozen bundle."""
from pathlib import Path
import sys

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
for directory in (ROOT, ROOT / "server"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from editor.app import main

if __name__ == "__main__":
    raise SystemExit(main())
