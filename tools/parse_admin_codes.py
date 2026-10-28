#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse the wiki-markup administrative-division table (行政区划代码.txt) into the
single compact table data/idcheck_tables.txt used by idcheck.

Format (UTF-8, LF, tab separated):

    #idcheck administrative divisions
    #provinces
    <2-digit code>\t<name>
    #divisions
    <6-digit code>\t<first year>\t<abolished year, 0 = still in use>\t<name>

Source quirks handled:
  * most rows separate cells with '||', but a few (133100 雄安新区, 330113 临平区,
    330114 钱塘区) put one cell per line — both forms are parsed;
  * '…' in the 废止年份 column marks a code still in use;
  * rows marked 未曾使用 carry names that were never assigned and are dropped;
  * the first '<br>'-separated name variant is the current one;
  * the 启用年份 column is '○' for codes present in the 1980 edition.

Usage:  python tools/parse_admin_codes.py [source.txt]
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', 'data'))
DEFAULT_SOURCE = os.path.join(DATA, '行政区划代码.txt')

HEADING_RE = re.compile(r'^==\s*([^=]+?)\s*==\s*$')
LINK_RE = re.compile(r'\[\[(?:\\.|[^\]|])*\|([^\]]*)\]\]|\[\[([^\]]*)\]\]')
BR_RE = re.compile(r'\s*<br\s*/?>\s*')
ANNOT_RE = re.compile(r'\s*[（(][^（）()]*年[^（）()]*[）)]\s*$')
CODE_RE = re.compile(r'^\d{6}$')
YEAR_RE = re.compile(r'(\d{4})')


def clean_name(cell):
    """One wiki cell holding a (possibly annotated) division name -> plain text."""
    text = LINK_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), cell)
    parts = [p.strip() for p in BR_RE.split(text) if p.strip()]
    if parts:
        text = parts[0]                    # first variant = current name
    text = ANNOT_RE.sub('', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def first_year(cell):
    cell = cell.strip()
    if cell == '○':
        return 1980
    m = YEAR_RE.search(cell)
    if not m:
        raise ValueError('bad 启用年份: %r' % cell)
    return int(m.group(1))


def last_year(cell):
    cell = cell.strip()
    if cell == '…':
        return 0
    m = YEAR_RE.search(cell)
    if not m:
        raise ValueError('bad 废止年份: %r' % cell)
    return int(m.group(1))


def parse(source):
    provinces = []
    divisions = []
    with open(source, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    def add(code, first, last, name_cell):
        if '未曾使用' in last or '未曾使用' in name_cell:
            return
        name = clean_name(name_cell)
        if not name:
            return
        if code[2:] == '0000':
            return                          # province row: heading is authoritative
        divisions.append((code, first_year(first), last_year(last), name))

    pending = []
    for raw in lines:
        line = raw.strip()
        m = HEADING_RE.match(line)
        if m:
            pending = []
            title = m.group(1)
            m2 = re.match(r'^(.*?)[（(](\d{2})[）)]$', title)
            if not m2:
                raise SystemExit('unexpected heading: %r' % line)
            provinces.append((m2.group(2), m2.group(1).strip()))
            continue
        if line in ('|}', ''):
            continue
        if line.startswith('|-') or line.startswith('|}'):
            continue
        if not line.startswith('|'):
            continue
        body = line.strip('|')
        if '||' in line:
            pending = []
            cells = [c.strip() for c in body.split('||')]
            if not cells or not CODE_RE.match(cells[0]):
                continue
            if '未曾使用' in body:
                continue
            if len(cells) < 4:
                raise SystemExit('short row: %r' % line)
            add(cells[0], cells[1], cells[2], cells[3])
        else:
            pending.append(body)
            if len(pending) == 4:
                add(pending[0], pending[1], pending[2], pending[3])
                pending = []

    provinces.sort()
    divisions.sort()
    return provinces, divisions


def main(argv):
    source = argv[1] if len(argv) > 1 else DEFAULT_SOURCE
    provinces, divisions = parse(source)
    out = os.path.join(DATA, 'idcheck_tables.txt')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('#idcheck administrative divisions (GB/T 2260 history)\n')
        f.write('#provinces\n')
        for code, name in provinces:
            f.write('%s\t%s\n' % (code, name))
        f.write('#divisions\n')
        for code, first, last, name in divisions:
            f.write('%s\t%d\t%d\t%s\n' % (code, first, last, name))
    cur = sum(1 for d in divisions if d[2] == 0)
    print('provinces: %d' % len(provinces))
    print('divisions: %d (current %d, abolished %d)'
          % (len(divisions), cur, len(divisions) - cur))
    print('wrote', out, '(%d bytes)' % os.path.getsize(out))


if __name__ == '__main__':
    main(sys.argv)
