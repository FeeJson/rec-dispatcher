#!/usr/bin/env python3
"""主控 10 秒一轮的监视：有事才打一行，给 Monitor 当事件流。

报四类事：
  完成   对话发来 worker_done、提问、上报（只看不确认，主控用 inbox.py 去收）
  掉线   在跑的对话终端里出现掉登录、接口报错，或者停下来空闲了却没交回
  网关   中转网关日志（环境变量 GATEWAY_LOG 指向的文件，没设就跳过这一类）里新出现清凭证、限流、非客户端、隧道断线
  启动失败 启动器起对话没成功（launch-failures.log）
同一件事只报一次。
"""
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ORCA = '/Applications/Orca.app/Contents/Resources/bin/orca'
# 网关日志路径从环境变量 GATEWAY_LOG 取。没设就是空串，下面各处 os.path.exists 判断为假，网关告警整段跳过
GATEWAY_LOG = os.path.expanduser(os.environ.get('GATEWAY_LOG', ''))
# 网关告警关键词：下面是通用例子（凭证缺失或被清、被限流、客户端被拒、隧道断线），按你自己的网关日志里真实出现的字样改
GATEWAY_WARN = re.compile(r'credential (missing|cleared)|rate.?limited|client rejected|tunnel error')
ROLE = {'dev': '开发', 'check': '核对', 'fix': '返修'}
FAILURES = os.path.join(HERE, 'launch-failures.log')


def orca_json(*args):
    out = subprocess.run([ORCA, *args, '--json'], capture_output=True, text=True)
    try:
        return json.loads(out.stdout).get('result') or {}
    except ValueError:
        return {}


def active_rows():
    """派工记录里还在跑的 Orca 对话：没停、没关窗、没交回"""
    state = json.load(open(os.path.join(HERE, 'dispatch-state.json'), encoding='utf-8'))
    rows = []
    for pid, p in state['pages'].items():
        for kind in ('dev', 'check', 'fix'):
            r = (p.get(kind) or [None])[-1]
            if r and r.get('dispatch') and not r.get('stopped') and not r.get('released'):
                rows.append((pid, kind, r))
    return rows


def main():
    seen = set()
    log_pos = os.path.getsize(GATEWAY_LOG) if os.path.exists(GATEWAY_LOG) else 0
    idle_since = {}
    fail_pos = os.path.getsize(FAILURES) if os.path.exists(FAILURES) else 0
    while True:
        # 新消息：只偷看不确认
        peek = orca_json('orchestration', 'check', '--peek')
        # 对话的心跳收下就确认掉：收件只等交回、提问、上报，心跳不确认会越攒越多，一直提醒
        # 取一批时 --types 不管用，会把交回、提问一起收走：所以只在队列里全是心跳时才取，取到的一批里有别的消息就不确认
        pending = peek.get('messages') or []
        if pending and all(m.get('type') == 'heartbeat' for m in pending):
            beats = orca_json('orchestration', 'check', '--types', 'heartbeat')
            got = beats.get('messages') or []
            if beats.get('deliveryId') and all(m.get('type') == 'heartbeat' for m in got):
                orca_json('orchestration', 'check', '--types', 'heartbeat', '--ack', beats['deliveryId'])
        for m in peek.get('messages') or []:
            if m.get('type') in ('worker_done', 'question', 'escalation') and m['id'] not in seen:
                seen.add(m['id'])
                print(f"完成 {m.get('type')} {m.get('subject', '')[:60]}", flush=True)
        # 在跑的对话：掉登录、报错、停住没交回
        for pid, kind, r in active_rows():
            read = orca_json('orchestration', 'worker-read', '--dispatch', r['dispatch'], '--source', 'terminal', '--limit', '200')
            tail = (read.get('terminal') or {}).get('tail') or []
            text = '\n'.join(tail[-40:])
            # 对话在等自己起的后台命令时界面是空闲的，底栏会写「1 shell」，也算在干活
            bottom = '\n'.join(tail[-6:])
            busy = 'esc to interrupt' in bottom or bool(re.search(r'\d+ shells?\b', bottom))
            key = f"{pid}-{kind}-{r['dispatch']}"
            if re.search(r'Not logged in|API Error|authentication_failed', text) and not busy and key + '掉线' not in seen:
                seen.add(key + '掉线')
                print(f"掉线 {pid} {ROLE[kind]} 终端里出现掉登录或接口报错", flush=True)
            if busy:
                idle_since.pop(key, None)
            else:
                idle_since.setdefault(key, time.time())
                if time.time() - idle_since[key] > 90 and key + '停住' not in seen:
                    seen.add(key + '停住')
                    print(f"停住 {pid} {ROLE[kind]} 空闲超过 90 秒还没交回", flush=True)
        # 启动器记下的启动失败
        if os.path.exists(FAILURES):
            size = os.path.getsize(FAILURES)
            if size > fail_pos:
                with open(FAILURES, encoding='utf-8', errors='ignore') as f:
                    f.seek(fail_pos)
                    for line in f:
                        print('启动失败 ' + line.strip()[:160], flush=True)
                    fail_pos = f.tell()
        # 网关日志新增的告警
        if os.path.exists(GATEWAY_LOG):
            size = os.path.getsize(GATEWAY_LOG)
            if size < log_pos:
                log_pos = 0
            with open(GATEWAY_LOG, encoding='utf-8', errors='ignore') as f:
                f.seek(log_pos)
                for line in f:
                    if GATEWAY_WARN.search(line):
                        print('网关 ' + line.strip()[:120], flush=True)
                log_pos = f.tell()
        time.sleep(10)


if __name__ == '__main__':
    main()
