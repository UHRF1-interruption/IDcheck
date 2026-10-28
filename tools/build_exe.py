#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pack idcheck with PyInstaller.

Two artefacts are produced:

  dist/idcheck/            folder build (recommended): idcheck.exe + _internal,
                           starts instantly and never touches %TEMP%
  dist/idcheck-single.exe  single-file build: handy to copy as one file, but it
                           unpacks into %TEMP% on every start

The single-file exe dies instantly — with a console window that flashes and
closes — when %TEMP% is not writable (locked-down profile, antivirus, full
disk).  That is exactly what "double-click does nothing" looks like, so the
folder build is the default deliverable.

PyInstaller lives in .build/pylib (kept out of the system interpreter):

    python -m pip install --target .build/pylib pyinstaller

Usage:  python tools/build_exe.py
"""

import io
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
PYLIB = os.path.join(ROOT, '.build', 'pylib')
DIST = os.path.join(ROOT, 'dist')


def stamp_build():
    """Write the build time into idcheck.BUILD so an exe can be identified."""
    path = os.path.join(ROOT, 'idcheck.py')
    src = io.open(path, encoding='utf-8').read()
    mark = time.strftime('%Y-%m-%d %H:%M')
    out = []
    for line in src.splitlines(True):
        if line.startswith('BUILD = '):
            line = "BUILD = '%s'\n" % mark
        out.append(line)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(''.join(out))
    print('build stamp:', mark)
    return mark


def pyinstaller(mode, env):
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', mode, '--console', '--name', 'idcheck',
        '--add-data', os.path.join(ROOT, 'data') + ';data',
        '--hidden-import', 'idcheck_gui',
        '--hidden-import', 'idcheck',
        '--collect-submodules', 'tkinter',
        '--distpath', DIST,
        '--workpath', os.path.join(ROOT, '.build', 'pyi'),
        '--specpath', os.path.join(ROOT, '.build'),
        os.path.join(ROOT, 'idcheck.py'),
    ]
    print('$ ' + ' '.join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=env)


def make_zip(src_dir, zpath):
    if os.path.exists(zpath):
        os.remove(zpath)
    base = os.path.dirname(src_dir)
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, base))
    print('zip   : %s (%.1f MB)' % (zpath, os.path.getsize(zpath) / 1048576.0))


def main():
    mark = stamp_build()
    env = dict(os.environ)
    env['PYTHONPATH'] = PYLIB
    env.setdefault('PYTHONIOENCODING', 'utf-8')

    # 1) folder build (default deliverable)
    onedir = os.path.join(DIST, 'idcheck')
    if os.path.isdir(onedir):
        shutil.rmtree(onedir, ignore_errors=True)
    if pyinstaller('--onedir', env) != 0:
        return 1
    exe = os.path.join(DIST, 'idcheck', 'idcheck.exe')
    if not os.path.exists(exe):
        raise SystemExit('onedir build missing: %s' % exe)
    make_zip(onedir, os.path.join(
        DIST, 'idcheck-%s-win64.zip' % mark.replace(':', '').replace(' ', '_')))

    # 2) single-file build (portable)
    single = os.path.join(DIST, 'idcheck-single.exe')
    if os.path.exists(single):
        os.remove(single)
    if pyinstaller('--onefile', env) != 0:
        return 1
    built = os.path.join(DIST, 'idcheck.exe')
    if os.path.exists(built) and built != single:
        os.replace(built, single)

    print('folder: %s' % exe)
    print('single: %s (%.1f MB)' % (single, os.path.getsize(single) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
