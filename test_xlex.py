# -*- coding: utf-8 -*-
"""xlex.py 的自动化测试。

两层验证：
  1. 语言等价性：对每个正则表达式，穷举长度不超过 5 的全部字符串，要求
     NFA、子集构造 DFA、最小化 DFA 三者的接受结果完全一致；另用 Python 的 re
     模块做独立参照（re.fullmatch，因此也可以用 Python 正则引擎验算）。
  2. C 代码端到端：把生成的 C 词法分析程序用系统 cc 编译并运行，
     比对输出与 xlex.scan 的结果，确保「生成的确实是可编译可运行的 C 程序」。

运行：
    python3 -m unittest -v test_xlex
    python3 -m unittest -v test_xlex.TestCodegen      # 只跑 C 代码生成测试
"""

import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xlex  # noqa: E402


# 覆盖必做项与选做项的测试表达式
REGEXES = [
    'a',
    'ab',
    'ab|c',
    'a*',
    'a+',
    'a?',
    'a|b',
    '(a|b)*abb',
    '(ab|a)*',
    '(a|b)*a(a|b)',
    'a*b*',
    '(aa|bb)*',
    'a?b+c*',
    '[abc]',
    '[a-c]x',
    '[a-zA-Z]',
    '[0-9]+',
    '0|1(0|1)*',
    'a(bb?)*',
    '(a|ε)b',
    '((a|b)(a|b))*',
]

# 小字母表的表达式，穷举时组合更充分
SMALL_ALPHABET_REGEXES = [
    'a',
    'ab',
    'a|b',
    'a*',
    'a+',
    'a?',
    'a*b?',
    '(a|b)*abb',
    '(ab|a)*',
    '(a|b)*',
    'a(ba)*',
    '[ab]+',
    '(a|ε)(b|ε)',
]


def _strings(alphabet, max_len):
    """按长度枚举字母表上的全部字符串。"""
    for length in range(max_len + 1):
        for tup in itertools.product(alphabet, repeat=length):
            yield ''.join(tup)


def _convert_to_python_regex(regex):
    """把本程序的语法翻译成 Python re 的等价写法，用于独立参照。

    预处理：浏览正则，把 α+ 改写为 (?:α)+、α? 改写为 (?:α)? 等，
    以避免 Python re 在量词作用对象上的差异。这里用后缀展开的技巧：
    直接把表达式交给本程序的语法树，然后按树生成 Python 正则，最可靠。
    """
    ast = xlex.parse_regex(regex)
    return _ast_to_python(ast)


def _ast_to_python(node):
    kind = node[0]
    if kind == 'eps':
        return '(?:)'
    if kind == 'char':
        return re.escape(node[1])
    if kind == 'class':
        return '[' + ''.join(re.escape(c) for c in sorted(node[1])) + ']'
    if kind == 'cat':
        return '(?:%s)(?:%s)' % (_ast_to_python(node[1]), _ast_to_python(node[2]))
    if kind == 'alt':
        return '(?:(?:%s)|(?:%s))' % (_ast_to_python(node[1]), _ast_to_python(node[2]))
    if kind == 'star':
        return '(?:%s)*' % _ast_to_python(node[1])
    if kind == 'plus':
        return '(?:%s)+' % _ast_to_python(node[1])
    if kind == 'opt':
        return '(?:%s)?' % _ast_to_python(node[1])
    raise AssertionError('未知结点 %r' % (kind,))


