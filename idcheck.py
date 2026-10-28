#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idcheck —— 身份证号码校验、错位诊断与区划代码反推（GB 11643 / 2023 版永居证）

号码结构
  公民身份号码（18 位）：
     第 1–6   地址码（行政区划代码）      第 7–14  出生日期码 YYYYMMDD
     第 15–17 顺序码（末位奇男偶女）      第 18    校验码
  外国人永久居留身份证（18 位，2023 版）：
     第 1     标识码，固定 "9"            第 2–3   申领地（省级行政区划代码）
     第 4–6   国籍（ISO 3166-1 数字代码）  其余与公民身份号码相同
  校验码：c = (12 − (Σ a_i·W_i mod 11)) mod 11，c = 10 记作 'X'，
          W_i = 2^(18−i) mod 11 = 7 9 10 5 8 4 2 1 6 3 7 9 10 5 8 4 2 1

本程序解决的手抄件问题
  1. 校验：号码本身是否合法，区划、日期、顺序码、校验码逐项报告。
  2. 错位：手抄时两字粘连、漏字、多字、换位会让后面整体错位。程序枚举全部
     “读数”（原样 / 替换 / 插入 / 删除 / 换位 / 合并），每个读数按概率计权。
  3. 反推：校验码是一条模 11 的线性方程。给定读数，任一可疑位上的正确值都能
     由其余位唯一解出（每个位置恰好一个解），所以“把每一位该改成什么”是可算的。
     程序把全部候选号码按概率排序，并逐位列出可能的数字及其占比。

用法
  idcheck check   11010219840406970X
  idcheck analyze 11010219840406970X
  idcheck analyze "11010219840406970 8"          # 空格 = 该位看不清/缺位
  idcheck analyze 1101021984040697OX --gender 男
  idcheck analyze 1101021984040697OX --foreign 是
  idcheck analyze --stdin
  idcheck demo

