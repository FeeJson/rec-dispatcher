#!/usr/bin/env python3
"""主控收件：等开发和核对对话的消息，按页面编号和角色打出要点。

用法：
  python3 inbox.py wait [超时毫秒]    等下一批（不确认）；打出这一批的消息和批次号
  python3 inbox.py next [超时毫秒]    先确认上一批（处理完才能用），再等下一批
心跳只计数不展开。批次号记在同目录 inbox-pending.txt。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORCA = '/Applications/Orca.app/Contents/Resources/bin/orca'
PENDING = os.path.join(HERE, 'inbox-pending.txt')


def who():
    """终端句柄、派工号 → 页面编号和角色"""
    state = json.load(open(os.path.join(HERE, 'dispatch-state.json'), encoding='utf-8'))
    by = {}
    for pid, kinds in state['pages'].items():
        for kind, rows in kinds.items():
            if not isinstance(rows, list):
                continue
            for i, r in enumerate(rows):
                label = f'{pid} {kind}#{i + 1}'
                for key in ('terminal', 'dispatch'):
                    if r.get(key):
                        by[r[key]] = label
    return by


def main():
    cmd = sys.argv[1]
    timeout = sys.argv[2] if len(sys.argv) > 2 else '540000'
    args = [ORCA, 'orchestration', 'check', '--wait', '--types', 'worker_done,escalation,question', '--timeout-ms', timeout, '--json']
    if cmd == 'next' and os.path.exists(PENDING):
        args += ['--ack', open(PENDING).read().strip()]
    out = subprocess.run(args, capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        print('读不出结果', out.returncode, out.stdout[-800:], out.stderr[-800:])
        return
    if cmd == 'next' and os.path.exists(PENDING):
        os.remove(PENDING)
    res = data.get('result') or {}
    delivery = res.get('deliveryId') or (res.get('delivery') or {}).get('id')
    msgs = res.get('messages') or []
    if delivery:
        open(PENDING, 'w').write(delivery)
    names = who()
    beats = 0
    print(f'批次 {delivery}，{len(msgs)} 条')
    for m in msgs:
        if m.get('type') == 'heartbeat':
            beats += 1
            continue
        payload = {}
        try:
            payload = json.loads(m.get('payload') or '{}')
        except ValueError:
            pass
        src = names.get(m.get('from_handle')) or names.get(payload.get('dispatchId')) or m.get('from_handle')
        print(f"\n[{m.get('type')}] {src} | {m.get('id')} | {m.get('subject', '')[:80]}")
        body = (m.get('body') or '').strip()
        if body:
            print('  ' + body[:900].replace('\n', '\n  '))
        keep = {k: v for k, v in payload.items() if k not in ('taskId',)}
        if keep:
            print('  ' + json.dumps(keep, ensure_ascii=False)[:600])
    print(f'\n心跳 {beats} 条')
    if not msgs and not delivery:
        print('没有新消息', json.dumps(res, ensure_ascii=False)[:400])


if __name__ == '__main__':
    main()