class TestEquivalence(unittest.TestCase):
    """NFA / DFA / 最小化 DFA 三者语言必须完全一致。"""

    def _check(self, regex, alphabet, max_len):
        compiled = xlex.compile_regex(regex)
        py_regex = re.compile(_convert_to_python_regex(regex))
        count = 0
        for text in _strings(alphabet, max_len):
            count += 1
            expect = py_regex.fullmatch(text) is not None
            self.assertEqual(
                xlex.nfa_accepts(compiled.nfa, text), expect,
                '%r 在 NFA 上判定错误：%r' % (regex, text))
            self.assertEqual(
                xlex.dfa_accepts(compiled.dfa, text), expect,
                '%r 在 DFA 上判定错误：%r' % (regex, text))
            self.assertEqual(
                xlex.dfa_accepts(compiled.mdfa, text), expect,
                '%r 在最小化 DFA 上判定错误：%r' % (regex, text))
        self.assertGreater(count, 0)

    def test_full_alphabet_against_python_re(self):
        for regex in REGEXES:
            with self.subTest(regex=regex):
                alphabet = xlex.compile_regex(regex).alphabet
                if len(alphabet) > 4:
                    alphabet = alphabet[:3]
                self._check(regex, alphabet, 4)

    def test_small_alphabet_exhaustive(self):
        for regex in SMALL_ALPHABET_REGEXES:
            with self.subTest(regex=regex):
                self._check(regex, 'ab', 5)


class TestStructure(unittest.TestCase):
    """关键结构断言：状态数、去重、最小性。"""

    def test_classic_regex_minimal_states(self):
        # (a|b)*abb 的经典最小 DFA 是 4 个状态
        compiled = xlex.compile_regex('(a|b)*abb')
        self.assertEqual(len(compiled.dfa), 5)
        self.assertEqual(len(compiled.mdfa), 4)

    def test_alphabet_is_deduplicated(self):
        # 原实现会得到 ['a','b','a','b','b']，这里必须是升序去重
        compiled = xlex.compile_regex('(a|b)*abb')
        self.assertEqual(compiled.alphabet, ['a', 'b'])

    def test_minimization_is_idempotent(self):
        for regex in REGEXES:
            with self.subTest(regex=regex):
                once = xlex.compile_regex(regex).mdfa
                twice = xlex.minimize_dfa(once)
                self.assertEqual(len(once), len(twice))
                alphabet = once.alphabet
                for text in _strings(alphabet[:3], 3):
                    self.assertEqual(xlex.dfa_accepts(once, text),
                                     xlex.dfa_accepts(twice, text))

    def test_minimal_is_truly_minimal(self):
        """最小化结果再最小化不会变少（等价于已是极小）。"""
        for regex in ['(a|b)*abb', '(ab|a)*', 'a?b+c*', '[0-9]+']:
            with self.subTest(regex=regex):
                mdfa = xlex.compile_regex(regex).mdfa
                self.assertEqual(len(xlex.minimize_dfa(mdfa)), len(mdfa))

    def test_plus_and_opt_semantics(self):
        # a+ 不接受空串，a? 接受空串和一个 a
        plus = xlex.compile_regex('a+')
        self.assertFalse(xlex.dfa_accepts(plus.mdfa, ''))
        self.assertTrue(xlex.dfa_accepts(plus.mdfa, 'a'))
        self.assertTrue(xlex.dfa_accepts(plus.mdfa, 'aaaa'))

        opt = xlex.compile_regex('a?')
        self.assertTrue(xlex.dfa_accepts(opt.mdfa, ''))
        self.assertTrue(xlex.dfa_accepts(opt.mdfa, 'a'))
        self.assertFalse(xlex.dfa_accepts(opt.mdfa, 'aa'))

    def test_epsilon_forms(self):
        for regex in ['ε', '~', r'\ε', '(ε)*']:
            with self.subTest(regex=regex):
                compiled = xlex.compile_regex(regex)
                self.assertTrue(xlex.dfa_accepts(compiled.mdfa, ''))
                self.assertEqual(len(compiled.mdfa), 1)

    def test_alt_with_epsilon_keeps_two_states(self):
        # 'a|ε' 里空串态与 'a' 态可区分（后者非终态），最小化后必须保留 2 个状态
        compiled = xlex.compile_regex('a|ε')
        self.assertEqual(len(compiled.mdfa), 2)
        self.assertTrue(xlex.dfa_accepts(compiled.mdfa, ''))
        self.assertTrue(xlex.dfa_accepts(compiled.mdfa, 'a'))
        self.assertFalse(xlex.dfa_accepts(compiled.mdfa, 'aa'))

    def test_explicit_concat_operator(self):
        for regex in ['a.b', 'a·b', 'ab']:
            with self.subTest(regex=regex):
                compiled = xlex.compile_regex(regex)
                self.assertTrue(xlex.dfa_accepts(compiled.mdfa, 'ab'))
                self.assertFalse(xlex.dfa_accepts(compiled.mdfa, 'a'))

    def test_tables_are_wellformed(self):
        compiled = xlex.compile_regex('(a|b)*abb')
        for table in (xlex.nfa_table(compiled.nfa),
                      xlex.dfa_table(compiled.dfa),
                      xlex.dfa_table(compiled.mdfa, show_nfa_sets=True)):
            headers, rows = table
            for row in rows:
                self.assertEqual(len(row), len(headers),
                                 '表头 %r 与行 %r 长度不一致' % (headers, row))

    def test_alphabet_symbol_table_lookup(self):
        compiled = xlex.compile_regex('[a-c]x')
        self.assertEqual(compiled.alphabet, ['a', 'b', 'c', 'x'])
        self.assertTrue(xlex.dfa_accepts(compiled.mdfa, 'bx'))
        self.assertFalse(xlex.dfa_accepts(compiled.mdfa, 'dx'))


