#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse ISO 3166-1 numeric country codes (国家代码.txt) into data/country_codes.txt.

Source: wiki-markup tables; rows look like

    | <tt>004</tt> || [[阿富汗]] || Afghanistan

Only the first table (currently assigned codes) is used; the second table lists
codes the UN statistics division uses but ISO 3166-1 never assigned
(e.g. 830 海峡群岛), which must NOT be treated as nationalities.

Output (UTF-8, LF):  <3-digit code>\t<name>       one line per country

Usage: python tools/parse_country_codes.py [source.txt]
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, '..', 'data'))

ROW_RE = re.compile(r'^\|\s*<tt>(\d{3})</tt>\s*\|\|(.*)$', re.M)
LINK_RE = re.compile(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]')


def clean(text):
    text = LINK_RE.sub(r'\1', text)
    text = text.split('||')[0]
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\{\{.*?\}\}', '', text)     # {{NoteTag|...}} 等模板说明
    return text.strip()


def main(argv):
    src_path = argv[1] if len(argv) > 1 else os.path.join(DATA, '国家代码.txt')
    with open(src_path, encoding='utf-8-sig') as f:
        src = f.read()
    cut = src.find('从未正式列入')
    if cut < 0:
        raise SystemExit('找不到第二张表的说明文字，无法区分"已分配"与"联合国统计代码"')
    rows = []
    for m in ROW_RE.finditer(src):
        if m.start() > cut:
            continue
        code = m.group(1)
        name = clean(m.group(2))
        if not name:
            continue
        rows.append((code, name))
    seen = {}
    for code, name in rows:
        seen.setdefault(code, name)
    out = os.path.join(DATA, 'country_codes.txt')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('#ISO 3166-1 numeric codes (currently assigned only)\n')
        for code in sorted(seen):
            f.write('%s\t%s\n' % (code, seen[code]))
    print('wrote %s (%d countries)' % (out, len(seen)))


if __name__ == '__main__':
    main(sys.argv)
