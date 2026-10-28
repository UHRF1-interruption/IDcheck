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


def sign(env):
    """调用 tools/win_trust.ps1：解除网络标记 + 用本机自签证书签名。

    没有 PowerShell 或没有证书权限时只警告，不影响产物可用性。
    """
    ps = os.path.join(HERE, 'win_trust.ps1')
    if not os.path.exists(ps):
        return False
    cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
           '-File', ps, '-DistDir', DIST]
    rc = subprocess.call(cmd, cwd=ROOT, env=env)
    print('sign  : rc=%d' % rc)
    return rc == 0


def write_helpers(onedir):
    """在文件夹版里放一份"首次使用.cmd"：解除网络标记 + 导入自签证书 + 启动。"""
    text = (
        '@echo off\r\n'
        'chcp 936 >nul\r\n'
        'cd /d "%~dp0"\r\n'
        'echo ============================================================\r\n'
        'echo  idcheck 首次使用：解除 SmartScreen 的"来自互联网"标记\r\n'
        'echo ============================================================\r\n'
        'echo.\r\n'
        'echo [1/2] 解除本目录所有文件的网络来源标记...\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
        'Get-ChildItem -Recurse -File | Unblock-File"\r\n'
        'echo [2/2] 若存在 idcheck-codesign.cer，则导入本机受信任的根与发布者...\r\n'
        'if exist "idcheck-codesign.cer" (\r\n'
        '  powershell -NoProfile -ExecutionPolicy Bypass -Command "'
        'Import-Certificate -FilePath .\\idcheck-codesign.cer '
        '-CertStoreLocation Cert:\\CurrentUser\\Root '
        '-ErrorAction SilentlyContinue | Out-Null; '
        'Import-Certificate -FilePath .\\idcheck-codesign.cer '
        '-CertStoreLocation Cert:\\CurrentUser\\TrustedPublisher '
        '-ErrorAction SilentlyContinue | Out-Null"\r\n'
        ')\r\n'
        'echo.\r\n'
        'echo 完成：以后双击 idcheck.exe 不会再被 SmartScreen 拦截。\r\n'
        'echo 现在启动 idcheck...\r\n'
        'start "" /D "%~dp0" "%~dp0idcheck.exe"\r\n'
        'exit /b 0\r\n'
    )
    cer = os.path.join(DIST, 'idcheck-codesign.cer')
    if os.path.exists(cer):
        shutil.copy2(cer, os.path.join(onedir, 'idcheck-codesign.cer'))
        print('wrote : %s' % os.path.join(onedir, 'idcheck-codesign.cer'))
    path = os.path.join(onedir, '首次使用.cmd')
    with open(path, 'w', encoding='gbk', errors='replace', newline='') as f:
        f.write(text)
    print('wrote : %s' % path)
    stale = os.path.join(onedir, '解除锁定.cmd')
    if os.path.exists(stale):
        os.remove(stale)


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

    # 2) single-file build (portable)
    single = os.path.join(DIST, 'idcheck-single.exe')
    if os.path.exists(single):
        os.remove(single)
    if pyinstaller('--onefile', env) != 0:
        return 1
    built = os.path.join(DIST, 'idcheck.exe')
    if os.path.exists(built) and built != single:
        os.replace(built, single)

    # 3) 本机信任：解除"来自互联网"标记 + 自签代码签名
    #    不签名的话，SmartScreen 每次启动都会拦（发行者：未知）。
    sign(env)

    # 4) 签名之后再打包 zip，保证包里是已签名的 exe
    write_helpers(onedir)
    make_zip(onedir, os.path.join(
        DIST, 'idcheck-%s-win64.zip' % mark.replace(':', '').replace(' ', '_')))

    print('folder: %s' % exe)
    print('single: %s (%.1f MB)' % (single, os.path.getsize(single) / 1048576.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
