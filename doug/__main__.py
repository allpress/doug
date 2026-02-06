"""Allow running doug as a module: python -m doug"""
import sys

from doug.cli import main

if __name__ == "__main__":
    sys.exit(main())