class TestErrors(unittest.TestCase):
    """语法错误必须给出 RegexError，而不是崩栈。"""

    def test_bad_inputs(self):
        bad = [
            '',
            '(a',
            'a)',
            '|a',
            'a|',
            '*a',
            'a**b*',
            '[]',
            '[a-',
            '[z-a]',
            'a|(|b)',
            'a.',
            '.a',
            'a*+',
        ]
        for regex in bad:
            with self.subTest(regex=regex):
                with self.assertRaises(xlex.RegexError):
                    xlex.compile_regex(regex)

    def test_empty_class_message(self):
        with self.assertRaises(xlex.RegexError) as ctx:
            xlex.compile_regex('[]')
        self.assertIn('字符集为空', str(ctx.exception))


class TestScan(unittest.TestCase):
    """最长匹配与错误恢复。"""

    def test_longest_match(self):
        compiled = xlex.compile_regex('ab|a')
        tokens, errors = xlex.scan(compiled.mdfa, 'ab')
        self.assertEqual([t[0] for t in tokens], ['ab'])
        self.assertEqual(errors, [])

        tokens, errors = xlex.scan(compiled.mdfa, 'aab')
        self.assertEqual([t[0] for t in tokens], ['a', 'ab'])
        self.assertEqual(errors, [])

    def test_error_recovery(self):
        # 'ab' 在 'aXab' 上：a 无法构成完整词素 -> 报错；X 报错；第二个 ab 匹配成功
        compiled = xlex.compile_regex('ab')
        tokens, errors = xlex.scan(compiled.mdfa, 'aXab')
        self.assertEqual([t[0] for t in tokens], ['ab'])
        self.assertEqual([e[0] for e in errors], ['a', 'X'])

    def test_whitespace_skipped(self):
        compiled = xlex.compile_regex('[a-z]+')
        tokens, errors = xlex.scan(compiled.mdfa, '  abc  de ')
        self.assertEqual([t[0] for t in tokens], ['abc', 'de'])
        self.assertEqual(errors, [])

    def test_no_infinite_loop_on_empty_match(self):
        # a* 能匹配空串，扫描时必须跳过而不是死循环
        compiled = xlex.compile_regex('a*')
        tokens, errors = xlex.scan(compiled.mdfa, 'aab')
        self.assertEqual([t[0] for t in tokens], ['aa'])
        self.assertEqual([e[0] for e in errors], ['b'])


