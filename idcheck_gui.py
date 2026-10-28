# -*- coding: utf-8 -*-
"""
idcheck 的图形界面（标准库 tkinter，无第三方依赖）。

要点
  * 分析要跑 1–3 秒，放到后台线程；线程只往队列里放结果，界面用 after() 轮询，
    避免跨线程操作 Tk（那是 tkinter 最常见的崩法）；
  * 候选号码用 Treeview 做成真正的表格列，不会因为全角/半角而不对齐；
  * 双击 exe 时 FreeConsole()，只留一个窗口；异常写到 exe 旁边的 idcheck-gui.log，
    并弹窗提示，绝不静默退出；
  * 设 IDCHECK_GUI_SELFTEST=<号码> 可在无人工操作下自检：自动分析、输出结果后退出。
"""

import os
import queue
import sys
import threading
import traceback

import idcheck as core

TITLE = ('idcheck %s（build %s）—— 身份证号码校验 / 错位诊断 / 区划反推'
         % (core.VERSION, core.BUILD))

HINT = ('直接粘贴或输入 18 位号码后按回车；看不清的位用空格或 ? 代替。'
        '例：1101021984 406970X')

COLS = [
    ('no', '#', 40, 'center'),
    ('num', '号码', 170, 'w'),
    ('p', '概率', 70, 'e'),
    ('edits', '改动', 50, 'center'),
    ('div', '区划 / 国籍', 240, 'w'),
    ('date', '出生日期', 100, 'w'),
    ('sex', '性别', 50, 'center'),
    ('ops', '改动说明', 420, 'w'),
]

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.executable
                                                        if getattr(sys, 'frozen', False)
                                                        else __file__)),
                        'idcheck-gui.log')


def _log(text):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(text.rstrip() + '\n')
    except Exception:
        pass


def _hide_console():
    """双击启动时隐藏附带的控制台黑窗口（不 FreeConsole，以免打断父进程）。"""
    core.hide_own_console()


