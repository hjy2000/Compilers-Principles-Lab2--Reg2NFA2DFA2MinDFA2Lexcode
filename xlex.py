# -*- coding: utf-8 -*-
"""XLEX —— 正则表达式 -> NFA -> DFA -> 最小化 DFA -> C 词法分析程序。

编译原理实验二（华南师范大学）。仅依赖 Python 标准库（tkinter 用于界面）。

支持的正则表达式语法
--------------------
    单字符      任意可打印 ASCII 字符，如 a b 0 _
    连接        ab 或显式写成 a.b（. 与 · 均视为连接符）
    选择        a|b
    闭包        a*      克林闭包（零次或多次）
                a+      正闭包（一次或多次）      —— 选做
                a?      可选（零次或一次）        —— 选做
    括号        (ab|c)*
    字符集      [abc] [a-z] [a-zA-Z0-9_]        —— 选做
    空串        ε 或 ~
    转义        \\. \\* \\| \\( \\) \\[ \\] \\\\ 等

命令行使用
----------
    python3 xlex.py                              # 启动图形界面
    python3 xlex.py --regex '(a|b)*abb' --dump   # 打印 NFA / DFA / 最小化 DFA 三张表
    python3 xlex.py --regex 'ab|c' --text abc    # 用生成的 DFA 切分词素
    python3 xlex.py --regex 'ab|c' --emit-c out.c  # 输出 C 词法分析程序

作者：基于 2018213055 侯佳耀 的实验代码重写（原 temp.py / main.py 保留为历史版本）。
"""

import argparse
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# 常量与异常
# ---------------------------------------------------------------------------

EPS = None                 # NFA 转移表中 epsilon 边的符号键
EPS_DISPLAY = 'ε'          # 表格中 epsilon 的显示形式
META = set('|*+?()[]\\.·')  # 需要特殊处理的字符集合（. 与 · 为显式连接符）
EPSILON_INPUT = set('ε~')   # 输入中表示空串的记号


class RegexError(ValueError):
    """正则表达式语法错误。"""


# ---------------------------------------------------------------------------
# 一、词法分析 + 递归下降语法分析
#    文法（优先级由低到高）：
#        alt      -> cat ('|' cat)*
#        cat      -> repeat (('.'|'·')? repeat)*
#        repeat   -> atom ('*' | '+' | '?')*
#        atom     -> '(' alt ')' | '[' class ']' | '\' 字符 | 'ε' | 普通字符
# ---------------------------------------------------------------------------


def _check_char(ch, where):
    """只允许可打印 ASCII 字符，保证后面生成的 C 程序不出现编码问题。"""
    if not (32 <= ord(ch) <= 126):
        raise RegexError('%s：字符 %r 不在可打印 ASCII 范围(32~126)内' % (where, ch))


class Parser:
    """把正则表达式文本解析成语法树。

    语法树结点（元组）：
        ('char', c)        单个字符
        ('class', frozenset) 字符集（[a-z] 等展开后的集合）
        ('eps',)           空串
        ('cat', l, r)      连接
        ('alt', l, r)      选择
        ('star', x)        克林闭包
        ('plus', x)        正闭包
        ('opt', x)         可选
    """

    def __init__(self, text):
        self.text = text
        self.pos = 0

    # -- 基础工具 ---------------------------------------------------------
    def peek(self):
        if self.pos < len(self.text):
            return self.text[self.pos]
        return None

    def _err(self, msg):
        return RegexError('第 %d 个字符处：%s' % (self.pos + 1, msg))

    # -- 入口 -------------------------------------------------------------
    def parse(self):
        if not self.text:
            raise RegexError('正则表达式为空')
        node = self.parse_alt()
        if self.pos != len(self.text):
            raise self._err('多余的字符 %r' % self.text[self.pos])
        return node

    # -- alt -> cat ('|' cat)* -------------------------------------------
    def parse_alt(self):
        node = self.parse_cat()
        if node is None:
            raise self._err('缺少表达式')
        while self.peek() == '|':
            self.pos += 1
            right = self.parse_cat()
            if right is None:
                raise self._err("'|' 右侧缺少表达式")
            node = ('alt', node, right)
        return node

    # -- cat -> repeat (('.')? repeat)* ----------------------------------
    def parse_cat(self):
        node = None
        while True:
            ch = self.peek()
            if ch is None or ch == '|' or ch == ')':
                break
            if ch in '.·':                       # 显式连接符
                if node is None:
                    raise self._err("连接符 %r 前缺少表达式" % ch)
                self.pos += 1
                node = ('cat', node, self._parse_concat_operand())
                continue
            part = self.parse_repeat()
            node = part if node is None else ('cat', node, part)
        return node

    def _parse_concat_operand(self):
        """连接符后面必须紧跟一个可连接的项，否则给出明确报错。"""
        ch = self.peek()
        if ch is None:
            raise self._err('连接符后缺少表达式')
        if ch in '|)':
            raise self._err('连接符后缺少表达式')
        return self.parse_repeat()

    # -- repeat -> atom ('*'|'+'|'?')* -----------------------------------
    def parse_repeat(self):
        node = self.parse_atom()
        seen = set()
        while True:
            ch = self.peek()
            if ch is None or ch not in '*+?':
                break
            if seen:                         # 拒绝 a** / a*+ / a?? 这类后缀连用
                raise self._err('后缀运算符 %r 不能连用' % ch)
            seen.add(ch)
            self.pos += 1
            node = ({'*': 'star', '+': 'plus', '?': 'opt'}[ch], node)
        return node

    # -- atom -------------------------------------------------------------
    def parse_atom(self):
        ch = self.peek()
        if ch is None:
            raise self._err('表达式意外结束')
        if ch == '(':
            self.pos += 1
            node = self.parse_alt()
            if node is None:
                raise self._err('括号内缺少表达式')
            if self.peek() != ')':
                raise self._err("缺少右括号 ')'")
            self.pos += 1
            return node
        if ch == '[':
            return self.parse_class()
        if ch == '\\':
            self.pos += 1
            esc = self.peek()
            if esc is None:
                raise self._err("转义符 '\\' 后缺少字符")
            if esc in EPSILON_INPUT:
                self.pos += 1
                return ('eps',)
            _check_char(esc, '第 %d 个字符处' % self.pos)
            self.pos += 1
            return ('char', esc)
        if ch in EPSILON_INPUT:
            self.pos += 1
            return ('eps',)
        if ch in META:
            raise self._err('意外的字符 %r（如需匹配请写成 \\%s）' % (ch, ch))
        _check_char(ch, '第 %d 个字符处' % (self.pos + 1))
        self.pos += 1
        return ('char', ch)

    # -- 字符集 [abc] / [a-z] --------------------------------------------
    def parse_class(self):
        self.pos += 1                       # 跳过 '['
        if self.peek() == '^':
            raise self._err('[^...] 取反字符集暂不支持，请改为枚举或用 | 连接')
        chars = set()
        first = True
        while True:
            ch = self.peek()
            if ch is None:
                raise self._err("字符集缺少右方括号 ']'")
            if ch == ']':                    # 空字符集 []，直接给出明确报错
                if first:
                    raise self._err('字符集为空')
                self.pos += 1
                break
            if ch == '\\':
                self.pos += 1
                ch = self.peek()
                if ch is None:
                    raise self._err("转义符 '\\' 后缺少字符")
            _check_char(ch, '第 %d 个字符处' % (self.pos + 1))
            self.pos += 1
            lo = ch
            # 形如 a-z 的区间：'-' 后面还有字符且不是 ']'
            if (self.peek() == '-' and self.pos + 1 < len(self.text)
                    and self.text[self.pos + 1] != ']'):
                self.pos += 1                # 跳过 '-'
                hi = self.peek()
                if hi == '\\':
                    self.pos += 1
                    hi = self.peek()
                if hi is None:
                    raise self._err("区间缺少右端点")
                _check_char(hi, '第 %d 个字符处' % (self.pos + 1))
                self.pos += 1
                if ord(hi) < ord(lo):
                    raise RegexError('区间 %s-%s 顺序颠倒' % (lo, hi))
                for code in range(ord(lo), ord(hi) + 1):
                    chars.add(chr(code))
            else:
                chars.add(lo)
            first = False
        if not chars:
            raise self._err('字符集为空')
        return ('class', frozenset(chars))


