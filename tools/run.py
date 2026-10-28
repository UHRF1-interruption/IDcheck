# -*- coding: utf-8 -*-
"""Forces UTF-8 console output on Windows, then runs idcheck.main()."""

import io
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))

for stream in ('stdout', 'stderr'):
    s = getattr(sys, stream)
    try:
        s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import idcheck  # noqa: E402

if __name__ == '__main__':
    sys.exit(idcheck.main(sys.argv[1:]))