class App:
    def __init__(self, root, admin, countries):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.admin = admin
        self.countries = countries
        self.q = queue.Queue()
        self.busy = False

        root.title(TITLE)
        root.geometry('1140x800')
        root.minsize(920, 620)

        top = ttk.Frame(root, padding=(12, 10, 12, 4))
        top.pack(fill='x')
        ttk.Label(top, text='号码', font=('Microsoft YaHei UI', 11)).grid(
            row=0, column=0, sticky='w')
        self.var_num = tk.StringVar()
        self.entry = ttk.Entry(top, textvariable=self.var_num,
                               font=('Consolas', 15))
        self.entry.grid(row=0, column=1, columnspan=7, sticky='we',
                        padx=(8, 8), ipady=3)

        ttk.Label(top, text='性别').grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.var_gender = tk.StringVar(value='未知')
        ttk.Combobox(top, textvariable=self.var_gender, width=6,
                     state='readonly', values=('未知', '男', '女')).grid(
            row=1, column=1, sticky='w', padx=(8, 16), pady=(8, 0))

        ttk.Label(top, text='外国人').grid(row=1, column=2, sticky='w', pady=(8, 0))
        self.var_foreign = tk.StringVar(value='未知')
        ttk.Combobox(top, textvariable=self.var_foreign, width=6,
                     state='readonly', values=('未知', '是', '否')).grid(
            row=1, column=3, sticky='w', padx=(8, 16), pady=(8, 0))

        ttk.Label(top, text='可疑位').grid(row=1, column=4, sticky='w', pady=(8, 0))
        self.var_suspect = tk.StringVar()
        self.e_suspect = ttk.Entry(top, textvariable=self.var_suspect, width=12)
        self.e_suspect.grid(row=1, column=5, sticky='w', padx=(8, 16), pady=(8, 0))

        ttk.Label(top, text='允许改动').grid(row=1, column=6, sticky='w', pady=(8, 0))
        self.var_edits = tk.IntVar(value=2)
        ttk.Spinbox(top, from_=1, to=3, width=4, textvariable=self.var_edits).grid(
            row=1, column=7, sticky='w', padx=(8, 0), pady=(8, 0))

        top.columnconfigure(1, weight=1)
        ttk.Label(top, text=HINT, foreground='#666').grid(
            row=2, column=0, columnspan=8, sticky='w', pady=(8, 0))

        bar = ttk.Frame(root, padding=(12, 6, 12, 6))
        bar.pack(fill='x')
        self.btn_analyze = ttk.Button(bar, text='分析（回车）', width=16,
                                      command=self.do_analyze)
        self.btn_analyze.pack(side='left')
        ttk.Button(bar, text='严格校验', width=12, command=self.do_check).pack(
            side='left', padx=(8, 0))
        ttk.Button(bar, text='清空', width=8, command=self.do_clear).pack(
            side='left', padx=(8, 0))
        ttk.Button(bar, text='填入示例', width=10,
                   command=self.do_sample).pack(side='left', padx=(8, 0))
        self.var_status = tk.StringVar(value='就绪')
        ttk.Label(bar, textvariable=self.var_status, foreground='#444').pack(
            side='left', padx=(16, 0))

        self.var_head = tk.StringVar(value=(
            '把号码粘贴到上面的输入框，按回车（或点"分析"）开始。\n'
            '示例：1101021984 406970X  —— 中间的空格表示"这一位看不清"。'))
        ttk.Label(root, textvariable=self.var_head,
                  font=('Microsoft YaHei UI', 11, 'bold'),
                  padding=(14, 2, 14, 8), wraplength=1090,
                  justify='left').pack(fill='x')

        table_frame = ttk.Frame(root, padding=(12, 0, 12, 0))
        table_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table_frame,
                                 columns=[c[0] for c in COLS],
                                 show='headings', height=9)
        for key, title, width, anchor in COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == 'ops'))
        ysb = ttk.Scrollbar(table_frame, orient='vertical',
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        ysb.pack(side='right', fill='y')
        self.tree.tag_configure('best', background='#eaf3ff')

        bottom = ttk.LabelFrame(root, text='逐位候选（该位可能是什么）',
                                padding=(8, 4))
        bottom.pack(fill='both', expand=False, padx=12, pady=(8, 8))
        self.txt = tk.Text(bottom, height=10, wrap='none', font=('SimSun', 10),
                           state='disabled')
        xsb = ttk.Scrollbar(bottom, orient='horizontal', command=self.txt.xview)
        self.txt.configure(xscrollcommand=xsb.set)
        self.txt.pack(fill='both', expand=True)
        xsb.pack(fill='x')

        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        self.entry.bind('<Return>', self.do_analyze)
        self.e_suspect.bind('<Return>', self.do_analyze)
        root.bind('<Control-Return>', self.do_analyze)
        root.bind('<Escape>', lambda e: root.destroy())
        self.entry.focus_set()
        try:
            root.update_idletasks()
            root.deiconify()
            root.lift()
            root.attributes('-topmost', True)
            root.after(400, lambda: root.attributes('-topmost', False))
        except Exception:
            pass
        self.root.after(100, self.poll)

    # ---------- 线程 → 界面 ----------
    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'ok':
                    self.finish(payload)
                else:
                    self.fail(payload)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_status(self, msg):
        self.var_status.set(msg)

    def do_analyze(self, *_):
        if self.busy:
            return
        text = self.var_num.get().strip()
        if not text:
            self.set_status('请先输入号码')
            self.entry.focus_set()
            return
        self.busy = True
        self.btn_analyze.state(['disabled'])
        self.set_status('分析中…（最多几秒）')
        kwargs = dict(
            priors=core.Priors(gender=self.var_gender.get(),
                               foreign=self.var_foreign.get()),
            max_edits=max(1, min(3, int(self.var_edits.get() or 2))),
            suspect=core.parse_positions(self.var_suspect.get()))
        admin, countries, q = self.admin, self.countries, self.q

        def work():
            try:
                res = core.analyze(text, admin, countries, **kwargs)
                q.put(('ok', res))
            except Exception:
                q.put(('err', traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def fail(self, err):
        self.busy = False
        self.btn_analyze.state(['!disabled'])
        self.set_status('出错')
        _log(err)
        try:
            from tkinter import messagebox
            messagebox.showerror('分析出错', err[-1200:])
        except Exception:
            pass

    # ---------- 展示 ----------
    def finish(self, res):
        self.busy = False
        self.btn_analyze.state(['!disabled'])
        self.tree.delete(*self.tree.get_children())
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        if not res.cands:
            self.var_head.set('没有找到合法候选')
            for note in res.notes:
                self.txt.insert('end', '说明：%s\n' % note)
            self.txt.configure(state='disabled')
            self.set_status('完成：0 个候选')
            return
        best_num, best_v = res.cands[0]
        info = core.cand_info(best_v, self.admin, self.countries)
        head = ('最可能  %s   %s\n%s\n改动：%s'
                % (best_num,
                   core.fmt_pct(core.math.exp(best_v[0] - res.best) / res.total),
                   core.heading(info, self.admin, self.countries),
                   core.ops_text(best_v[2])))
        if not info.div_ok and not info.date_ok:
            head += ('\n!! 连最可能的候选都“区划未知 + 出生日期不合法”，'
                     '这份号码可能不是身份证号码')
        self.var_head.set(head)
        for i, (num, v) in enumerate(res.cands):
            inf = core.cand_info(v, self.admin, self.countries)
            p = core.math.exp(v[0] - res.best) / res.total
            div = inf.div_name if inf.div_ok else (inf.div_note or '未知')
            if inf.div_ok and inf.div_level == 1:
                div += '*'
            date = inf.date if inf.date_ok else '—'
            self.tree.insert('', 'end', values=(
                i + 1, num, core.fmt_pct(p), v[1], div, date,
                inf.sex or '?', core.ops_text(v[2])),
                tags=('best',) if i == 0 else ())
        for i, ent in enumerate(res.columns):
            if not ent:
                continue
            src = res.clean[i] if i < len(res.clean) else ' '
            self.txt.insert('end', '第%2d位  %s  %s   〔%s〕\n'
                            % (i + 1, src,
                               '   '.join('%s %s' % (ch, core.fmt_pct(q2))
                                          for ch, q2 in ent),
                               core.SEG_NAME[i]))
        for note in res.notes:
            self.txt.insert('end', '说明：%s\n' % note)
        self.txt.configure(state='disabled')
        self.set_status('完成：%d 种读数解释，%d 个候选，用时 %.2f s'
                        % (res.readings, len(res.cands), res.elapsed))

    def do_check(self, *_):
        text = self.var_num.get().strip()
        if not text:
            self.set_status('请先输入号码')
            return
        out = core.do_check(text, self.admin, self.countries)
        self.tree.delete(*self.tree.get_children())
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.insert('end', core.json.dumps(out, ensure_ascii=False, indent=2))
        self.txt.configure(state='disabled')
        self.var_head.set('严格校验：%s' % ('合法' if out.get('ok') else '不合法'))
        self.set_status('就绪')

    def do_sample(self):
        self.var_num.set('1101021984 406970X')
        self.entry.focus_set()
        self.do_analyze()

    def do_clear(self):
        self.var_num.set('')
        self.var_suspect.set('')
        self.var_head.set('')
        self.tree.delete(*self.tree.get_children())
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.configure(state='disabled')
        self.set_status('就绪')
        self.entry.focus_set()

    # ---------- 自检 ----------
    def dump(self):
        rows = []
        for iid in self.tree.get_children():
            rows.append(self.tree.item(iid, 'values'))
        return {
            'head': self.var_head.get(),
            'status': self.var_status.get(),
            'rows': rows[:10],
            'text': self.txt.get('1.0', 'end').strip().splitlines()[:8],
        }


def run(admin, countries):
    import tkinter as tk

    if os.environ.get('IDCHECK_FORCE_GUI_FAIL'):
        raise RuntimeError('forced GUI failure (IDCHECK_FORCE_GUI_FAIL)')
    # 先把窗口建出来，成功之后再藏黑窗口：这样 Tk 起不来时控制台还在，
    # 错误至少能被看见（而不是"藏了黑框 + 回退文本模式"变成一片空白）。
    root = tk.Tk()
    _hide_console()
    app = App(root, admin, countries)

    selftest = os.environ.get('IDCHECK_GUI_SELFTEST')
    if selftest:
        import json

        def auto():
            if selftest != '1':
                app.var_num.set(selftest)
            app.do_analyze()

        def report():
            try:
                data = app.dump()
            except Exception:
                data = {'error': traceback.format_exc()}
            text = json.dumps(data, ensure_ascii=False, indent=2)
            try:
                with open(os.environ.get('IDCHECK_GUI_SELFTEST_OUT',
                                         'gui_selftest.json'), 'w',
                          encoding='utf-8') as f:
                    f.write(text)
            except Exception:
                pass
            _log(text)
            root.destroy()

        root.after(300, auto)
        root.after(9000, report)

    try:
        root.mainloop()
    except Exception:
        _log(traceback.format_exc())
        raise
    finally:
        core.startup_log('gui exit')
    return 0