CC = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')


@unittest.skipUnless(CC, '系统没有 C 编译器，跳过端到端测试')
class TestCodegen(unittest.TestCase):
    """生成的 C 词法分析程序必须能编译、能运行、结果正确。"""

    def _build_and_run(self, regex, source_text, workdir):
        compiled = xlex.compile_regex(regex)
        code = xlex.generate_c(compiled.mdfa, regex)
        c_path = os.path.join(workdir, 'scanner.c')
        exe_path = os.path.join(workdir, 'scanner')
        with open(c_path, 'w', encoding='utf-8') as handle:
            handle.write(code)

        build = subprocess.run(
            [CC, '-std=c99', '-Wall', '-Wextra', '-O2', '-o', exe_path, c_path],
            capture_output=True, text=True)
        self.assertEqual(build.returncode, 0,
                         'C 编译失败：\n%s\n%s' % (build.stdout, build.stderr))
        self.assertEqual(build.stderr.strip(), '',
                         'C 编译出现告警：\n%s' % build.stderr)

        input_path = os.path.join(workdir, 'input.txt')
        with open(input_path, 'w', encoding='utf-8') as handle:
            handle.write(source_text)

        run = subprocess.run([exe_path, input_path], capture_output=True, text=True)
        self.assertIn(run.returncode, (0, 1),
                      'C 程序异常退出：%d\n%s' % (run.returncode, run.stderr))
        return run.stdout, compiled

    def _assert_scanner_matches_python(self, regex, source_text):
        with tempfile.TemporaryDirectory() as workdir:
            stdout, compiled = self._build_and_run(regex, source_text, workdir)
        tokens, errors = xlex.scan(compiled.mdfa, source_text)

        # C 程序按从左到右的流顺序输出，token 与 error 会交错，这里按位置合并
        events = [(start, '<TOKEN, %s, [%d,%d)>' % (lexeme, start, end))
                  for lexeme, start, end in tokens]
        events += [(pos, "<ERROR, '%s', pos=%d>" % (ch, pos)) for ch, pos in errors]
        events.sort(key=lambda item: item[0])
        expected = [text for _, text in events]
        expected.append('/* %d token(s), %d error(s) */' % (len(tokens), len(errors)))

        actual = [line for line in stdout.strip().splitlines()]
        self.assertEqual(actual, expected)

    def test_scanner_ab_or_c(self):
        self._assert_scanner_matches_python('ab|c', 'ab c ab\nc  X')

    def test_scanner_a_plus(self):
        self._assert_scanner_matches_python('a+', 'aaa a aa')

    def test_scanner_class(self):
        self._assert_scanner_matches_python('[a-z]+', 'int x = 42;  \nfoo')

    def test_scanner_single_char(self):
        self._assert_scanner_matches_python('a', 'aab')

    def test_scanner_classic_regex(self):
        self._assert_scanner_matches_python('(a|b)*abb', 'abb aab abb bba')

    def test_generated_code_contains_table(self):
        compiled = xlex.compile_regex('(a|b)*abb')
        code = xlex.generate_c(compiled.mdfa, '(a|b)*abb')
        self.assertIn('#define DFA_STATES  4', code)
        self.assertIn('#define DFA_SYMS    2', code)
        self.assertIn('match_longest', code)
        self.assertNotIn('cout', code)      # 原实现混用了 C++ 的 cout
        self.assertNotIn('@@', code)        # 模板占位符必须全部替换

    def test_quote_symbols_are_escaped(self):
        # 引号、反斜杠作为字母表符号时，必须正确转义/注释，C 代码仍可编译
        self._assert_scanner_matches_python('"|\\\\', '" \\ " ')