def parse_regex(text):
    """解析正则表达式文本，返回语法树。"""
    return Parser(text).parse()


# ---------------------------------------------------------------------------
# 二、Thompson 构造法：语法树 -> NFA
# ---------------------------------------------------------------------------


class NFA:
    """不确定有限自动机：状态用 0..n-1 的整数编号。"""

    def __init__(self):
        self.trans = []          # trans[s] = {字符: {后继状态}}；字符为 EPS 表示 ε 边
        self.start = 0
        self.accepts = set()     # 终态集合

    def new_state(self):
        self.trans.append({})
        return len(self.trans) - 1

    def add_edge(self, src, sym, dst):
        self.trans[src].setdefault(sym, set()).add(dst)

    def alphabet(self):
        """返回字母表（升序去重）。"""
        chars = set()
        for row in self.trans:
            for sym in row:
                if sym is not EPS:
                    chars.add(sym)
        return sorted(chars)

    def eps_of(self, state):
        return self.trans[state].get(EPS, set())

    def __len__(self):
        return len(self.trans)


class _NfaBuilder:
    """按 Thompson 规则把语法树翻译成 NFA。

    每个构造返回一个 (入口状态, 出口状态) 片段；片段的出口没有出边，
    这样可以安全地被外层拼接。
    """

    def __init__(self):
        self.nfa = NFA()

    def build(self, node):
        kind = node[0]
        handler = getattr(self, '_build_' + kind)
        return handler(node)

    # 空串 ε：两个状态加一条 ε 边
    def _build_eps(self, node):
        nfa = self.nfa
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, EPS, t)
        return s, t

    # 单字符
    def _build_char(self, node):
        nfa = self.nfa
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, node[1], t)
        return s, t

    # 字符集：一个入口、一个出口，入口对集合中每个字符各有一条边
    def _build_class(self, node):
        nfa = self.nfa
        s = nfa.new_state()
        t = nfa.new_state()
        for ch in sorted(node[1]):
            nfa.add_edge(s, ch, t)
        return s, t

    # 连接：前一片段出口 ε-> 后一片段入口
    def _build_cat(self, node):
        nfa = self.nfa
        ls, lt = self.build(node[1])
        rs, rt = self.build(node[2])
        nfa.add_edge(lt, EPS, rs)
        return ls, rt

    # 选择：新入口 ε 分叉，两出口 ε 汇合
    def _build_alt(self, node):
        nfa = self.nfa
        ls, lt = self.build(node[1])
        rs, rt = self.build(node[2])
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, EPS, ls)
        nfa.add_edge(s, EPS, rs)
        nfa.add_edge(lt, EPS, t)
        nfa.add_edge(rt, EPS, t)
        return s, t

    # 闭包 X*：入口可跳过，出口可回到入口
    def _build_star(self, node):
        nfa = self.nfa
        xs, xt = self.build(node[1])
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, EPS, xs)
        nfa.add_edge(s, EPS, t)
        nfa.add_edge(xt, EPS, xs)
        nfa.add_edge(xt, EPS, t)
        return s, t

    # 正闭包 X+：至少走一次 X，出口可回到入口
    def _build_plus(self, node):
        nfa = self.nfa
        xs, xt = self.build(node[1])
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, EPS, xs)
        nfa.add_edge(xt, EPS, xs)
        nfa.add_edge(xt, EPS, t)
        return s, t

    # 可选 X?：可直接跳过 X
    def _build_opt(self, node):
        nfa = self.nfa
        xs, xt = self.build(node[1])
        s = nfa.new_state()
        t = nfa.new_state()
        nfa.add_edge(s, EPS, xs)
        nfa.add_edge(s, EPS, t)
        nfa.add_edge(xt, EPS, t)
        return s, t


def build_nfa(ast):
    """由语法树构造 NFA（Thompson 构造法）。"""
    builder = _NfaBuilder()
    start, accept = builder.build(ast)
    nfa = builder.nfa
    nfa.start = start
    nfa.accepts = {accept}
    return nfa