只用标准库；数据表在 data/ 下，随 exe 一起打包。
"""

import argparse
import datetime
import json
import math
import os
import sys
import time

VERSION = '1.0'

# ---------------------------------------------------------------------------
# 基本常量
# ---------------------------------------------------------------------------

ALPHABET = '0123456789X'
IDX = {c: i for i, c in enumerate(ALPHABET)}
N_CHARS = 11

W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2, 1]

# 港澳台居民居住证：邮编前三位 + 000
RESIDENCE_REGIONS = {
    '810000': '香港特别行政区',
    '820000': '澳门特别行政区',
    '830000': '台湾省',
}

LOG_ZERO = -1.0e300
TODAY = datetime.date.today()
REF_YMD = (TODAY.year + 1, 12, 31)


def _data_dir():
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        packed = os.path.join(base, 'data')
        if os.path.isdir(packed):
            return packed
        return os.path.join(os.path.dirname(sys.executable), 'data')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


DATA_DIR = _data_dir()


def slog(x):
    return math.log(x) if x > 0.0 else LOG_ZERO


def checksum_of(cols):
    """17 列（可含缺位 → 返回 ''）→ 校验码字符。"""
    s = 0
    for i in range(17):
        c = cols[i] if i < len(cols) else -1
        if c < 0:
            return ''
        s += c * W[i]
    r = (12 - s % 11) % 11
    return 'X' if r == 10 else chr(48 + r)


# ---------------------------------------------------------------------------
# 数据表
# ---------------------------------------------------------------------------

class Admin:
    """行政区划库：6 位代码 → [(启用年, 废止年或 0, 名称)]。"""

    def __init__(self, provinces, divisions):
        self.provinces = provinces            # '11' -> '北京市'
        self.divs = divisions                 # '110102' -> [(1980, 0, '西城区')]
        names = set(provinces.values())
        for lst in divisions.values():
            for _, _, name in lst:
                names.add(name)
        names.update(RESIDENCE_REGIONS.values())
        self.name_set = names

    def lookup(self, code6, year=None):
        """返回 (命中, 名称, 说明, 时效等级)。

        时效等级 2 = 出生年有效；1 = 仅边界年（启用年或废止年）可能；
                 0 = 与时序矛盾；None = 无出生年可判。
        """
        if code6 in RESIDENCE_REGIONS:
            return (True, RESIDENCE_REGIONS[code6], '港澳台居民居住证', None)
        intervals = self.divs.get(code6)
        prov = self.provinces.get(code6[:2])
        if not intervals:
            if code6[2:] == '0000':
                if prov:
                    return (True, prov, '省级行政单位', None)
                return (False, '', '区划未知（省级代码 %s 不在库中）' % code6[:2], None)
            if code6[4:] == '00':
                head = prov or '省 %s' % code6[:2]
                return (False, '', '区划未知（%s 下无地级代码 %s）' % (head, code6), None)
            head = prov if prov else '省 %s' % code6[:2]
            return (False, '', '区划未知（%s 下无代码 %s）' % (head, code6), None)
        if year is None:
            first, last, name = intervals[0] if intervals[0][1] == 0 else intervals[-1]
            return (True, self._full(code6, name), '现行' if last == 0 else '已废止', None)
        for first, last, name in intervals:
            if year >= first and (last == 0 or year <= last):
                if year == first:
                    tag, level = '启用当年', 1
                elif last and year == last:
                    tag, level = '废止当年', 1
                else:
                    tag, level = '有效', 2
                return (True, self._full(code6, name), tag, level)
        best = None
        for first, last, name in intervals:
            gap = (first - year) if year < first else ((year - last) if last else -1)
            if best is None or gap < best[0]:
                best = (gap, first, last, name)
        gap, first, last, name = best
        if year < first:
            return (False, self._full(code6, name),
                    '出生%d年早于代码%d年启用' % (year, first), 0)
        return (False, self._full(code6, name),
                '出生%d年晚于代码%d年废止' % (year, last), 0)

    def _full(self, code6, name):
        if code6[2:] == '0000':
            return name
        prov = self.provinces.get(code6[:2])
        if not prov:
            return name
        return prov + name


def load_tables():
    path = os.path.join(DATA_DIR, 'idcheck_tables.txt')
    if not os.path.exists(path):
        raise SystemExit('找不到区划表：%s\n（源码运行时先执行 python tools/parse_admin_codes.py）'
                         % path)
    provinces = {}
    divs = {}
    section = None
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            if line.startswith('#'):
                if line.strip() in ('#provinces', '#divisions'):
                    section = line.strip()
                continue
            cells = line.split('\t')
            if section == '#provinces':
                provinces[cells[0]] = cells[1]
            elif section == '#divisions':
                code = cells[0]
                divs.setdefault(code, []).append((int(cells[1]), int(cells[2]), cells[3]))
    for code in divs:
        divs[code].sort()
    return Admin(provinces, divs)


class Countries:
    def __init__(self, table):
        self.table = table

    def name(self, code3):
        return self.table.get(code3)


def load_countries():
    path = os.path.join(DATA_DIR, 'country_codes.txt')
    table = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                cells = line.split('\t')
                if len(cells) >= 2:
                    table[cells[0]] = cells[1]
    return Countries(table)


# ---------------------------------------------------------------------------
# 输入规范化
# ---------------------------------------------------------------------------
# 手抄/OCR 常见混淆先统一：O/o/〇 → 0，I/l/| → 1，×/x → X；空格或下划线表示
# “这一位看不清”，是缺位而不是分隔符。

OCR_PAIRS = [
    ('OO', '00'), ('oO', '00'), ('Oo', '00'), ('oo', '00'),
    ('〇〇', '00'), ('ΟΟ', '00'),
    ('〇', '0'), ('Ο', '0'), ('O', '0'), ('o', '0'),
    ('I', '1'), ('l', '1'), ('|', '1'), ('！', '1'),
    ('×', 'X'), ('x', 'X'), ('ｘ', 'X'),
    ('，', ''), ('。', ''), ('；', ''), ('、', ''),
    ('“', ''), ('”', ''), ('（', ''), ('）', ''), ('(', ''), (')', ''),
    ('　', ' '), ('－', ''), ('-', ''), ('—', ''),
]


def normalize_ocr(text):
    out = []
    notes = []
    i = 0
    n = len(text)
    while i < n:
        for pat, rep in OCR_PAIRS:
            if text.startswith(pat, i):
                out.append(rep)
                if pat != rep:
                    notes.append('%s→%s' % (pat, rep if rep else '（删除）'))
                i += len(pat)
                break
        else:
            out.append(text[i])
            i += 1
    return ''.join(out), notes


def sanitize(text):
    """返回 (规范化串, 提示)。串里只含 0-9 / X / 空格（空格 = 缺位）。"""
    text = text.strip().replace('\ufeff', '').replace('\u200b', '')
    text, notes = normalize_ocr(text.strip())
    out = []
    bad = []
    for ch in text:
        if ch.isdigit() and ord(ch) < 128:
            out.append(ch)
        elif ch in 'xX':
            out.append('X')
        elif ch in ' \t_?？':
            out.append(' ')
        elif ch not in bad:
            bad.append(ch)
    if bad:
        notes.append('忽略非号码字符：%s（要表示“看不清”请用空格）' % ' '.join(bad))
    s = ''.join(out).strip()
    while '  ' in s:
        s = s.replace('  ', ' ')
    if len(s) > 18:
        notes.append('输入 %d 个字符，多于 18 位：多出的字符按“粘连/多写”处理' % len(s))
    elif len(s) < 18:
        notes.append('输入 %d 个字符，少于 18 位：缺的位按“漏字/缺位”处理' % len(s))
    if 'X' in s[:-1]:
        notes.append('号码中间出现 X：身份证只在第 18 位出现 X，此处按该位可疑处理')
    return s, notes


# ---------------------------------------------------------------------------
# 结构判定
# ---------------------------------------------------------------------------

class Info:
    __slots__ = ('kind', 'addr', 'div_ok', 'div_name', 'div_note', 'div_level',
                 'date', 'date_ok', 'date_note', 'seq_ok', 'sex', 'checksum',
                 'cs_ok', 'birth_year', 'country', 'country_ok', 'province')

    def __init__(self):
        self.kind = 'citizen'
        self.addr = None
        self.div_ok = False
        self.div_name = ''
        self.div_note = ''
        self.div_level = None
        self.date = None
        self.date_ok = False
        self.date_note = ''
        self.seq_ok = False
        self.sex = ''
        self.checksum = ''
        self.cs_ok = False
        self.birth_year = None
        self.country = None
        self.country_ok = False
        self.province = None


def parse_date(chars):
    if len(chars) < 8 or -1 in chars or any(c > 9 for c in chars):
        return None
    y = chars[0] * 1000 + chars[1] * 100 + chars[2] * 10 + chars[3]
    m = chars[4] * 10 + chars[5]
    d = chars[6] * 10 + chars[7]
    return y, m, d


def valid_date(y, m, d):
    if not (1900 <= y <= 2100) or not (1 <= m <= 12) or not (1 <= d <= 31):
        return False
    try:
        datetime.date(y, m, d)
        return True
    except ValueError:
        return False


def date_plausible(y, m, d):
    if not valid_date(y, m, d):
        return False
    ry, rm, rd = REF_YMD
    return (y, m, d) <= (ry, rm, rd)


CACHE_DIV = {}
CACHE_DATE = {}


def fast_flags(cols, admin, countries, kind):
    """结构判定的快路径：只算标志位，不拼字符串。返回 (div_ok, div_level,
    date_ok, seq_ok, sexbit, birth_year)。"""
    # 出生日期
    dc = cols[6:14]
    y = None
    date_ok = False
    if -1 not in dc and max(dc) <= 9:
        y = dc[0] * 1000 + dc[1] * 100 + dc[2] * 10 + dc[3]
        m = dc[4] * 10 + dc[5]
        d = dc[6] * 10 + dc[7]
        key = (y, m, d)
        hit = CACHE_DATE.get(key)
        if hit is None:
            hit = date_plausible(y, m, d)
            CACHE_DATE[key] = hit
        date_ok = hit
    seq_ok = cols[14] >= 0 and cols[15] >= 0 and cols[16] >= 0 and \
        cols[14] <= 9 and cols[15] <= 9 and cols[16] <= 9
    sexbit = (cols[16] & 1) if seq_ok else -1
    div_ok = False
    level = None
    if kind == 'foreign':
        if cols[0] == 9 and cols[1] >= 0 and cols[2] >= 0 and min(cols[3:6]) >= 0:
            prov = ALPHABET[cols[1]] + ALPHABET[cols[2]]
            ctry = '%d%d%d' % (cols[3], cols[4], cols[5])
            key = (prov, ctry)
            hit = CACHE_DIV.get(key)
            if hit is None:
                hit = bool(admin.provinces.get(prov)) and countries.name(ctry) is not None
                CACHE_DIV[key] = hit
            div_ok = hit
            level = 2 if hit else 0
    elif min(cols[0:6]) >= 0:
        code = (cols[0] * 100000 + cols[1] * 10000 + cols[2] * 1000 +
                cols[3] * 100 + cols[4] * 10 + cols[5])
        key = (code, y)
        hit = CACHE_DIV.get(key)
        if hit is None:
            ok, _name, _note, lv = admin.lookup('%06d' % code, y)
            hit = (ok, lv)
            CACHE_DIV[key] = hit
        div_ok, level = hit
    return div_ok, level, date_ok, seq_ok, sexbit, y


def analyse(cols, admin, countries, kind):
    """完整判定（含文字），给最终展示用。"""
    info = Info()
    info.kind = kind
    info.checksum = checksum_of(cols)
    if info.checksum and len(cols) > 17 and cols[17] >= 0:
        info.cs_ok = cols[17] == IDX[info.checksum]
    date = parse_date(cols[6:14])
    if date:
        y, m, d = date
        info.birth_year = y
        info.date = '%04d-%02d-%02d' % (y, m, d)
        info.date_ok = date_plausible(y, m, d)
        if not info.date_ok:
            info.date_note = '超出现实范围' if valid_date(y, m, d) else '无效日期'
    year = info.birth_year
    if kind == 'foreign':
        if cols[0] != 9:
            info.div_note = '外国人永居证首位应为 9'
        elif cols[1] < 0 or cols[2] < 0:
            info.div_note = '申领地代码含缺位'
        else:
            prov = ALPHABET[cols[1]] + ALPHABET[cols[2]]
            info.province = prov
            pname = admin.provinces.get(prov)
            if min(cols[3:6]) >= 0:
                ctry = '%d%d%d' % (cols[3], cols[4], cols[5])
                info.country = ctry
                cname = countries.name(ctry)
                info.country_ok = cname is not None
                info.div_ok = bool(pname) and info.country_ok
                info.div_name = '%s · %s' % (pname or '申领地 %s 未知' % prov,
                                             cname or '国籍代码 %s 未知' % ctry)
                info.div_note = '外国人永居证'
            else:
                info.div_note = '国籍代码含缺位'
    else:
        if min(cols[0:6]) >= 0:
            code = ''.join(ALPHABET[c] for c in cols[0:6])
            info.addr = code
            ok, name, note, level = admin.lookup(code, year)
            info.div_ok = ok
            info.div_name = name
            info.div_note = note
            info.div_level = level
        else:
            info.div_note = '地址码含缺位'
    if min(cols[14:17]) >= 0 and max(cols[14:17]) <= 9:
        info.seq_ok = True
        info.sex = '男' if cols[16] % 2 == 1 else '女'
    return info


# 结构先验（相对权重）
W_DIV = 4.0            # 区划命中
W_DATE = 2.0           # 出生日期合理
W_SEQ = 1.0            # 顺序码完整
W_BAD = 0.04           # 任一项不成立
W_YEAR_EDGE = 0.5      # 代码恰在启用年/废止年：过渡期仍可能出现
DEFAULT_P_FOREIGN = 0.02


class Priors:
    def __init__(self, p_foreign=DEFAULT_P_FOREIGN, gender='未知', foreign='未知'):
        self.p_foreign = p_foreign
        self.gender = gender
        self.foreign = foreign
        if foreign == '是':
            self.kinds = ('foreign',)
        elif foreign == '否':
            self.kinds = ('citizen',)
        else:
            self.kinds = ('citizen', 'foreign')

    def kind_weight(self, kind):
        f = self.p_foreign
        if self.foreign == '是':
            return 1.0 if kind == 'foreign' else 0.0
        if self.foreign == '否':
            return 1.0 if kind == 'citizen' else 0.0
        return f if kind == 'foreign' else (1.0 - f)

    def logflags(self, flags, kind):
        """flags = fast_flags() 的返回值。"""
        div_ok, level, date_ok, seq_ok, sexbit, _year = flags
        w = 1.0
        if div_ok:
            w *= W_DIV
            if level == 1:
                w *= W_YEAR_EDGE
            elif level == 0:
                w *= W_BAD
        else:
            w *= W_BAD
        w *= W_DATE if date_ok else W_BAD
        w *= W_SEQ if seq_ok else W_BAD
        w *= self.kind_weight(kind)
        if self.gender != '未知' and sexbit >= 0:
            w *= 1.0 if sexbit == (1 if self.gender == '男' else 0) else 0.02
        return slog(w)


# ---------------------------------------------------------------------------
# 读数枚举
# ---------------------------------------------------------------------------
# 一个“读数”= 把输入串解释成一条 18 位号码。允许的局部改动：
#   原样  该字符就是号码该位的字符        替换  该位实际是别的字符（10 种可能）
#   插入  多写了一位                      删除  漏写了一位
#   换位  与相邻位顺序颠倒                合并  两位粘成一位（读作前者或后者）
#   缺位  输入里是空格（看不清），该位取任意值
#
# 概率模型（对数）：p = 每位抄对的概率（默认 0.97）
#   原样 log p；替换 log((1−p)/10)；插入 log q_ins；删除 log q_del；
#   换位 log q_swap；合并 log q_merge；缺位 log q_blank。
# 结构先验另行相乘。校验码不参与读数概率，而是决定候选号码如何组成。

DEFAULT_P = 0.97
Q_INS = 0.010
Q_DEL = 0.010
Q_SWAP = 0.020
Q_MERGE = 0.020
Q_BLANK = 0.030

K_SUB, K_INS, K_DEL, K_SWAP, K_MERGE = 0, 1, 2, 3, 4


class Costs:
    def __init__(self, p=DEFAULT_P, q_ins=Q_INS, q_del=Q_DEL, q_swap=Q_SWAP,
                 q_merge=Q_MERGE, q_blank=Q_BLANK):
        self.p = p
        self.log_p = slog(p)
        self.log_sub = slog((1.0 - p) / 10.0)
        self.log_ins = slog(q_ins)
        self.log_del = slog(q_del)
        self.log_swap = slog(q_swap)
        self.log_merge = slog(q_merge)
        self.log_blank = slog(q_blank)


def enumerate_readings(s, costs, max_edits=2, min_len=6, allowed=None):
    """枚举读数。yield (cols, edits, edit_ops, logw)。

    cols     : tuple，长度 6..18，元素 0..10 或 -1（缺位）
    edits    : 局部改动组数
    edit_ops : tuple[(kind, col0based, old_text, new_text)]
    logw     : 读数概率对数
    """
    n = len(s)
    codes = [-1 if ch == ' ' else IDX[ch] for ch in s]
    lp = costs.log_p
    stack = [(0, 0, (), 0, 0.0, ())]
    push = stack.append
    pop = stack.pop
    while stack:
        pos, col, cols, edits, lw, ops = pop()
        if pos == n:
            if col >= min_len:
                yield cols, edits, ops, lw
            continue
        ci = codes[pos]
        ch = s[pos]
        if ci < 0:
            push((pos + 1, col + 1, cols + (-1,), edits, lw + costs.log_blank, ops))
            continue
        # 原样
        push((pos + 1, col + 1, cols + (ci,), edits, lw + lp, ops))
        if edits >= max_edits or col >= 18:
            continue
        if allowed is not None and col not in allowed:
            continue
        if pos + 1 < n and codes[pos + 1] >= 0:
            ni = codes[pos + 1]
            two = s[pos] + s[pos + 1]
            if ni != ci:
                push((pos + 2, col + 2, cols + (ni, ci), edits + 1,
                      lw + costs.log_swap,
                      ops + ((K_SWAP, col, two, two[::-1]),)))
            push((pos + 2, col + 1, cols + (ci,), edits + 1,
                  lw + costs.log_merge, ops + ((K_MERGE, col, two, ch),)))
            push((pos + 2, col + 1, cols + (ni,), edits + 1,
                  lw + costs.log_merge, ops + ((K_MERGE, col, two, s[pos + 1]),)))
        # 替换
        for c in range(N_CHARS):
            if c != ci:
                push((pos + 1, col + 1, cols + (c,), edits + 1,
                      lw + costs.log_sub, ops + ((K_SUB, col, ch, ALPHABET[c]),)))
        # 插入（新字占 col，原字顺延）
        if col < 17:
            for c in range(N_CHARS):
                if c != ci:
                    push((pos + 1, col + 2, cols + (c, ci), edits + 1,
                          lw + costs.log_ins,
                          ops + ((K_INS, col, '', ALPHABET[c]),)))
        # 删除
        push((pos + 1, col, cols, edits + 1, lw + costs.log_del,
              ops + ((K_DEL, col, ch, ''),)))
    del stack


# ---------------------------------------------------------------------------
# 候选号码
# ---------------------------------------------------------------------------
# 由读数生成号码：
#   * 前缀（第 1–17 列）若有 k 个缺位，需填 11^k 种；填好后校验位由公式决定，
#     故候选数 = 11^k（不是 11^(k+1)）。k ≥ 3 不展开。
#   * 读数若已给出第 18 列且与公式不符，就把第 18 位改成公式值并记 1 次替换——
#     这是“校验位抄错”这一解释；“前缀某位抄错”由另一个读数覆盖。

MAX_FILL = 2
MIN_LOGW = -60.0        # 相对最高权重低于 e^-60 的候选丢弃


class Analysis:
    def __init__(self):
        self.raw = ''
        self.clean = ''
        self.notes = []
        self.cands = []
        self.total = 0.0
        self.columns = []
        self.elapsed = 0.0
        self.readings = 0
        self.best = 0.0


def analyze(text, admin, countries, priors=None, p=DEFAULT_P, max_edits=2,
            top_columns=4, suspect=None):
    t0 = time.perf_counter()
    priors = priors or Priors()
    res = Analysis()
    res.raw = text
    s, notes = sanitize(text)
    res.clean = s
    res.notes = notes
    if not s:
        res.notes.append('输入里没有可用的号码字符')
        return res
    costs = Costs(p=p)
    # 公民身份号码的省级代码不含 90–99，首位见 9 基本只有永居证一种可能
    if s[0] == '9' and priors.foreign == '未知':
        priors = Priors(p_foreign=0.9, gender=priors.gender, foreign='未知')
        res.notes.append('首位为 9：公民身份号码的省级代码不以 9 开头，按外国人永居证核验')
    cands = {}
    readings = 0
    kinds = priors.kinds
    allowed = None
    if suspect:
        tmp = set()
        for k in suspect:
            tmp.add(k - 1)
            tmp.add(k)
        allowed = frozenset(c for c in tmp if 0 <= c < 18)
    for cols, edits, ops, lw in enumerate_readings(s, costs, max_edits=max_edits,
                                                   allowed=allowed):
        readings += 1
        n = len(cols)
        if n > 18:
            continue                      # 多出的位说明还得多删一位，不是号码本身
        blanks = [i for i in range(min(n, 17)) if cols[i] < 0]
        if len(blanks) > MAX_FILL:
            continue
        combos = N_CHARS ** len(blanks)
        for t in range(combos):
            cur = list(cols) + [-1] * (18 - n)
            v = t
            for i in blanks:
                cur[i] = v % N_CHARS
                v //= N_CHARS
            cs = checksum_of(cur)
            if not cs:
                continue
            extra = 0
            extra_ops = ()
            csi = IDX[cs]
            if n == 18 and cols[17] >= 0 and cols[17] != csi:
                extra = 1
                extra_ops = ((K_SUB, 17, ALPHABET[cols[17]], cs),)
            cur[17] = csi
            # X 只可能出现在第 18 位：前 17 位出现 X 的候选直接不成立
            if -1 in cur or max(cur[:17]) > 9:
                continue
            tup = tuple(cur)
            number = ''.join(ALPHABET[c] for c in tup)
            base_w = lw + costs.log_sub * extra
            for kind in kinds:
                flags = fast_flags(tup, admin, countries, kind)
                w = base_w + priors.logflags(flags, kind)
                old = cands.get(number)
                if old is None or w > old[0] or (w == old[0] and edits < old[1]):
                    cands[number] = [w, edits + extra, ops + extra_ops, kind, tup]
    res.readings = readings
    if not cands:
        res.notes.append('没有能构成合法号码的读数（可提高 --edits 或调整 --p）')
        return res
    best = max(v[0] for v in cands.values())
    res.best = best
    items = [(num, v) for num, v in cands.items() if v[0] >= best + MIN_LOGW]
    items.sort(key=lambda kv: (-kv[1][0], kv[1][1]))
    # 只给展示用的前若干个候选补上文字描述
    for num, v in items[:200]:
        v.append(analyse(v[4], admin, countries, v[3]))
    res.cands = items
    res.total = sum(math.exp(v[0] - best) for _, v in items)
    # 逐位统计
    hist = [dict() for _ in range(18)]
    seen = [0.0] * 18
    for num, v in items:
        w = math.exp(v[0] - best)
        for i in range(18):
            c = IDX[num[i]] if i < len(num) else -1
            if c < 0:
                continue
            h = hist[i]
            h[c] = h.get(c, 0.0) + w
            seen[i] += w
    cols_out = []
    for i in range(18):
        if seen[i] <= 0.0:
            cols_out.append([])
            continue
        ranked = sorted(hist[i].items(), key=lambda kv: -kv[1])[:top_columns]
        cols_out.append([(ALPHABET[c], w / seen[i]) for c, w in ranked])
    res.columns = cols_out
    res.elapsed = time.perf_counter() - t0
    return res


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

OP_TEXT = {
    K_SUB: '第%(a)d位 %(old)s→%(new)s',
    K_INS: '第%(a)d位漏抄 %(new)s（应补一位）',
    K_DEL: '第%(a)d位多抄 %(old)s（应删去）',
    K_SWAP: '第%(a)d、%(b)d位颠倒 %(old)s→%(new)s',
    K_MERGE: '第%(a)d位“%(old)s”粘连读作%(new)s',
}


def op_text(op):
    kind, col, old, new = op
    return OP_TEXT[kind] % {'a': col + 1, 'b': col + 2, 'old': old, 'new': new}


def ops_text(ops):
    return '；'.join(op_text(o) for o in ops) if ops else '—'


def fmt_pct(x):
    if x >= 0.9995:
        return '100%'
    if x < 0.0005:
        return '<0.1%'
    return '%.1f%%' % (x * 100.0)


def align_marks(clean, number):
    """等长时标出与输入不同的位。"""
    if len(clean) != len(number):
        return number, ''
    marks = ''.join('^' if a != b else ' ' for a, b in zip(clean, number))
    return number, marks


SEG_NAME = ['地址码'] * 6 + ['出生日期'] * 8 + ['顺序码'] * 3 + ['校验码']


def cand_info(v, admin, countries):
    """取候选的 Info（前 200 名已在 analyze 里补好，其余按需生成）。"""
    if len(v) > 5:
        return v[5]
    return analyse(v[4], admin, countries, v[3])


def heading(info, admin, countries):
    """一句话结论：区划 · 出生 · 性别 · 校验。"""
    div = info.div_name if info.div_ok else (info.div_note or '区划未知')
    when = info.date if info.date_ok else (info.date_note or '出生日期未知')
    sex = info.sex or '性别未知'
    cs = '校验码正确' if info.cs_ok else '校验码不符'
    return '%s · %s · %s · %s' % (div, when, sex, cs)


def render(res, admin, countries, top=10):
    L = []
    add = L.append
    add('输入  %s' % res.raw.strip())
    add('识别  %s' % (res.clean or '（空）'))
    for note in res.notes:
        add('说明  %s' % note)
    if not res.cands:
        add('')
        add('没有找到合法候选。')
        return '\n'.join(L)
    add('读数  %d 种错位解释 → %d 个候选号码，用时 %.2f s'
        % (res.readings, len(res.cands), res.elapsed))
    best_num, best_v = res.cands[0]
    best_info = cand_info(best_v, admin, countries)
    add('')
    add('最可能  %s   %s' % (best_num,
                             fmt_pct(math.exp(best_v[0] - res.best) / res.total)))
    add('        %s' % heading(best_info, admin, countries))
    add('        改动：%s' % ops_text(best_v[2]))
    if not best_info.div_ok and not best_info.date_ok:
        add('!!      连最可能的候选都“区划未知 + 出生日期不合法”：这份号码可能不是'
            '身份证号码，或错位超过了 --edits 允许的范围')
    elif not best_info.div_ok:
        add('!!      最可能的候选区划未命中（区划未知），请核对前 6 位')
    add('')
    add('候选号码（按可能性排序；^ 标出与输入不同的位）')
    add('%-3s %-18s %-6s %-3s %-22s %-11s %-2s %s'
        % ('#', '号码', '概率', '改', '区划 / 国籍', '出生日期', '性', '改动说明'))
    for i, (num, v) in enumerate(res.cands[:top], 1):
        info = cand_info(v, admin, countries)
        p = math.exp(v[0] - res.best) / res.total
        div = info.div_name if info.div_ok else (info.div_note or '未知')
        if info.div_ok and info.div_level == 1:
            div += '*'
        date = info.date if info.date_ok else '—'
        shown, marks = align_marks(res.clean, num)
        add('%-3d %-18s %-6s %-3d %-22s %-11s %-2s %s'
            % (i, shown, fmt_pct(p), v[1], div[:22], date, info.sex or '?',
               ops_text(v[2])))
        if marks.strip():
            add('%-3s %-18s' % ('', marks))
    add('  （号码不合法时显示 —；区划名后带 * 表示该代码只在启用/废止当年可能）')
    add('')
    add('逐位候选（概率 = 该位上各候选字符在全部候选号码中的占比）')
    add('位   输入  候选字符（占比）')
    for i, ent in enumerate(res.columns):
        if not ent:
            continue
        src = res.clean[i] if i < len(res.clean) else ' '
        txt = '   '.join('%s %s' % (ch, fmt_pct(q)) for ch, q in ent)
        add('%-4d %-5s %s   〔%s〕' % (i + 1, src, txt, SEG_NAME[i]))
    return '\n'.join(L)


def to_json(res, admin, countries):
    best = res.best
    out = []
    for num, v in res.cands[:50]:
        info = cand_info(v, admin, countries)
        out.append({
            'number': num,
            'probability': round(math.exp(v[0] - best) / res.total, 6),
            'edits': v[1],
            'kind': v[3],
            'address': info.div_name if info.div_ok else None,
            'address_note': info.div_note,
            'birth': info.date,
            'birth_ok': info.date_ok,
            'sex': info.sex,
            'changes': [op_text(o) for o in v[2]],
        })
    return {
        'input': res.raw,
        'clean': res.clean,
        'notes': res.notes,
        'readings': res.readings,
        'elapsed': round(res.elapsed, 4),
        'candidates': out,
        'columns': [
            [{'char': ch, 'share': round(q, 6)} for ch, q in ent]
            for ent in res.columns
        ],
    }


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def do_check(text, admin, countries):
    s, notes = sanitize(text)
    out = {'input': text, 'clean': s, 'notes': notes, 'ok': False}
    if len(s) != 18 or ' ' in s:
        out['error'] = '号码不是标准 18 位（当前 %d 位%s）' % (
            len(s), '，含缺位' if ' ' in s else '')
        return out
    if not all(ch in ALPHABET for ch in s):
        out['error'] = '含非法字符'
        return out
    cols = tuple(IDX[c] for c in s)
    kind = 'foreign' if s[0] == '9' else 'citizen'
    info = analyse(cols, admin, countries, kind)
    out['kind'] = kind
    out['checksum'] = {'expected': info.checksum, 'got': s[17], 'ok': info.cs_ok}
    if kind == 'foreign':
        out['address'] = {'form': '外国人永久居留身份证',
                          'province': s[1:3], 'country_code': s[3:6],
                          'hit': info.div_ok, 'name': info.div_name,
                          'note': info.div_note}
    else:
        out['address'] = {'code': s[:6], 'hit': info.div_ok, 'name': info.div_name,
                          'note': info.div_note}
    out['birth'] = {'value': info.date, 'ok': info.date_ok, 'note': info.date_note}
    out['sequence'] = {'value': s[14:17], 'ok': info.seq_ok, 'sex': info.sex}
    out['ok'] = bool(info.cs_ok and info.div_ok and info.date_ok and info.seq_ok)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog='idcheck', description='身份证号码校验、错位诊断与区划代码反推')
    p.add_argument('--version', action='version', version='idcheck ' + VERSION)
    sub = p.add_subparsers(dest='cmd')

    c = sub.add_parser('check', help='严格校验一个 18 位号码')
    c.add_argument('number')

    sub.add_parser('demo', help='内置样例演示')

    a = sub.add_parser('analyze', help='手抄号码：错位识别 + 候选反推')
    a.add_argument('number', nargs='*',
                   help='号码；含空格时请加引号，或直接分几段给出（空格表示该位看不清）')
    a.add_argument('--stdin', action='store_true', help='逐行读取号码')
    a.add_argument('--json', action='store_true', help='输出 JSON')
    a.add_argument('--top', type=int, default=10, help='显示前 N 个候选（默认 10）')
    a.add_argument('--edits', type=int, default=2,
                   help='最多允许几处局部改动（默认 2；3 明显变慢）')
    a.add_argument('--p', type=float, default=DEFAULT_P,
                   help='每位抄对的概率（默认 %.2f）' % DEFAULT_P)
    a.add_argument('--gender', choices=['男', '女', '未知'], default='未知',
                   help='输入者提供的性别')
    a.add_argument('--foreign', choices=['是', '否', '未知'], default='未知',
                   help='是否为外国人永久居留身份证')
    a.add_argument('--p-foreign', type=float, default=DEFAULT_P_FOREIGN,
                   help='事先认为对象是外国人的概率（默认 %.2f）'
                        % DEFAULT_P_FOREIGN)
    a.add_argument('--suspect', default='',
                   help='输入者指出可疑的位（1 起，逗号分隔，如 15,16）；'
                        '给出后只在这些位附近找错位，速度与准确度都更好')
    return p


def parse_positions(text):
    out = []
    for part in text.replace('，', ',').replace(' ', ',').split(','):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def cmd_demo(admin, countries):
    samples = [
        '11010219840406970X',
        '11010219840406970 8',
        '1101021984O40697OX',
        '110102198404O6970X',
        '910000198404069008',
    ]
    for s in samples:
        print('=' * 104)
        print(render(analyze(s, admin, countries), admin, countries))


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    admin = load_tables()
    countries = load_countries()
    if args.cmd == 'check':
        out = do_check(args.number, admin, countries)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get('ok') else 1
    if args.cmd in (None, 'demo'):
        cmd_demo(admin, countries)
        return 0
    if args.cmd == 'analyze':
        priors = Priors(p_foreign=args.p_foreign, gender=args.gender,
                        foreign=args.foreign)
        suspect = parse_positions(args.suspect)
        if args.stdin:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                res = analyze(line, admin, countries, priors=priors, p=args.p,
                              max_edits=args.edits, suspect=suspect)
                print(render(res, admin, countries, top=args.top) if not args.json
                      else json.dumps(to_json(res, admin, countries), ensure_ascii=False, indent=2))
                print()
            return 0
        if not args.number:
            parser.error('analyze 需要号码，或用 --stdin')
        text = ' '.join(args.number)
        res = analyze(text, admin, countries, priors=priors, p=args.p,
                      max_edits=args.edits, suspect=suspect)
        print(render(res, admin, countries, top=args.top) if not args.json
              else json.dumps(to_json(res, admin, countries), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    # 管道/重定向时 Windows 默认按 GBK 解码，中文与 BOM 都会变乱码；号码是 ASCII，
    # 统一按 UTF-8 读不会影响键盘输入。
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
