#!/usr/bin/env python3
"""Lối tắt theo kế hoạch cho `python -m app.quality.noise <labels.csv>`."""

import sys

from app.quality.noise import main

if __name__ == "__main__":
    sys.exit(main())