# ---------------------------------------------------------------------------
# 三、子集构造法：NFA -> DFA
# ---------------------------------------------------------------------------


class DFA:
    """确定有限自动机。转移表中缺失的项表示"无转移"（即进入陷阱状态）。"""

    def __init__(self, alphabet):
        self.alphabet = list(alphabet)
        self.trans = []          # trans[s] = {字符: 后继状态}
        self.start = 0
        self.accepts = set()
        self.state_sets = []     # 每个 DFA 状态对应的 NFA 状态子集（用于展示）

    def __len__(self):
        return len(self.trans)

    def step(self, state, ch):
        return self.trans[state].get(ch)

    def is_complete(self):
        for row in self.trans:
            if len(row) != len(self.alphabet):
                return False
        return True


def eps_closure(nfa, states):
    """求状态集合的 ε-闭包。"""
    seen = set(states)
    stack = list(states)
    while stack:
        s = stack.pop()
        for t in nfa.eps_of(s):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    return frozenset(seen)


def nfa_to_dfa(nfa):
    """子集构造法。状态按 BFS 发现顺序编号，因此 start 恒为 0。"""
    alphabet = nfa.alphabet()
    start_set = eps_closure(nfa, {nfa.start})
    index = {start_set: 0}
    order = [start_set]
    dfa = DFA(alphabet)
    cursor = 0
    while cursor < len(order):
        cur = order[cursor]
        row = {}
        for ch in alphabet:
            moved = set()
            for s in cur:
                moved |= nfa.trans[s].get(ch, set())
            if not moved:
                continue
            nxt = eps_closure(nfa, moved)
            if nxt not in index:
                index[nxt] = len(order)
                order.append(nxt)
            row[ch] = index[nxt]
        dfa.trans.append(row)
        if cur & nfa.accepts:
            dfa.accepts.add(cursor)
        cursor += 1
    dfa.state_sets = order
    dfa.start = 0
    return dfa


# ---------------------------------------------------------------------------
# 四、DFA 最小化（划分精化 / Moore 算法）
# ---------------------------------------------------------------------------


def minimize_dfa(dfa):
    """最小化 DFA，返回新的 DFA。

    步骤：
      1. 补全：缺失的转移统一指向一个新加的死状态 dead；
      2. 只保留从初态可达的状态；
      3. 初始划分 {终态} / {非终态}，按"各输入字符的后继所属块"反复精化；
      4. 合并后去掉死状态所在的块（它对应"任何输入都不接受"，
         去掉后该状态上的转移即为错误转移，语言不变）；
      5. 按 BFS 重新编号，使初态为 0，表格更易读。
    """
    n = len(dfa.trans)
    dead = n
    full = []
    for row in dfa.trans:
        full.append({ch: row.get(ch, dead) for ch in dfa.alphabet})
    full.append({ch: dead for ch in dfa.alphabet})

    # --- 可达性 ---------------------------------------------------------
    reachable = set()
    stack = [dfa.start]
    while stack:
        s = stack.pop()
        if s in reachable:
            continue
        reachable.add(s)
        for ch in dfa.alphabet:
            stack.append(full[s][ch])

    # --- 初始划分 -------------------------------------------------------
    blocks = []
    acc = reachable & set(dfa.accepts)
    non = reachable - acc
    if acc:
        blocks.append(acc)
    if non:
        blocks.append(non)

    # --- 反复精化 -------------------------------------------------------
    while True:
        block_of = {}
        for bi, block in enumerate(blocks):
            for s in block:
                block_of[s] = bi
        new_blocks = []
        changed = False
        for block in blocks:
            buckets = {}
            for s in block:
                sig = tuple(block_of[full[s][ch]] for ch in dfa.alphabet)
                buckets.setdefault(sig, set()).add(s)
            if len(buckets) > 1:
                changed = True
            new_blocks.extend(buckets.values())
        blocks = new_blocks
        if not changed:
            break

    block_of = {}
    for bi, block in enumerate(blocks):
        for s in block:
            block_of[s] = bi

    dead_block = block_of.get(dead)
    start_block = block_of[dfa.start]

    # --- 按 BFS 给保留的块编号 ------------------------------------------
    order = []
    seen = set()
    queue = [start_block]
    while queue:
        bi = queue.pop(0)
        if bi in seen or bi == dead_block:
            continue
        seen.add(bi)
        order.append(bi)
        rep = min(blocks[bi])
        for ch in dfa.alphabet:
            nxt = block_of[full[rep][ch]]
            if nxt not in seen and nxt != dead_block:
                queue.append(nxt)

    if start_block not in seen:              # 理论上不会发生，保险
        order.insert(0, start_block)

    new_index = {bi: i for i, bi in enumerate(order)}
    mdfa = DFA(dfa.alphabet)
    mdfa.trans = []
    mdfa.state_sets = []
    for bi in order:
        rep = min(blocks[bi])
        row = {}
        for ch in dfa.alphabet:
            nxt = block_of[full[rep][ch]]
            if nxt in new_index:
                row[ch] = new_index[nxt]
        mdfa.trans.append(row)
        merged = set()
        for s in blocks[bi]:
            merged |= set(dfa.state_sets[s]) if dfa.state_sets else {s}
        mdfa.state_sets.append(frozenset(merged))
    mdfa.start = new_index[start_block]
    mdfa.accepts = {new_index[bi] for bi in order if blocks[bi] & set(dfa.accepts)}
    return mdfa


# ---------------------------------------------------------------------------
# 五、自动机的语言（用于自测、CLI 预览和 GUI 提示）
# ---------------------------------------------------------------------------


def nfa_accepts(nfa, text):
    """NFA 是否接受整个串 text。"""
    cur = eps_closure(nfa, {nfa.start})
    for ch in text:
        moved = set()
        for s in cur:
            moved |= nfa.trans[s].get(ch, set())
        if not moved:
            return False
        cur = eps_closure(nfa, moved)
    return bool(cur & nfa.accepts)


