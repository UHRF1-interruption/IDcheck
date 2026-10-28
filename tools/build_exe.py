#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebuild dist/idcheck.exe with PyInstaller.

PyInstaller is installed into .build/pylib (not the system Python) so the
interpreter stays clean:

    python -m pip install --target .build/pylib pyinstaller

Usage:  python tools/build_exe.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
PYLIB = os.path.join(ROOT, '.build', 'pylib')


def main():
    env = dict(os.environ)
    env['PYTHONPATH'] = PYLIB
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--onefile', '--console', '--name', 'idcheck',
        '--add-data', os.path.join(ROOT, 'data') + ';data',
        '--distpath', os.path.join(ROOT, 'dist'),
        '--workpath', os.path.join(ROOT, '.build', 'pyi'),
        '--specpath', os.path.join(ROOT, '.build'),
        os.path.join(ROOT, 'idcheck.py'),
    ]
    print(' '.join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT, env=env)
    if rc != 0:
        return rc
    exe = os.path.join(ROOT, 'dist', 'idcheck.exe')
    print('built %s (%.1f MB)' % (exe, os.path.getsize(exe) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
