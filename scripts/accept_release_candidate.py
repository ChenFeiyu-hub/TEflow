#!/usr/bin/env python3
"""Compatibility entry; use accept_release.py for 1.0 and later."""
from accept_release import main

if __name__ == '__main__':
    raise SystemExit(main())