def dfa_accepts(dfa, text):
    """DFA 是否接受整个串 text（整串匹配）。"""
    state = dfa.start
    for ch in text:
        nxt = dfa.trans[state].get(ch)
        if nxt is None:
            return False
        state = nxt
    return state in dfa.accepts


def match_longest(dfa, text, start):
    """从 text[start] 开始做最长匹配，返回匹配结束位置；无匹配返回 -1。

    与生成的 C 程序中的 match_longest 语义完全一致。
    """
    state = dfa.start
    best = -1
    i = start
    while i < len(text):
        nxt = dfa.trans[state].get(text[i])
        if nxt is None:
            break
        state = nxt
        i += 1
        if state in dfa.accepts:
            best = i
    return best


def scan(dfa, text, skip_space=True):
    """用最小化 DFA 切分词素，返回 [(词素, 起点, 终点)] 与错误列表。"""
    tokens = []
    errors = []
    i = 0
    while i < len(text):
        if skip_space and text[i].isspace():
            i += 1
            continue
        end = match_longest(dfa, text, i)
        if end <= i:                     # 无匹配，或匹配到空串（避免死循环）
            errors.append((text[i], i))
            i += 1
        else:
            tokens.append((text[i:end], i, end))
            i = end
    return tokens, errors


# ---------------------------------------------------------------------------
# 六、一次性编译入口
# ---------------------------------------------------------------------------


class Compiled(object):
    """一次完整转换的结果。"""

    def __init__(self, regex, ast, nfa, dfa, mdfa):
        self.regex = regex
        self.ast = ast
        self.nfa = nfa
        self.dfa = dfa
        self.mdfa = mdfa

    @property
    def alphabet(self):
        return list(self.dfa.alphabet)

    def describe(self):
        return {
            'regex': self.regex,
            'alphabet': self.alphabet,
            'nfa_states': len(self.nfa),
            'dfa_states': len(self.dfa),
            'mdfa_states': len(self.mdfa),
            'nfa_accepts_empty': nfa_accepts(self.nfa, ''),
            'mdfa_accepts_empty': dfa_accepts(self.mdfa, ''),
        }


def compile_regex(regex):
    """正则表达式 -> NFA -> DFA -> 最小化 DFA。"""
    ast = parse_regex(regex)
    nfa = build_nfa(ast)
    dfa = nfa_to_dfa(nfa)
    mdfa = minimize_dfa(dfa)
    return Compiled(regex, ast, nfa, dfa, mdfa)


# ---------------------------------------------------------------------------
# 七、状态转移表的文本化（GUI 与 CLI 共用）
# ---------------------------------------------------------------------------


def state_name(i):
    """0->A, 1->B, ... 25->Z, 26->S26。"""
    if i < 26:
        return chr(ord('A') + i)
    return 'S%d' % i


def _fmt_state_set(states):
    if not states:
        return '—'
    return '{' + ','.join(str(s) for s in sorted(states)) + '}'


def nfa_table(nfa):
    """返回 (表头, 数据行) —— NFA 状态转移表。"""
    alphabet = nfa.alphabet()
    headers = ['状态'] + alphabet + [EPS_DISPLAY, '类型']
    rows = []
    for s in range(len(nfa)):
        row = ['q%d' % s]
        for ch in alphabet:
            row.append(_fmt_state_set(nfa.trans[s].get(ch, set())))
        row.append(_fmt_state_set(nfa.eps_of(s)))
        marks = []
        if s == nfa.start:
            marks.append('初态')
        if s in nfa.accepts:
            marks.append('终态')
        row.append('、'.join(marks) if marks else '')
        rows.append(row)
    return headers, rows


def dfa_table(dfa, show_nfa_sets=False):
    """返回 (表头, 数据行) —— DFA / 最小化 DFA 状态转移表。"""
    headers = ['状态'] + list(dfa.alphabet) + ['类型']
    if show_nfa_sets:
        headers.append('对应 NFA 状态集')
    rows = []
    for s in range(len(dfa)):
        row = [state_name(s)]
        for ch in dfa.alphabet:
            nxt = dfa.trans[s].get(ch)
            row.append(state_name(nxt) if nxt is not None else '—')
        marks = []
        if s == dfa.start:
            marks.append('初态')
        if s in dfa.accepts:
            marks.append('终态')
        row.append('、'.join(marks) if marks else '')
        if show_nfa_sets:
            row.append(_fmt_state_set(dfa.state_sets[s]) if dfa.state_sets else '')
        rows.append(row)
    return headers, rows


def _display_width(text):
    """终端对齐用：中日韩字符按 2 列计算。"""
    width = 0
    for ch in text:
        width += 2 if ord(ch) > 0x2E80 else 1
    return width


def format_table(headers, rows):
    """把表格排成等宽文本（用于命令行输出）。"""
    widths = [_display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(str(cell)))
    lines = []
    for row in [headers] + [[str(c) for c in r] for r in rows]:
        parts = []
        for i, cell in enumerate(row):
            pad = widths[i] - _display_width(cell)
            parts.append(cell + ' ' * pad)
        lines.append('  '.join(parts).rstrip())
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 八、C 词法分析程序生成
# ---------------------------------------------------------------------------

