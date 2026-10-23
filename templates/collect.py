#!/usr/bin/env python3
"""收一个交回的对话：先关窗，再拿锁把结果记进状态文件，最后记一次顺利交回。

用法：python3 collect.py <页面编号> <dev|check|fix> [核对结论]
核对结论以「通过」开头的，页面记「核对通过，待主控抽查」，别的记「待返修」；开发和返修交回记「待核对」。
下一步照旧用 launchq.py add 排队。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dispatch as D  # noqa: E402

NAMES = {'dev': '开发', 'check': '核对', 'fix': '返修'}


def main():
    pid, kind = sys.argv[1], sys.argv[2]
    verdict = sys.argv[3] if len(sys.argv) > 3 else ''
    # 关窗要十几秒，只先看一眼派工号，不拿着状态等
    row = D.load()['pages'][pid][kind][-1]
    print(pid, NAMES[kind], '第', row.get('round') or 1, '轮', row['dispatch'], flush=True)
    if not row.get('released'):
        out = subprocess.run(['python3', os.path.join(HERE, 'dispatch.py'), 'close', row['dispatch']], capture_output=True, text=True)
        print(' ', (out.stdout + out.stderr).strip()[-120:])
    with D.locked():
        st = D.load()
        row = st['pages'][pid][kind][-1]
        row['released'] = '已交回，窗口已关'
        if kind == 'check':
            row['verdict'] = verdict
            status = '核对通过，待主控抽查' if verdict.startswith('通过') else '待返修'
        else:
            status = '待核对'
        st['pages'][pid]['status'] = status
        D.save(st)
    print(' ', '页面记成', status, flush=True)
    subprocess.run(['python3', os.path.join(HERE, 'launchq.py'), 'ok', pid, NAMES[kind]])


if __name__ == '__main__':
    main()
