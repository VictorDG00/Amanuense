#!/usr/bin/env python3
"""Convenience wrapper: run the full pipeline from CLI."""
import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "pipeline.run", "run"] + sys.argv[1:], check=True)