_C_TEMPLATE = r'''/* ==========================================================================
 *  XLEX —— 由正则表达式自动生成的词法分析程序
 *
 *  正则表达式  : @@REGEX@@
 *  字母表      : @@ALPHABET@@
 *  自动机状态数: @@STATES@@        字母表大小: @@SYMS@@
 *  生成工具    : xlex.py（编译原理实验二）
@@NOTES@@
 *
 *  编译: cc -O2 -o scanner scanner.c
 *  运行: ./scanner [源程序文件]        (省略参数则从标准输入读取)
 *
 *  输出: <TOKEN, 词素, [起点,终点)>   识别出一个记号
 *        <ERROR, 字符, pos=位置>      无法匹配的字符
 *  规则: 最长匹配(longest match)，即不断读入直到无法继续为止，
 *        取其中最长的、停在终态的那个前缀作为词素。
 * ========================================================================== */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DFA_STATES  @@STATES@@
#define DFA_SYMS    @@SYMS@@   /* 字母表为空时占位为 1，此时 char_class 恒为 -1 */
#define DFA_START   @@START@@

/* 状态转移表: TRANS[状态][字符类] = 后继状态; -1 表示该状态没有这条转移 */
static const int TRANS[DFA_STATES][DFA_SYMS] = {
@@TRANS_TABLE@@
};

/* 终态标记: 1 表示该状态是接受状态 */
static const int ACCEPT[DFA_STATES] = {
@@ACCEPT_TABLE@@
};

/* 字符 -> 字符类下标; 不属于字母表时返回 -1 */
static int char_class(int c)
{
@@CHAR_CLASS@@
}

/* 从 buf[start] 开始做最长匹配, 返回匹配结束位置(不含);
 * 无匹配返回 -1. 只有在到达终态时才更新 best, 因此结果一定最长. */
static int match_longest(const char *buf, int len, int start)
{
    int state = DFA_START;
    int best = -1;
    int i = start;

    while (i < len) {
        int cls = char_class((unsigned char)buf[i]);
        int next;

        if (cls < 0) {
            break;
        }
        next = TRANS[state][cls];
        if (next < 0) {
            break;
        }
        state = next;
        ++i;
        if (ACCEPT[state]) {
            best = i;
        }
    }
    return best;
}

/* 一次性读入整个文件/stdin */
static char *read_all(FILE *fp, int *out_len)
{
    size_t cap = 4096;
    size_t len = 0;
    size_t n;
    char *buf = (char *)malloc(cap);

    if (buf == NULL) {
        return NULL;
    }
    while ((n = fread(buf + len, 1, cap - len, fp)) > 0) {
        len += n;
        if (len == cap) {
            char *grown;

            cap *= 2;
            grown = (char *)realloc(buf, cap);
            if (grown == NULL) {
                free(buf);
                return NULL;
            }
            buf = grown;
        }
    }
    *out_len = (int)len;
    return buf;
}

int main(int argc, char **argv)
{
    FILE *fp = stdin;
    int len = 0;
    int i = 0;
    int ntokens = 0;
    int nerrors = 0;
    char *buf;

    if (argc > 1) {
        fp = fopen(argv[1], "rb");
        if (fp == NULL) {
            fprintf(stderr, "无法打开文件: %s\n", argv[1]);
            return 2;
        }
    }
    buf = read_all(fp, &len);
    if (fp != stdin) {
        fclose(fp);
    }
    if (buf == NULL) {
        fprintf(stderr, "内存不足\n");
        return 2;
    }

    while (i < len) {
        int end;

        if (isspace((unsigned char)buf[i])) {   /* 空白符不参与匹配 */
            ++i;
            continue;
        }
        end = match_longest(buf, len, i);
        if (end <= i) {                         /* 匹配长度 <= 0, 按错误处理 */
            printf("<ERROR, '%c', pos=%d>\n", buf[i], i);
            ++nerrors;
            ++i;
        } else {
            printf("<TOKEN, %.*s, [%d,%d)>\n", end - i, buf + i, i, end);
            ++ntokens;
            i = end;
        }
    }
    printf("/* %d token(s), %d error(s) */\n", ntokens, nerrors);
    free(buf);
    return nerrors == 0 ? 0 : 1;
}
'''


def _c_comment_text(text):
    """把任意文本安全地放进 C 的块注释里。"""
    return text.replace('*/', '* /').replace('\r', ' ').replace('\n', ' ')


def _c_char_comment(ch):
    """字符的 C 注释；引号、反斜杠等特殊字符直接用十六进制说明。"""
    if ch == "'" or ch == '\\':
        return '/* 0x%02X */' % ord(ch)
    return "/* '%s' */" % ch


def generate_c(mdfa, regex):
    """由最小化 DFA 生成一份完整、可编译的 C 词法分析程序。"""
    alphabet = list(mdfa.alphabet)
    states = len(mdfa)
    syms = max(1, len(alphabet))

    trans_lines = []
    for s in range(states):
        cells = []
        for ch in alphabet:
            nxt = mdfa.trans[s].get(ch)
            cells.append('-1' if nxt is None else str(nxt))
        if not cells:
            cells = ['-1']
        trans_lines.append('    { %s },  /* %s */' % (', '.join(cells), state_name(s)))
    trans_table = '\n'.join(trans_lines)

    accept_lines = []
    for s in range(states):
        accept_lines.append('    %d,%s' % (1 if s in mdfa.accepts else 0,
                                          '  /* %s */' % state_name(s)))
    accept_table = '\n'.join(accept_lines)

    if alphabet:
        class_lines = ['    switch (c) {']
        for idx, ch in enumerate(alphabet):
            class_lines.append('    case 0x%02X: return %d;   %s'
                               % (ord(ch), idx, _c_char_comment(ch)))
        class_lines.append('    default: return -1;')
        class_lines.append('    }')
        char_class = '\n'.join(class_lines)
    else:
        char_class = '    (void)c;\n    return -1;   /* 该表达式没有消耗字符 */'

    notes = []
    if dfa_accepts(mdfa, ''):
        notes.append(' *  注意: 该正则表达式可以匹配空串, 生成的最长匹配会忽略这一点')
    if alphabet:
        shown = ' '.join(alphabet)
    else:
        shown = '(空)'
    notes_text = '\n'.join(notes)

    code = _C_TEMPLATE
    replacements = [
        ('@@REGEX@@', _c_comment_text(regex)),
        ('@@ALPHABET@@', _c_comment_text(shown)),
        ('@@STATES@@', str(states)),
        ('@@SYMS@@', str(syms)),
        ('@@START@@', str(mdfa.start)),
        ('@@TRANS_TABLE@@', trans_table),
        ('@@ACCEPT_TABLE@@', accept_table),
        ('@@CHAR_CLASS@@', char_class),
        ('@@NOTES@@', notes_text),
    ]
    for key, value in replacements:
        code = code.replace(key, value)
    return code


# ---------------------------------------------------------------------------
# 九、图形界面
# ---------------------------------------------------------------------------


DEFAULT_FONT = ('Menlo', 12) if sys.platform == 'darwin' else ('Consolas', 11)

