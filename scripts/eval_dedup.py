#!/usr/bin/env python3
"""Lối tắt theo kế hoạch cho `python -m app.quality.dedup <pairs.csv>`."""

import sys

from app.quality.dedup import main

if __name__ == "__main__":
    sys.exit(main())