@unittest.skipUnless(xlex.TK_AVAILABLE, '当前 Python 没有 tkinter')
class TestGui(unittest.TestCase):
    """界面层测试：三张状态表都要真正填上内容，按钮回调不能抛异常。"""

    @classmethod
    def setUpClass(cls):
        import tkinter
        try:
            cls.root = tkinter.Tk()
        except tkinter.TclError as exc:      # 无显示环境
            raise unittest.SkipTest('无法创建 Tk 窗口：%s' % exc)
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        import tkinter
        for child in self.root.winfo_children():
            child.destroy()
        self.app = xlex.XlexApp(self.root)

    def _set_regex(self, regex):
        self.app.regex_var.set(regex)
        self.app.compiled = None

    def test_default_regex_is_compiled_by_run_all(self):
        self.app.run_all()
        self.assertIsNotNone(self.app.compiled)
        self.assertEqual(len(self.app.compiled.mdfa), 4)

    def test_all_three_tables_populated(self):
        self._set_regex('(a|b)*abb')
        self.app.run_all()
        for tree, expected_rows in ((self.app.tree_nfa, 14),
                                    (self.app.tree_dfa, 5),
                                    (self.app.tree_min, 4)):
            rows = tree.get_children()
            self.assertEqual(len(rows), expected_rows,
                             '表格行数不对：期望 %d，实际 %d' % (expected_rows, len(rows)))
            # 每行的单元格数必须与列数一致，否则表格会错位
            for item in rows:
                values = tree.item(item, 'values')
                self.assertEqual(len(values), len(tree['columns']),
                                 '行 %r 的单元格数与列数不一致' % (values,))

    def test_table_has_headers_and_values(self):
        self._set_regex('ab|c')
        self.app.on_nfa()
        tree = self.app.tree_nfa
        columns = tree['columns']
        self.assertGreaterEqual(len(columns), 4)   # 状态 + a + b + c + ε + 类型
        first = tree.item(tree.get_children()[0], 'values')
        self.assertTrue(str(first[0]).startswith('q'))

        self.app.on_min()
        tree = self.app.tree_min
        header_texts = [tree.heading(col, 'text') for col in tree['columns']]
        self.assertIn('对应 NFA 状态集', header_texts)

    def test_c_code_is_generated_into_text_widget(self):
        self._set_regex('ab|c')
        self.app.on_code()
        code = self.app.code_text.get('1.0', 'end')
        self.assertIn('match_longest', code)
        self.assertIn('DFA_STATES', code)
        self.assertNotIn('@@', code)
        self.assertEqual(code.rstrip(), self.app.c_code.rstrip())

    def test_bad_regex_shows_error_not_crash(self):
        self._set_regex('(a')
        from unittest import mock
        with mock.patch.object(xlex.messagebox, 'showerror') as showerror:
            # 走按钮回调的包装器，验证界面不会因语法错误崩掉
            self.app._guard(self.app.on_nfa)()
            self.assertTrue(showerror.called, '语法错误应当弹窗提示')
        self.assertIn('正则表达式错误', str(self.app.status.cget('text')))

    def test_start_and_accept_highlight_correct_rows(self):
        self._set_regex('ab|c')
        self.app.run_all()
        tree = self.app.tree_nfa
        headers, rows = xlex.nfa_table(self.app.compiled.nfa)
        marks_col = headers.index('类型')
        for item, row in zip(tree.get_children(), rows):
            tags = tree.item(item, 'tags')
            expected_start = '初态' in str(row[marks_col])
            expected_accept = '终态' in str(row[marks_col])
            self.assertEqual('start' in tags, expected_start,
                             '初态高亮错行：%r' % (row,))
            self.assertEqual('accept' in tags, expected_accept,
                             '终态高亮错行：%r' % (row,))

    def test_status_reports_state_counts(self):
        self._set_regex('(a|b)*abb')
        self.app.run_all()
        text = str(self.app.status.cget('text'))
        self.assertIn('NFA 14 态', text)
        self.assertIn('DFA 5 态', text)
        self.assertIn('最小化 DFA 4 态', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
