from __future__ import annotations

import sys
from pathlib import Path

# Allows both:
#   python -m mozok_game.main
# and:
#   python mozok_game\main.py
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mozok_game.ui.pygame_app import PygameApp


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    app = PygameApp(base_dir)
    app.run()


if __name__ == "__main__":
    main()