# tkinter 只在需要界面时使用；无图形环境（精简版 Python）下命令行仍可用
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    TK_AVAILABLE = True
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    TK_AVAILABLE = False


class XlexApp(object):
    def __init__(self, root):
        self.root = root
        self.compiled = None
        self.c_code = ''
        self.regex_var = tk.StringVar(value='(a|b)*abb')
        self._build()

    # -- 界面搭建 ---------------------------------------------------
    def _build(self):
        root = self.root
        root.title('XLEX —— 正则表达式 → NFA → DFA → 最小化 DFA → C 词法分析程序')
        root.geometry('1140x760')
        root.minsize(900, 600)

        # 第一行：正则表达式输入
        top = ttk.Frame(root, padding=(12, 10, 12, 4))
        top.pack(fill='x')
        ttk.Label(top, text='正则表达式：').pack(side='left')
        entry = ttk.Entry(top, textvariable=self.regex_var, font=DEFAULT_FONT, width=46)
        entry.pack(side='left', padx=(0, 8))
        entry.bind('<Return>', lambda event: self.run_all())
        ttk.Button(top, text='打开…', width=8, command=self.on_open).pack(side='left', padx=3)
        ttk.Button(top, text='保存…', width=8, command=self.on_save_regex).pack(side='left', padx=3)

        # 第二行：功能按钮（回调统一包一层 _guard，语法错误只弹窗不崩栈）
        bar = ttk.Frame(root, padding=(12, 4))
        bar.pack(fill='x')
        ttk.Button(bar, text='表达式 → NFA', width=14,
                   command=self._guard(self.on_nfa)).pack(side='left', padx=(0, 4))
        ttk.Button(bar, text='NFA → DFA', width=14,
                   command=self._guard(self.on_dfa)).pack(side='left', padx=4)
        ttk.Button(bar, text='DFA 最小化', width=14,
                   command=self._guard(self.on_min)).pack(side='left', padx=4)
        ttk.Button(bar, text='生成 C 程序', width=14,
                   command=self._guard(self.on_code)).pack(side='left', padx=4)
        ttk.Button(bar, text='一键执行', width=12,
                   command=self.run_all).pack(side='left', padx=(16, 4))
        ttk.Button(bar, text='关于', width=8,
                   command=self.on_about).pack(side='right')

        # 表格区
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='both', expand=True, padx=12, pady=(6, 4))

        self.tab_nfa, self.tree_nfa = self._make_table_tab('NFA 状态转移表')
        self.tab_dfa, self.tree_dfa = self._make_table_tab('DFA 状态转移表')
        self.tab_min, self.tree_min = self._make_table_tab('最小化 DFA 状态转移表')

        # C 代码页
        self.tab_code = ttk.Frame(self.nb, padding=6)
        codebar = ttk.Frame(self.tab_code)
        codebar.pack(fill='x', pady=(0, 6))
        ttk.Button(codebar, text='生成 / 刷新', command=self.on_code).pack(side='left')
        ttk.Button(codebar, text='保存为 .c 文件…',
                   command=self.on_save_c).pack(side='left', padx=6)
        ttk.Label(codebar, text='（生成的 C 程序可用 cc scanner.c -o scanner 编译运行）'
                  ).pack(side='left', padx=10)
        self.code_text = tk.Text(self.tab_code, wrap='none', font=DEFAULT_FONT,
                                 undo=False, background='#fbfbfb')
        yscroll = ttk.Scrollbar(self.tab_code, orient='vertical',
                                command=self.code_text.yview)
        xscroll = ttk.Scrollbar(self.tab_code, orient='horizontal',
                                command=self.code_text.xview)
        self.code_text.configure(yscrollcommand=yscroll.set,
                                 xscrollcommand=xscroll.set)
        self.code_text.pack(side='left', fill='both', expand=True)
        yscroll.pack(side='right', fill='y')
        xscroll.pack(side='bottom', fill='x')
        self.nb.add(self.tab_code, text='词法分析程序 (C)')

        self.status = ttk.Label(root, text='就绪', anchor='w',
                                relief='sunken', padding=(8, 4))
        self.status.pack(fill='x', side='bottom')

    def _make_table_tab(self, title):
        frame = ttk.Frame(self.nb, padding=6)
        inner = ttk.Frame(frame)
        inner.pack(fill='both', expand=True)
        tree = ttk.Treeview(inner, show='headings', selectmode='browse')
        yscroll = ttk.Scrollbar(inner, orient='vertical', command=tree.yview)
        xscroll = ttk.Scrollbar(inner, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        inner.rowconfigure(0, weight=1)
        inner.columnconfigure(0, weight=1)
        tree.tag_configure('accept', background='#e8f5e9')
        tree.tag_configure('start', background='#e3f2fd')
        self.nb.add(frame, text=title)
        return frame, tree

    # -- 表格填充 ---------------------------------------------------
    def _fill_tree(self, tree, headers, rows):
        tree.delete(*tree.get_children())
        keys = ['c%d' % i for i in range(len(headers))]
        tree.configure(columns=keys)
        for key, text in zip(keys, headers):
            tree.heading(key, text=text)
            # 按内容调整列宽
            index = keys.index(key)
            widest = len(text)
            for row in rows:
                widest = max(widest, len(str(row[index])))
            tree.column(key, width=max(60, min(300, widest * 9 + 16)),
                        anchor='center', stretch=False)
        # '类型' 列不是固定位置（NFA 表末尾是 ε，DFA 表末尾可能是 NFA 状态集），
        # 按表头名字定位，避免高亮打到错误的列上
        marks_index = headers.index('类型') if '类型' in headers else None
        for row in rows:
            tags = []
            if marks_index is not None:
                marks = str(row[marks_index])
                if '初态' in marks:
                    tags.append('start')
                if '终态' in marks:
                    tags.append('accept')
            tree.insert('', 'end', values=row, tags=tags)

    def _set_status(self, text):
        self.status.configure(text=text)

    # -- 各功能入口 -------------------------------------------------
    def _current_regex(self):
        return self.regex_var.get().strip()

    def _ensure_compiled(self):
        """按需完成 解析->NFA->DFA->最小化，返回 Compiled；失败抛异常。"""
        regex = self._current_regex()
        if not regex:
            raise RegexError('请输入正则表达式')
        if self.compiled is None or self.compiled.regex != regex:
            self.compiled = compile_regex(regex)
        return self.compiled

    def _guard(self, func):
        """统一异常处理：正则错误/运行错误都弹窗提示，不让界面崩掉。"""
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except RegexError as exc:
                messagebox.showerror('正则表达式错误', str(exc), parent=self.root)
                self._set_status('正则表达式错误：%s' % exc)
            except Exception as exc:              # 兜底，避免界面静默失效
                messagebox.showerror('运行错误', '%s: %s' % (type(exc).__name__, exc),
                                     parent=self.root)
                self._set_status('运行错误：%s' % exc)
            return None
        return wrapper

    def on_open(self):
        path = filedialog.askopenfilename(
            title='打开正则表达式文件',
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')],
            parent=self.root)
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                text = handle.read().strip()
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror('打开失败', str(exc), parent=self.root)
            return
        self.regex_var.set(text)
        self.compiled = None
        self._set_status('已读入 %s，共 %d 个字符。' % (path, len(text)))
        self.run_all()

    def on_save_regex(self):
        path = filedialog.asksaveasfilename(
            title='保存正则表达式',
            defaultextension='.txt',
            filetypes=[('文本文件', '*.txt')],
            parent=self.root)
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(self._current_regex() + '\n')
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc), parent=self.root)
            return
        self._set_status('正则表达式已保存到 %s。' % path)

    def on_nfa(self):
        compiled = self._ensure_compiled()
        headers, rows = nfa_table(compiled.nfa)
        self._fill_tree(self.tree_nfa, headers, rows)
        self.nb.select(self.tab_nfa)
        self._set_status('NFA：%d 个状态，字母表 %s。'
                         % (len(compiled.nfa), self._alphabet_text(compiled)))

    def on_dfa(self):
        compiled = self._ensure_compiled()
        headers, rows = dfa_table(compiled.dfa)
        self._fill_tree(self.tree_dfa, headers, rows)
        self.nb.select(self.tab_dfa)
        self._set_status('DFA：%d 个状态（子集构造法），字母表 %s。'
                         % (len(compiled.dfa), self._alphabet_text(compiled)))

    def on_min(self):
        compiled = self._ensure_compiled()
        headers, rows = dfa_table(compiled.mdfa, show_nfa_sets=True)
        self._fill_tree(self.tree_min, headers, rows)
        self.nb.select(self.tab_min)
        self._set_status('最小化 DFA：%d 个状态（最小化前 %d 个）。'
                         % (len(compiled.mdfa), len(compiled.dfa)))

    def on_code(self):
        compiled = self._ensure_compiled()
        self.c_code = generate_c(compiled.mdfa, compiled.regex)
        self.code_text.delete('1.0', 'end')
        self.code_text.insert('1.0', self.c_code)
        self.nb.select(self.tab_code)
        self._set_status('已生成 C 词法分析程序（%d 个状态，%d 个字符类）。'
                         % (len(compiled.mdfa), len(compiled.mdfa.alphabet)))

    def on_save_c(self):
        if not self.c_code:
            self.on_code()
        path = filedialog.asksaveasfilename(
            title='保存 C 词法分析程序',
            defaultextension='.c',
            initialfile='scanner.c',
            filetypes=[('C 源文件', '*.c')],
            parent=self.root)
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(self.c_code)
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc), parent=self.root)
            return
        self._set_status('C 程序已保存到 %s。' % path)

    def _alphabet_text(self, compiled):
        if not compiled.alphabet:
            return '(空)'
        return '{' + ','.join(compiled.alphabet) + '}'

    def run_all(self):
        try:
            regex = self._current_regex()
            if not regex:
                raise RegexError('请输入正则表达式')
            self.compiled = compile_regex(regex)
            compiled = self.compiled

            headers, rows = nfa_table(compiled.nfa)
            self._fill_tree(self.tree_nfa, headers, rows)
            headers, rows = dfa_table(compiled.dfa)
            self._fill_tree(self.tree_dfa, headers, rows)
            headers, rows = dfa_table(compiled.mdfa, show_nfa_sets=True)
            self._fill_tree(self.tree_min, headers, rows)

            self.c_code = generate_c(compiled.mdfa, compiled.regex)
            self.code_text.delete('1.0', 'end')
            self.code_text.insert('1.0', self.c_code)

            self.nb.select(self.tab_nfa)
            self._set_status(
                '完成：NFA %d 态 → DFA %d 态 → 最小化 DFA %d 态；字母表 %s；'
                '空串%s被接受。'
                % (len(compiled.nfa), len(compiled.dfa), len(compiled.mdfa),
                   self._alphabet_text(compiled),
                   '' if dfa_accepts(compiled.mdfa, '') else '不'))
        except RegexError as exc:
            messagebox.showerror('正则表达式错误', str(exc), parent=self.root)
            self._set_status('正则表达式错误：%s' % exc)
        except Exception as exc:
            messagebox.showerror('运行错误', '%s: %s' % (type(exc).__name__, exc),
                                 parent=self.root)
            self._set_status('运行错误：%s' % exc)

    def on_about(self):
        messagebox.showinfo(
            '关于',
            'XLEX 词法分析程序生成器\n\n'
            '正则表达式 → NFA（Thompson 构造法）\n'
            'NFA → DFA（子集构造法）\n'
            'DFA → 最小化 DFA（划分精化）\n'
            '最小化 DFA → C 词法分析程序\n\n'
            '支持运算：连接、选择 |、闭包 * + ?、括号、字符集 [a-z]\n'
            '编译原理实验二',
            parent=self.root)


