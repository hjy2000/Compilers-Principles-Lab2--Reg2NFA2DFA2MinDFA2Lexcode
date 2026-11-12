#!/bin/sh
# XLEX 启动脚本
#
# macOS 自带的 /usr/bin/python3 链接的是 Apple 的 Tk 8.5（2011 年版本），
# 在 macOS 10.14 之后存在已知缺陷：窗口能打开、标题正常，但内容整片空白。
# 本脚本会按顺序挑一个 Tk >= 8.6 的 Python 来运行 xlex.py。
#
# 用法：
#   ./run.sh                                  启动图形界面
#   ./run.sh --regex '(a|b)*abb' --dump       直接传给 xlex.py 的命令行参数

set -e
cd "$(dirname "$0")"

# 判断某个解释器的 Tk 版本是否 >= 8.6（同时要求能 import tkinter）
tk_ok() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys, tkinter
sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)
PY
}

# 候选解释器：优先 uv 托管的高版本 Python，再试常见的 homebrew / python.org 路径，
# 最后才试系统 python3。
for candidate in \
    "${XLEX_PYTHON:-}" \
    "$(command -v python3.13 2>/dev/null || true)" \
    "$(command -v python3.12 2>/dev/null || true)" \
    "$(command -v python3.11 2>/dev/null || true)" \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    "$(command -v python3 2>/dev/null || true)"
do
    [ -n "$candidate" ] || continue
    [ -x "$candidate" ] || continue
    if tk_ok "$candidate"; then
        exec "$candidate" "$(dirname "$0")/xlex.py" "$@"
    fi
done

# 没找到合适的解释器；如果装了 uv，就用它临时拉一个带 Tk 8.6 的 Python
if command -v uv >/dev/null 2>&1; then
    echo "未找到 Tk >= 8.6 的 Python，使用 uv 提供的 Python 3.13 运行。" >&2
    exec uv run --quiet --python 3.13 python "$(dirname "$0")/xlex.py" "$@"
fi

cat >&2 <<'EOF'
错误：没有找到 Tk >= 8.6 的 Python 解释器。

macOS 自带的 /usr/bin/python3 使用 Tk 8.5，界面会显示为空白。
请任选一种方式安装新版 Python：

  1) 使用 uv（推荐，无需管理员权限）：
       curl -LsSf https://astral.sh/uv/install.sh | sh
       uv python install 3.13
     然后重新运行 ./run.sh

  2) 使用 Homebrew：
       brew install python@3.13 python-tk@3.13
     然后重新运行 ./run.sh

  3) 从 python.org 下载安装包（自带 Tk 8.6）：
       https://www.python.org/downloads/macos/
EOF
exit 1
