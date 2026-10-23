#!/usr/bin/env python3
"""启动队列：所有要新起的对话都排进 launch-queue.jsonl，由这一个后台进程按顺序起，每个之间隔 70 秒。
经包装启动器或中转起 claude 时，有的包装启动器每次启动都会重写共用的登录凭证，几个挤在一起起会把正在发请求的对话打掉，所以只许这里一个一个起。

排队：python3 launchq.py add <页面编号> <dev|takeover|check|fix> [第几轮] [思考等级] [交接说明]
启动器：python3 launchq.py run（后台常驻，同一时间只能有一个）
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, 'launch-queue.jsonl')
DONE = os.path.join(HERE, 'launch-queue-done.txt')
GAP = 70
# 用户 2026-10-23 定：后台这一轮最多 15 个，从 5 起慢慢往上试，有问题或机器吃紧就往回减。
# 上限写在 launch-cap.txt，主控改这个文件就生效，不用重启启动器
CAP_FILE = os.path.join(HERE, 'launch-cap.txt')


def cap():
    try:
        return max(1, min(15, int(open(CAP_FILE).read().strip())))
    except (OSError, ValueError):
        return 5


def machine_ok():
    """机器吃紧就先不起新对话：内存剩不到 20%，或者 1 分钟负载超过 12（10 核）"""
    import subprocess
    try:
        out = subprocess.run(['memory_pressure'], capture_output=True, text=True, timeout=10).stdout
        free = int(out.strip().splitlines()[-1].split(':')[-1].strip().rstrip('%'))
    except Exception:
        free = 100
    load = os.getloadavg()[0]
    return free >= 20 and load <= 12, free, load


def active_isolated():
    st = D.load()
    n = 0
    for p in st['pages'].values():
        for kind in ('dev', 'check', 'fix'):
            for r in p.get(kind) or []:
                if r.get('launcher') == 'isolated' and not r.get('released') and not r.get('stopped'):
                    n += 1
    return n

sys.path.insert(0, HERE)
sys.argv = sys.argv[:1] + sys.argv[1:]
import dispatch as D  # noqa: E402


def jobs():
    if not os.path.exists(QUEUE):
        return []
    return [json.loads(x) for x in open(QUEUE, encoding='utf-8') if x.strip()]


def done_ids():
    return set(open(DONE).read().split()) if os.path.exists(DONE) else set()


def spec_of(job):
    pid, kind = job['pid'], job['kind']
    if kind == 'dev':
        return D.dev_spec(pid), f'{pid} 开发'
    if kind == 'takeover':
        return D.takeover_spec(pid, job.get('note') or '前一个对话停下了，已有的文件接着用。'), f'{pid} 接手开发'
    if kind == 'check':
        return D.check_spec(pid, job['round']), f"{pid} 核对第{job['round']}轮"
    if kind == 'fix':
        return D.fix_spec(pid, job['round']), f"{pid} 返修第{job['round']}轮"
    raise ValueError(kind)


def run():
    last = 0
    held = False
    while True:
        pending = [j for j in jobs() if j['id'] not in done_ids()]
        # 核对、返修排在开发前面：一页早点核完能早点进外壳，各页共有的问题也能早点发现；同一类里照排队先后
        pending.sort(key=lambda j: 0 if j['kind'] in ('check', 'fix') else 1)
        ok, free, load = machine_ok() if pending and time.time() - last >= GAP and active_isolated() < cap() else (False, 0, 0)
        if pending and time.time() - last >= GAP and active_isolated() < cap() and not ok and not held:
            held = True
            print(time.strftime('%H:%M:%S'), f'机器吃紧（内存剩 {free}%，负载 {load:.1f}），先不起新对话', flush=True)
        if ok and held:
            held = False
            print(time.strftime('%H:%M:%S'), f'机器缓过来了（内存剩 {free}%，负载 {load:.1f}），接着起', flush=True)
        if ok:
            job = pending[0]
            spec, title = spec_of(job)
            effort = job.get('effort') or D.PAGES[job['pid']][3]
            model = D.MODELS[job.get('model') or 'opus']
            r = D.start(spec, title, effort, model=model)
            # 起对话要几十秒，起完再读状态：先读后写会把这段时间里主控写进去的改动盖掉（2026-10-22 21:21 C07 核对那行就这样丢过）
            # 读到写之间拿着锁，主控用 collect.py 收交回时会等这边写完
            with D.locked():
                st = D.load()
                kind = {'takeover': 'dev'}.get(job['kind'], job['kind'])
                row = D.record(st, job['pid'], kind, r, effort=effort, model=model, round=job.get('round'), takeover=job['kind'] == 'takeover')
                st['pages'][job['pid']]['status'] = {'dev': 'Orca 开发中', 'takeover': 'Orca 接手中', 'check': '核对中', 'fix': '返修中'}[job['kind']]
                D.save(st)
            open(DONE, 'a').write(job['id'] + '\n')
            last = time.time()
            print(time.strftime('%H:%M:%S'), '起了', title, f'（{model} {effort}）', '成功' if row['ok'] else '失败 ' + row.get('error', '')[:200], flush=True)
            # 启动失败另记一份，watch.py 盯着这个文件报给主控
            if not row['ok']:
                open(FAILURES, 'a', encoding='utf-8').write(time.strftime('%H:%M:%S') + ' ' + title + ' ' + row.get('error', '')[:300] + '\n')
            n, changed = check_raise()
            print(f'  已连续起 {n} 个，上限 {cap()}', flush=True)
        time.sleep(5)


def add(args):
    pid, kind = args[0], args[1]
    job = {'id': f'{pid}-{kind}-{int(time.time() * 1000)}', 'pid': pid, 'kind': kind}
    if len(args) > 2 and args[2]:
        job['round'] = int(args[2])
    if len(args) > 3 and args[3]:
        # 写成 sonnet:high 就连模型一起定；只写 high 还是 Opus
        model, _, effort = args[3].rpartition(':')
        job['effort'] = effort
        if model:
            if model not in D.MODELS:
                raise SystemExit(f'不认识的模型 {model}，只能是 {"、".join(D.MODELS)}')
            job['model'] = model
    if len(args) > 4 and args[4]:
        job['note'] = args[4]
    open(QUEUE, 'a', encoding='utf-8').write(json.dumps(job, ensure_ascii=False) + '\n')
    waiting = len([j for j in jobs() if j['id'] not in done_ids()])
    print('已排队', job['id'], '前面还有', waiting - 1, '个')


STABLE = os.path.join(HERE, 'stability.json')
FAILURES = os.path.join(HERE, 'launch-failures.log')
# 凭证变动日志：自己写个脚本盯共用登录凭证文件，变一次记一行，行首是 HH:MM:SS 时间。没有这种日志就保持指向不存在的文件，只是少一项统计
CREDWATCH = '<临时目录>/credwatch.log'


def isolated_launches():
    st = D.load()
    return sum(1 for p in st['pages'].values() for k in ('dev', 'check', 'fix') for r in p.get(k) or [] if r.get('launcher') == 'isolated')


def check_raise():
    """加量：连续起满 5 个零掉线升到 10，起满 15 个升到 15（用户 2026-10-23 定最多 15）"""
    s = json.load(open(STABLE, encoding='utf-8'))
    n = isolated_launches() - s.get('启动计数起点', 0)
    since = s.get('凭证起算', '19:33:00')
    changed = [x for x in open(CREDWATCH, encoding='utf-8') if x[:8] > since] if os.path.exists(CREDWATCH) else []
    # 用户亲自定了上限（stability.json 里写了「用户定上限」）就不再自动加量：2026-10-23 06:30 用户令降到 5
    if s.get('用户定上限'):
        return n, len(changed)
    for need, to in ((5, 10), (15, 15)):
        if n >= need and cap() < to:
            open(CAP_FILE, 'w').write(str(to))
            print(time.strftime('%H:%M:%S'), f'已连续起 {n} 个、零掉线，上限调到 {to}', flush=True)
    return n, len(changed)


def stable(event, who):
    """稳定计数：ok 是新方式起的对话顺利交回一次，drop 是有对话掉线或被打断（清零重来）"""
    s = json.load(open(STABLE, encoding='utf-8'))
    if event == 'ok':
        s['顺利交回'] += 1
    else:
        s['顺利交回'] = 0
        s['掉线或打断'] += 1
        s['启动计数起点'] = isolated_launches()
        s['凭证起算'] = time.strftime('%H:%M:%S')
        open(CAP_FILE, 'w').write('5')
    s.setdefault('记录', []).append(time.strftime('%H:%M:%S') + ' ' + event + ' ' + who)
    json.dump(s, open(STABLE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    hint = ''
    print(f"顺利交回 {s['顺利交回']}/{s['目标']}，累计掉线或打断 {s['掉线或打断']}{hint}")


if __name__ == '__main__':
    if sys.argv[1] in ('ok', 'drop'):
        stable(sys.argv[1], ' '.join(sys.argv[2:]))
    elif sys.argv[1] == 'run':
        run()
    elif sys.argv[1] == 'add':
        add(sys.argv[2:])
