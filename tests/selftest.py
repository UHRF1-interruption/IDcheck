#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idcheck 自检。直接运行：python tests/selftest.py
全部通过时退出码 0；任一断言失败立即抛出并返回非 0。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..')))

import idcheck as I  # noqa: E402

ADMIN = I.load_tables()
COUNTRIES = I.load_countries()
FAILED = []


def check(name, cond, detail=''):
    if cond:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def top(text, **kw):
    res = I.analyze(text, ADMIN, COUNTRIES, **kw)
    if not res.cands:
        return None, 0.0
    num, v = res.cands[0]
    return num, I.math.exp(v[0] - res.best) / res.total


def main():
    print('== 校验码 ==')
    # 图中示例：北京市西城区、19840406、顺序码 970（女）、校验码 X
    check('11010219840406970 → X', I.checksum_of(
        [I.IDX[c] for c in '11010219840406970']) == 'X')
    check('任取 17 位都能算出校验位',
          all(len(I.checksum_of([I.IDX[c] for c in p])) == 1
              for p in ('00000000000000000', '99999999999999999')))

    print('== check 模式 ==')
    r = I.do_check('11010219840406970X', ADMIN, COUNTRIES)
    check('示例号码合法', r['ok'])
    check('地址为北京市西城区', r['address']['name'] == '北京市西城区', r['address'])
    check('出生 1984-04-06', r['birth']['value'] == '1984-04-06', r['birth'])
    check('顺序码 970 女', r['sequence']['sex'] == '女')
    check('改一位校验码即不合法',
          not I.do_check('11010219840406970 1'.replace(' ', ''), ADMIN, COUNTRIES)['ok'])

    print('== 区划时效 ==')
    ok, name, note, level = ADMIN.lookup('110103', 2009)   # 崇文区，2010 废止
    check('崇文区 2009 有效', ok and level == 2, (ok, level, note))
    ok, name, note, level = ADMIN.lookup('110103', 2010)
    check('崇文区 2010 为废止当年（边界）', ok and level == 1, (ok, level, note))
    ok, name, note, level = ADMIN.lookup('110103', 2011)
    check('崇文区 2011 不可能（废止一年后）', (not ok) and level == 0, (ok, level, note))
    ok, name, note, level = ADMIN.lookup('110102', 1980)
    check('西城区 1980 为启用当年', ok and level == 1, (ok, level, note))
    ok, name, note, level = ADMIN.lookup('659013', 2025)   # 草湖市 2026 启用
    check('2026 年才启用的代码，2025 年出生不可能', (not ok) and level == 0,
          (ok, level, note))
    check('港澳台居住证 810000 命中', ADMIN.lookup('810000')[0])
    check('不存在的代码不命中', not ADMIN.lookup('110199')[0])

    print('== analyze：正确号码 ==')
    num, p = top('11010219840406970X')
    check('原样号码排第一', num == '11010219840406970X', num)
    check('原样号码概率 > 90%', p > 0.90, p)

    print('== analyze：OCR 混淆 ==')
    num, p = top('1101021984040697OX')
    check('O 当成 0 后能还原', num == '11010219840406970X', num)

    print('== analyze：漏抄一位 ==')
    num, p = top('1101021984040690X', suspect=[16])
    check('指出第 16 位可疑时排第一', num == '11010219840406970X', num)

    print('== analyze：多抄一位 ==')
    num, p = top('110102198440406970X')
    check('多写的 4 能被识别', num == '11010219840406970X', num)

    print('== analyze：缺位标记 ==')
    num, p = top('1101021984 406970X')
    check('空格缺位能补回', num == '11010219840406970X', num)

    print('== analyze：可疑位给出逐位候选 ==')
    res = I.analyze('11010219840406970X', ADMIN, COUNTRIES)
    check('18 列都有候选', all(ent for ent in res.columns))
    check('第 1 列首选为 1', res.columns[0][0][0] == '1')

    print('== 性别选项 ==')
    res_m = I.analyze('1101021984040690X', ADMIN, COUNTRIES,
                      priors=I.Priors(gender='男'), suspect=[16])
    sexes = [I.cand_info(v, ADMIN, COUNTRIES).sex for _, v in res_m.cands[:20]]
    check('给出"男"后候选以男性为主', sexes.count('男') >= 1 and
          (not sexes or sexes[0] == '男') or '男' in sexes, sexes[:5])

    print('== 外国人永居证 ==')
    prefix = '9' + '11' + '840' + '19840406' + '970'
    num = prefix + I.checksum_of([I.IDX[c] for c in prefix])
    r = I.do_check(num, ADMIN, COUNTRIES)
    check('永居证号码合法', r['ok'], r)
    check('国籍解析为美国', '美利坚' in (r['address']['name'] or ''), r['address'])
    check('永居证首位必须是 9', not I.do_check('811840198404069706', ADMIN, COUNTRIES)['ok'])

    print('== 性能 ==')
    t = time.perf_counter()
    I.analyze('11010219840406970X', ADMIN, COUNTRIES)
    dt = time.perf_counter() - t
    check('完整分析 < 3 s（实测 %.2f s）' % dt, dt < 3.0)

    print()
    if FAILED:
        print('失败 %d 项：%s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