def _tk_version_of(python):
    """返回某个解释器链接的 Tk 版本；无法导入 tkinter 时返回 0。"""
    try:
        out = subprocess.run(
            [python, '-c', 'import tkinter; print(tkinter.TkVersion)'],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if out.returncode != 0:
        return 0.0
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _is_interpreter(path):
    """粗略判断路径是不是 Python 解释器（排除 python3-config 这类工具）。"""
    base = os.path.basename(path)
    if not (base == 'python3' or (base.startswith('python3.') and base[8:].isdigit())):
        return False
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _candidate_pythons():
    """列出可能带新版 Tk 的解释器路径。"""
    import glob
    found = []
    env = os.environ.get('XLEX_PYTHON')
    if env:
        found.append(env)
    for name in ('python3.13', 'python3.12', 'python3.11', 'python3.10'):
        path = shutil.which(name)
        if path:
            found.append(path)
    found.extend([
        '/opt/homebrew/bin/python3',
        '/usr/local/bin/python3',
        '/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
    ])
    # glob 会匹配到 python3-config 这类非解释器文件，交给 _is_interpreter 过滤
    found.extend(sorted(glob.glob(os.path.expanduser(
        '~/.local/share/uv/python/*/bin/python3*'))))
    seen = set()
    result = []
    for path in found:
        if path in seen or not _is_interpreter(path):
            continue
        seen.add(path)
        result.append(path)
    return result


def _relaunch_with_modern_tk():
    """macOS 上若 Tk < 8.6，尝试换一个解释器重新执行本程序。

    Apple 自带的 Tk 8.5 在 macOS 10.14 之后无法绘制窗口内容（窗口空白）。
    成功后 os.execv 不会返回；失败返回 False，由调用方给出提示。
    """
    if os.environ.get('XLEX_RELAUNCHED'):
        return False                     # 已经换过一次，避免无限重试
    script = os.path.abspath(__file__)
    tail = sys.argv[1:]

    for python in _candidate_pythons():
        if os.path.abspath(python) == os.path.abspath(sys.executable):
            continue
        if _tk_version_of(python) >= 8.6:
            os.environ['XLEX_RELAUNCHED'] = '1'
            try:
                os.execv(python, [python, script] + tail)
            except OSError:
                continue

    uv = shutil.which('uv')
    if uv:
        os.environ['XLEX_RELAUNCHED'] = '1'
        try:
            os.execv(uv, [uv, 'run', '--quiet', '--python', '3.13',
                          'python', script] + tail)
        except OSError:
            pass
    return False


def launch_gui():
    """启动 tkinter 界面。"""
    if not TK_AVAILABLE:
        print('当前 Python 环境没有 tkinter，无法启动图形界面；'
              '请改用命令行参数 --regex ... --dump。', file=sys.stderr)
        return 1
    if sys.platform == 'darwin' and tk.TkVersion < 8.6:
        # 先尝试自动换用带 Tk 8.6 的解释器（成功则本进程被替换，不再返回）
        _relaunch_with_modern_tk()
        print('警告：当前 Python 链接的是 Tk %s。Apple 自带的 Tk 8.5 在 '
              'macOS 10.14 之后存在已知缺陷，窗口内容会显示为空白。\n'
              '请改用 Tk 8.6 及以上的 Python，例如：\n'
              '  ./run.sh                    （本目录的启动脚本，自动挑选合适的解释器）\n'
              '  uv run --python 3.13 python xlex.py\n'
              % tk.TkVersion, file=sys.stderr)
    root = tk.Tk()
    XlexApp(root)
    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# 十、命令行入口
# ---------------------------------------------------------------------------


def _dump(compiled):
    """命令行下打印三张状态转移表和统计信息。"""
    out = []
    out.append('正则表达式: %s' % compiled.regex)
    out.append('字母表    : %s' % ('(空)' if not compiled.alphabet
                                  else '{' + ','.join(compiled.alphabet) + '}'))
    out.append('')
    out.append('===== NFA 状态转移表（Thompson 构造，共 %d 个状态） =====' % len(compiled.nfa))
    out.append(format_table(*nfa_table(compiled.nfa)))
    out.append('')
    out.append('===== DFA 状态转移表（子集构造，共 %d 个状态） =====' % len(compiled.dfa))
    out.append(format_table(*dfa_table(compiled.dfa)))
    out.append('')
    out.append('===== 最小化 DFA 状态转移表（共 %d 个状态，最小化前 %d 个） ====='
               % (len(compiled.mdfa), len(compiled.dfa)))
    out.append(format_table(*dfa_table(compiled.mdfa, show_nfa_sets=True)))
    out.append('')
    out.append('该表达式%s接受空串。' % ('' if dfa_accepts(compiled.mdfa, '') else '不'))
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='XLEX：正则表达式 -> NFA -> DFA -> 最小化 DFA -> C 词法分析程序',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='不带 --regex 时启动图形界面。')
    parser.add_argument('--regex', help='要转换的正则表达式')
    parser.add_argument('--dump', action='store_true', help='打印 NFA/DFA/最小化 DFA 三张状态转移表')
    parser.add_argument('--text', help='用最小化 DFA 切分该文本，打印词素与错误')
    parser.add_argument('--emit-c', metavar='PATH', help='把生成的 C 词法分析程序写到文件')
    args = parser.parse_args(argv)

    if not args.regex:
        launch_gui()
        return 0

    try:
        compiled = compile_regex(args.regex)
    except RegexError as exc:
        print('正则表达式错误：%s' % exc, file=sys.stderr)
        return 2

    if args.dump:
        print(_dump(compiled))
    if args.text is not None:
        tokens, errors = scan(compiled.mdfa, args.text)
        print('输入文本: %r' % args.text)
        for lexeme, start, end in tokens:
            print('<TOKEN, %s, [%d,%d)>' % (lexeme, start, end))
        for ch, pos in errors:
            print("<ERROR, '%s', pos=%d>" % (ch, pos))
        print('/* %d token(s), %d error(s) */' % (len(tokens), len(errors)))
    if args.emit_c:
        code = generate_c(compiled.mdfa, compiled.regex)
        with open(args.emit_c, 'w', encoding='utf-8') as handle:
            handle.write(code)
        print('已生成 C 词法分析程序: %s' % args.emit_c)
    if not (args.dump or args.text is not None or args.emit_c):
        for key, value in compiled.describe().items():
            print('%-18s %s' % (key, value))
    return 0


if __name__ == '__main__':
    sys.exit(main())
