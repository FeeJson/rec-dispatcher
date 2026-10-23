#!/usr/bin/env python3
"""小程序剩余页面还原的派工脚本：开发对话、核对对话、返修都从这里派，状态记在同目录 dispatch-state.json。

用法：
  python3 dispatch.py run                    建 Run（已有就跳过）
  python3 dispatch.py dev C06 C10 …          派开发对话
  python3 dispatch.py check C06 [第几轮]      派核对对话
  python3 dispatch.py fix C06                 把核对结论发回开发对话返修（复用它的终端）
  python3 dispatch.py show                    看每页走到哪一步
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'dispatch-state.json')
ORCA = '/Applications/Orca.app/Contents/Resources/bin/orca'
MODEL = 'claude-opus-5-5'
# 按活的难易换模型（用户 2026-10-23 06:40 准许）：排队时写 sonnet:high 这样，不写就是 Opus
MODELS = {'opus': 'claude-opus-5-5', 'sonnet': 'claude-sonnet-5-5', 'haiku': 'claude-haiku-5-5'}
# 带尖括号的是占位，换成你自己的路径：<项目根> 项目根目录，<迭代目录> 项目根下放这一轮材料的目录，<任务目录> 任务目录（相对项目根）
# 下面各个提示词和 PAGES 线索里出现的同名占位也一起换
TOOLS = '<项目根>/<迭代目录>/还原工具'
DEV_BRIEF = f'{TOOLS}/brief-后台页面还原.md'
CHECK_BRIEF = f'{TOOLS}/brief-后台页面核对.md'
TASK = '<任务目录>'

# 页面编号、页面名、模块、路由（admin-web 的 .umirc.ts）、开发思考等级、本页线索
PAGES = {
    'A-login': ('登录与改密', '外壳与登录', 'login', 'xhigh',
                '登录页 pages/login.tsx（验证码、密码错、账号锁定、首次登录强制改密跳改密页）和改密页 pages/change-password.tsx 两个路由，主路由写 login，改密写进 alsoRoutes。没登录的状态清单写 login: false；强制改密在状态里覆盖 /api/admin/auth/me 的 isForcePwdChange。'),
    'A-shell': ('外壳与工作台', '外壳与登录', '', 'xhigh',
                '外壳本身：components/AdminLayout.tsx（侧栏六个目录、展开收起、顶栏、登录人、退出）、PageTabs.tsx 和 usePageTabs.ts（多页签、上限 20、超限提示、全部关闭、保活），首页工作台 pages/home.tsx、找不到的路由 placeholder.tsx。路由写空串（首页）；开了多个页签的状态用清单的 tabs。'),
    'T01': ('讲师档案与入口码', '讲师产品中心', 'lecturer/profile', 'xhigh',
            '列表、新增编辑弹窗 components/LecturerEditorModal.tsx、详情弹窗、入口码弹窗 LecturerEntryCodeModal.tsx（复制小程序路径、刷新码图）、变更日志 LecturerChangeLogModal.tsx。'),
    'T02': ('产品与权益配置', '讲师产品中心', 'lecturer/product', 'max',
            '产品列表、产品编辑弹窗 components/ProductEditorModal.tsx（760 行，体验价、立减、权益、课程级别）、变更日志，以及页内的权益字典 BenefitDictPanel、课程级别 CourseLevelPanel、标签 TagManagePanel 三块。'),
    'C01': ('每日资讯发布管理', '内容服务中心', 'content/publish', 'max',
            '列表加内容编辑器 components/ContentEditorModal.tsx（2140 行，块编辑：段落、引用、列表、图片、插入搜索）、发布日志 ContentLogModal.tsx。编辑器状态多，挑运营常用的路径做全：新建、编辑、各种块、校验、保存失败、发布。保存时服务端会转义文本（admin-api 的 ContentBlockValidator.escapeText），和小程序显示对一下。'),
    'C02': ('第三方课程平台资源绑定', '内容服务中心', 'content/course', 'max',
            'pages/content/course.tsx 1430 行：课程资源列表、绑定产品、第三方课程平台任务 ThirdPartyTaskPanel、登录第三方课程平台（window.open 原型里不打开，记下即可）。'),
    'R01': ('用户档案', '会员准入规则管理', 'access/user', 'xhigh', '用户列表、详情；用户赵强 U100001 的资料和小程序一致。'),
    'R02': ('会员测评题库', '会员准入规则管理', 'access/question', 'xhigh', '题目列表、编辑、历史版本。题目改一次就换新 id，小程序测评交卷会报「作答与当前题目不一致」（小程序 C18 第 6 条），后台这边看有没有提示运营。'),
    'R03': ('等级与匹配规则', '会员准入规则管理', 'access/match', 'xhigh', '用户等级区间、等级与课程级别匹配表（init.sql 1840 行起）、保存整表替换、L1 只许 K1 的限制、历史记录。小程序测评结果页「适合购买」写死不跟这里（小程序 C19 第 10 条）。'),
    'R04': ('测评记录', '会员准入规则管理', 'access/assessment', 'high', '测评记录列表、筛选、详情。'),
    'D01': ('订单管理', '交易结算管理', 'trade/order', 'xhigh', '订单列表（19 列，更多筛选）、详情、发货异常、支付异常、第三方课程平台任务明细。加载中线上直接显示「没有符合筛选条件的订单」、网关出错显示英文原文，这两条先回代码确认。订单 900001 和小程序一致。'),
    'D02': ('退款处理', '交易结算管理', 'trade/refund', 'max', 'pages/trade/refund.tsx 930 行：退款单列表、审核通过驳回、残值退款、撤权。退款来源 customer、残值、线下几种（小程序 C23 第 1 条：小程序认 c23、服务端已改 customer）。'),
    'D03': ('业绩与分润', '交易结算管理', 'trade/settlement', 'xhigh', '业绩汇总、分润明细、筛选、导出（原型不下载，记下即可）。'),
    'O01': ('首页配置', '小程序运营配置', 'ops/home', 'max',
            'pages/ops/home/ 下六个页签，本页只做前四个：快捷入口 entry.tsx、Banner banner.tsx、身份条 identity.tsx、企微公告 wecom-notice.tsx。默认头像页签归 O05、免责文案页签归 O10，别的对话在做，本页不做。配的内容对一下小程序首页 C03 怎么显示。'),
    'O02': ('数据看板数据', '小程序运营配置', 'ops/dashboard', 'xhigh', '看板数据维护、导入、指标；对一下小程序 C10 数据看板怎么显示（C10 第 6 条学习时长单位）。'),
    'O03': ('企微客服入口', '小程序运营配置', 'ops/wechat', 'xhigh', '平台客服和学习顾问的企微二维码配置；对一下小程序 C11 加企微怎么显示。'),
    'O04': ('订阅消息配置', '小程序运营配置', 'ops/subscribe', 'xhigh', '订阅消息场景和模板配置，场景照上线种子（C16_PAY 等，卡片跳转路径可改：小程序 C16 第 12 条）。'),
    'O05': ('默认头像', '小程序运营配置', 'ops/home', 'high', '只做首页配置里的「默认头像」页签 pages/ops/home/avatar.tsx：状态先用 steps 点到这个页签。其余页签归 O01、O10。对一下小程序 C21av 头像选择怎么显示。'),
    'O06': ('关于我们配置', '小程序运营配置', 'ops/about', 'high', '关于我们内容配置；对一下小程序 C25 关于我们怎么显示。'),
    'O07': ('搜索配置', '小程序运营配置', 'ops/search', 'high', '常用关键词配置；对一下小程序 C06 每日资讯搜索（「全局推荐」）怎么显示。A-shell 核对发现本页没权限（403）时表格显示空数据提示，回代码确认。'),
    'O08': ('服务号消息', '小程序运营配置', 'ops/mp-message', 'xhigh', '服务号消息模板和发送记录。'),
    'O09': ('第三方课程平台账号核对', '小程序运营配置', 'ops/thirdparty-reconcile', 'xhigh', '第三方课程平台账号和用户的核对、差异处理。'),
    'O10': ('免责文案', '小程序运营配置', 'ops/home', 'high', '只做首页配置里的「免责文案」页签 pages/ops/home/disclaimer.tsx：状态先用 steps 点到这个页签。七个场景照上线种子，对一下小程序各页底部免责怎么显示（小程序 C08、C09 播放时看不到免责）。'),
    'S01': ('账号管理', '系统权限管理', 'system/account', 'max', 'pages/system/account.tsx 880 行：账号列表、新增编辑、重置密码、锁定解锁、启停、分配角色。预置账号 A001 照上线种子。'),
    'S02': ('账号动作留痕', '系统权限管理', 'system/account-trace', 'xhigh', '账号动作和全站操作记录、筛选、详情弹窗 ActionLogDetailModal.tsx。'),
    'S03': ('角色列表与预置角色', '系统权限管理', 'system/role', 'xhigh', '角色列表、预置三角色（超管、运营、财务，上线种子）、新增编辑、启停、授权。菜单管理、菜单级权限是另外两个路由，归 S04、S05，本页不做；角色页里没有它们的页签（种子注释写有，线上没有）。'),
    'S04': ('菜单管理', '系统权限管理', 'system/menu', 'xhigh', '菜单树（上线种子 6 个目录、27 个叶子，其中 5 个不占侧栏）、编辑、显隐。路由 system/menu；它自己在种子里也不占侧栏，角色页也没有页签（种子注释写有，线上没有），界面上没有入口，进页靠网址。'),
    'S05': ('菜单级权限', '系统权限管理', 'system/menu-permission', 'high', '按角色勾菜单授权（超管全选不可取消）。路由 system/menu-permission；和菜单管理一样，种子里不占侧栏（种子 init.sql:1990，侧栏只画显示的项 AdminLayout.tsx:132），角色页也没有页签，界面上没有入口，进页靠网址。这件事 S04 开发报告已列进要用户定，本页照它的说法写，不另算。'),
}


def load():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding='utf-8'))
    return {'run': None, 'pages': {}}


def save(state):
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


@contextmanager
def locked():
    """读、改、写状态文件都放进这把锁，一口气做完，中间别等起对话、关窗这类慢命令。
    主控曾经先读状态、等关窗十几秒、再整份写回，把这段时间里启动器记的 O08 第 2 轮核对冲掉了（2026-10-23 03:09）"""
    with open(STATE + '.lock', 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def orca(*args):
    out = subprocess.run([ORCA, *args, '--json'], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        data = {'ok': False, 'raw': out.stdout[-2000:], 'stderr': out.stderr[-2000:]}
    data['_exit'] = out.returncode
    return data


def dig(data, *keys):
    """receipt 的字段层级随版本会变，按候选路径逐个找"""
    for path in keys:
        cur = data
        for k in path.split('.'):
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is not None:
            return cur
    return None


def dev_spec(pid):
    name, module, route, _, note = PAGES[pid]
    return '\n'.join([
        f'Active task: {TASK}',
        f'【开发】管理后台页面还原：{pid} {name}',
        '',
        f'目标：按线上代码把管理后台「{pid} {name}」还原成离线原型页。模块「{module}」，路由「{route}」（代码在 <项目根>/admin-web/src，路由表见 admin-web/.umirc.ts）。',
        f'做法：先完整读开发规则 {DEV_BRIEF} 和工具说明 {TOOLS}/admweb/README.md，从头到尾照它做。用户要求真的核对源码，每个状态、每条问题都要指到 文件:行号。',
        f'本页线索（只当线索，都要回代码确认）：{note}' if note else '本页线索：无，按规则从代码列全部分支。',
        f'只写：admweb/specs/{pid}-proto.json、原型目录 管理后台/{pid}/、reports/后台-{pid}-开发报告.md。工具文件按规则里的锁和记录改。不动 mini-app、admin-web、server、管理后台/_app、外壳 index.html、说明.txt、别的页。',
        '验收：规则「自检」四项全部通过；开发报告写好；最后 worker_done --outcome succeeded --report-path <报告路径>。',
        '不要走 Trellis 流程，不要派子代理；非问不可的用派工说明里的 ask 问主控。',
    ])


def check_spec(pid, round_no):
    name, module, route, _, _ = PAGES[pid]
    return '\n'.join([
        f'Active task: {TASK}',
        f'【核对】管理后台页面还原：{pid} {name}（第 {round_no} 轮）',
        '',
        f'目标：独立核对开发对话做的管理后台「{pid} {name}」。路由「{route}」（代码在 <项目根>/admin-web/src）。',
        f'做法：先完整读核对规则 {CHECK_BRIEF}，再读它要求读的开发规则，照着逐项核对。先自己读代码列分支和问题，再看开发报告 reports/后台-{pid}-开发报告.md。',
        '只查不改：页面的清单、导出产物、配置一律不动。如果前一个核对对话做到一半掉线、核对结论里已有这一轮的半截内容，接着写完。',
        f'只写：reports/后台-{pid}-核对.md（已有就在末尾追加第 {round_no} 轮）。',
        '验收：核对结论写好；最后 worker_done --outcome succeeded --report-path <核对结论路径>，摘要第一句写「通过」或「不通过，必须改 N 条」。',
        '不要走 Trellis 流程，不要派子代理；非问不可的用派工说明里的 ask 问主控。',
    ])


def fix_spec(pid, round_no):
    name = PAGES[pid][0]
    return '\n'.join([
        f'Active task: {TASK}',
        f'【返修】管理后台页面还原：{pid} {name}（核对第 {round_no} 轮没通过）',
        '',
        f'先完整读开发规则 {DEV_BRIEF}，再读开发报告 {TOOLS}/reports/后台-{pid}-开发报告.md、这一页的清单和配置，弄清现在做到哪了。你说的每一句话都只用中文。',
        f'核对结论在 {TOOLS}/reports/后台-{pid}-核对.md，看最后一轮。照缺陷清单逐条改，「必须改」全部改掉，「建议改」能改的都改。新增的线上问题都要回代码确认 文件:行号、做正确样子。',
        f'改完重新跑开发规则 {DEV_BRIEF} 里「自检」五项，开发报告末尾追加「返修第 {round_no} 轮」写每条怎么改的。',
        '如果前一个返修对话改到一半掉线了，先看清单、配置、报告现在的样子，已经改好的不要重复改，接着改没改完的。',
        '对某条缺陷有不同意见的，不要硬改，在报告里写明理由。',
        '验收：最后 worker_done --outcome succeeded --report-path <开发报告路径>。',
    ])


def takeover_spec(pid, note):
    name, module, route, _, _ = PAGES[pid]
    return '\n'.join([
        f'Active task: {TASK}',
        f'【接手】管理后台页面还原：{pid} {name}（前一个对话做到一半掉线了）',
        '',
        f'模块「{module}」，路由「{route}」（代码在 <项目根>/admin-web/src）。',
        f'先完整读开发规则 {DEV_BRIEF}，再看这一页已经有的东西：admweb/specs/{pid}-proto.json、原型目录 管理后台/{pid}/、reports/后台-{pid}-开发报告.md（有的话）。接着做完，不要从零重来；已有的状态和数据要回代码核对，不对的照规则改。',
        f'前一个对话交接的话：{note}',
        '用户要求：真的核对源码，每个演示状态、每条线上问题都要指到 文件:行号。你说的每一句话都只用中文。',
        f'只写：admweb/specs/{pid}-proto.json、原型目录 管理后台/{pid}/、reports/后台-{pid}-开发报告.md。工具文件按规则里的锁和记录改。不动 mini-app、admin-web、server、管理后台/_app、外壳 index.html、说明.txt、别的页。',
        '验收：规则「自检」四项全部通过；开发报告写好；最后 worker_done --outcome succeeded --report-path <报告路径>。',
        '不要走 Trellis 流程，不要派子代理；非问不可的用派工说明里的 ask 问主控。',
    ])


# 工作区编号只从环境变量 ORCA_WORKTREE_ID 取，不给默认值：Orca 主控终端里自带这个变量，值就是文件夹工作区编号
if not os.environ.get('ORCA_WORKTREE_ID'):
    raise SystemExit('缺环境变量 ORCA_WORKTREE_ID。Orca 主控终端里自带这个变量；在别的终端里运行，先 export ORCA_WORKTREE_ID=<文件夹工作区编号>')
WORKSPACE = 'id:' + os.environ['ORCA_WORKTREE_ID']
# 起 claude 的命令从环境变量 CLAUDE_LAUNCH_CMD 取，不设就是 claude。
# 经启动器或中转起 claude 的人，在这里填独立启动脚本（带令牌、不读共用凭证），原因见下面 start 的说明
LAUNCH_CMD = os.environ.get('CLAUDE_LAUNCH_CMD', 'claude')


def start(spec, title, effort, terminal=None, model=MODEL):
    """派一个对话。新对话用独立启动脚本起（环境变量 CLAUDE_LAUNCH_CMD，不设就是 claude）：带着令牌（环境变量 CLAUDE_CODE_OAUTH_TOKEN）直接起 claude，
    会话不读共用凭证、启动时也不删补共用凭证，请求照样走原来的中转。2026-10-22 实测：有的包装启动器每次启动都会删一次、补一次共用凭证，
    正在读凭证的会话就掉登录；这类启动器还会去掉 CLAUDE_CODE_OAUTH_TOKEN，所以独立启动脚本不能经过它。
    以前直接用包装启动器起：它先同步登录再起 claude；不用 Orca 自带的 claude 启动，
    后者多开时会把本机共用的登录凭证清掉，别的对话跟着报 Not logged in。
    步骤：在本文件夹工作区开终端跑独立启动脚本 → 等界面空闲 → 把任务派进这个终端，Orca 照样管它的 worker_done。"""
    if not terminal:
        made = orca('terminal', 'create', '--worktree', WORKSPACE, '--title', title,
                    '--command', f'{LAUNCH_CMD} --dangerously-skip-permissions --model {model} --effort {effort}')
        terminal = dig(made, 'result.terminal.handle')
        if not terminal:
            return {'_exit': 1, 'stage': 'terminal create', 'detail': made}
        ready = orca('terminal', 'wait', '--terminal', terminal, '--for', 'tui-idle', '--timeout-ms', '120000')
        if not ready.get('ok'):
            return {'_exit': 1, 'stage': 'terminal wait', 'terminal': terminal, 'detail': ready}
    r = orca('orchestration', 'worker-start', '--spec', spec, '--task-title', title, '--worktree', WORKSPACE, '--terminal', terminal)
    # 2026-10-22 20:46、20:47 两次：终端里 claude 界面已经起来，Orca 还没认出是对话，派任务报 agent_unconfigured。
    # 隔 10 秒再派，最多再试 6 次
    for _ in range(6):
        if dig(r, 'error.code') != 'agent_unconfigured':
            break
        time.sleep(10)
        r = orca('orchestration', 'worker-start', '--spec', spec, '--task-title', title, '--worktree', WORKSPACE, '--terminal', terminal)
    r['_terminal'] = terminal
    return r


def find_id(obj, prefix):
    """回执结构随启动方式不同，按前缀在整个回执里找第一个派工号（ctx_）或任务号（task_）"""
    import re
    m = re.search(r'"(' + prefix + r'[0-9a-f]{6,})"', json.dumps(obj))
    return m.group(1) if m else None


def record(state, pid, kind, receipt, **extra):
    row = {
        'at': datetime.now().strftime('%H:%M:%S'),
        'ok': receipt.get('_exit') == 0,
        'task': dig(receipt, 'result.task.id', 'result.taskId', 'result.task_id') or find_id(receipt, 'task_'),
        'dispatch': dig(receipt, 'result.dispatch.id', 'result.dispatchId', 'result.dispatch_id') or find_id(receipt, 'ctx_'),
        'terminal': receipt.get('_terminal') or dig(receipt, 'result.worker.agentTerminalHandle', 'result.dispatch.assigneeHandle', 'result.terminal.handle'),
        'launcher': 'isolated' if not receipt.get('_reused') else 'reused',
        'launch': dig(receipt, 'result.launch', 'result.dispatch.launch'),
        **extra,
    }
    # 启动回执里没有终端句柄时，按派工号再查一次
    if row['ok'] and not row['terminal'] and row['dispatch']:
        shown = orca('orchestration', 'worker-show', '--dispatch', row['dispatch'])
        row['terminal'] = dig(shown, 'result.worker.agentTerminalHandle', 'result.dispatch.assigneeHandle', 'result.terminal.handle')
    if not row['ok']:
        row['error'] = json.dumps(receipt, ensure_ascii=False)[:1500]
    state['pages'].setdefault(pid, {}).setdefault(kind, []).append(row)
    save(state)
    return row


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    state = load()
    if cmd == 'run':
        if state['run']:
            print('已有 Run', state['run'])
            return
        r = orca('orchestration', 'run-create', '--objective', '小程序端剩余 22 页按线上代码还原：每页一个开发对话，核对对话逐页核对，不合格返修')
        state['run'] = dig(r, 'result.run.id', 'result.runId', 'result.id')
        save(state)
        print(json.dumps(r, ensure_ascii=False)[:800])
    elif cmd == 'dev':
        for pid in args:
            r = start(dev_spec(pid), f'{pid} 开发', PAGES[pid][3])
            row = record(state, pid, 'dev', r, effort=PAGES[pid][3])
            print(pid, '开发', '已起' if row['ok'] else '失败', row.get('terminal'), row.get('launch') or '', row.get('error', '')[:300])
    elif cmd == 'check':
        pid = args[0]
        round_no = int(args[1]) if len(args) > 1 else len(state['pages'].get(pid, {}).get('check', [])) + 1
        r = start(check_spec(pid, round_no), f'{pid} 核对第{round_no}轮', 'xhigh')
        row = record(state, pid, 'check', r, round=round_no)
        print(pid, '核对', round_no, '已起' if row['ok'] else '失败', row.get('terminal'), row.get('error', '')[:300])
    elif cmd == 'fix':
        pid = args[0]
        dev = state['pages'][pid]['dev'][-1]
        round_no = len(state['pages'][pid].get('check', []))
        r = start(fix_spec(pid, round_no), f'{pid} 返修第{round_no}轮', None, terminal=dev['terminal'])
        row = record(state, pid, 'fix', r, round=round_no)
        print(pid, '返修', round_no, '已起' if row['ok'] else '失败', row.get('error', '')[:300])
    elif cmd == 'takeover':
        # 子代理做到一半掉线：起 Orca 对话接着做；args：页面编号 交接说明 [思考等级]
        pid, note = args[0], args[1]
        effort = args[2] if len(args) > 2 else PAGES[pid][3]
        r = start(takeover_spec(pid, note), f'{pid} 接手开发', effort)
        row = record(state, pid, 'dev', r, effort=effort, takeover=True)
        print(pid, '接手', '已起' if row['ok'] else '失败', row.get('terminal'), row.get('error', '')[:300])
    elif cmd == 'fixnew':
        # 开发是子代理做的、没有终端可复用时，起一个新的 Orca 对话按开发报告和核对结论返修
        pid = args[0]
        effort = args[1] if len(args) > 1 else PAGES[pid][3]
        round_no = len(state['pages'][pid].get('check', []))
        r = start(fix_spec(pid, round_no), f'{pid} 返修第{round_no}轮', effort)
        row = record(state, pid, 'fix', r, round=round_no, effort=effort)
        print(pid, '返修', round_no, '已起' if row['ok'] else '失败', row.get('terminal'), row.get('error', '')[:300])
    elif cmd == 'resume':
        # 掉登录的对话发一句「继续」接着干；被 agent_prompt_blocked 拦下时按回执里的请求号原样再发一次
        for pid in args:
            handle = state['pages'][pid]['dev'][-1]['terminal']
            text = '继续。刚才掉了登录，接着上一步往下做，全程只用中文。'
            r = orca('terminal', 'send', '--terminal', handle, '--text', text, '--enter')
            if not r.get('ok'):
                msg = json.dumps(r.get('error') or r, ensure_ascii=False)
                req = msg.split('--retry-request ')[-1].split()[0].strip('".,') if '--retry-request ' in msg else None
                if req:
                    r = orca('terminal', 'send', '--terminal', handle, '--text', text, '--enter', '--retry-request', req, '--wait-submit', '20')
            print(pid, '已发继续' if r.get('ok') else '没发进去 ' + json.dumps(r, ensure_ascii=False)[:300])
    elif cmd == 'close':
        # 交回的窗口：先按编排释放；用户碰过的终端释放后仍是「留住」，再直接关掉这个标签页
        for dispatch in args:
            r = orca('orchestration', 'worker-release', '--dispatch', dispatch)
            shown = orca('orchestration', 'worker-show', '--dispatch', dispatch).get('result') or {}
            term = shown.get('terminal') or {}
            closed = ''
            if term.get('connected') and term.get('handle'):
                closed = '，再关窗 ' + str(orca('terminal', 'close', '--terminal', term['handle'], '--tab').get('ok'))
            print(dispatch, '释放', r.get('ok'), (r.get('result') or {}).get('state', ''), closed)
    elif cmd == 'show':
        print('Run', state['run'])
        for pid in PAGES:
            p = state['pages'].get(pid, {})
            steps = [f"{k}×{len(v)}" for k, v in p.items() if isinstance(v, list)]
            print(f"{pid:6} {PAGES[pid][0]:8} {PAGES[pid][3]:5} {' '.join(steps) or '未派'} {p.get('status', '')}")
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
