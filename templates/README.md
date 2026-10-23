派工脚本模板（2026-10-23 管理后台 28 页还原用过的版本；项目数据已换成模拟数据，脚本逻辑原样，只把工作区编号、claude 启动命令、网关日志路径改成从环境变量读）

换项目时整套拷到新任务目录（比如 <任务目录>/），改下面这些地方就能用。脚本之间靠同目录的文件通信，不用装别的东西。

环境变量：
- ORCA_WORKTREE_ID：必需。Orca 文件夹工作区编号，Orca 主控终端里自带。dispatch.py 只从这里取，没有就报错退出。
- CLAUDE_LAUNCH_CMD：可选。起 claude 的命令，不设就是 claude。经启动器或中转起 claude 的，填一个带令牌（CLAUDE_CODE_OAUTH_TOKEN）、不读共用凭证的独立启动脚本，原因见 SKILL.md 的「派工工具」。
- GATEWAY_LOG：可选。中转网关的日志路径，watch.py 用它报网关告警；没设就跳过这一类。

dispatch.py：派工本体
- 改常量：TOOLS（说明书和工具所在目录）、DEV_BRIEF、CHECK_BRIEF（两份说明书路径）、TASK（任务目录相对路径）。带尖括号的 <项目根>、<迭代目录>、<任务目录> 是占位，换成你自己的路径；提示词和线索里出现的同名占位也一起换。工作区编号不用改常量，从环境变量 ORCA_WORKTREE_ID 取。
- 改 PAGES：每项一行，编号: (名字, 模块, 路由或范围, 开发难度等级, 本项线索)。线索只写源码里核实过的事，别抄注释。
- 改 dev_spec / check_spec / fix_spec / takeover_spec 四个提示词：写清读哪份说明书、只写哪些文件、交回怎么写。提示词里必须有：只用中文、不走 Trellis 流程、不再派子代理、拿不准用 ask 问主控、交回用 worker_done（三句话摘要、--report-path）。
- 改 main() 里 run-create 的 objective。
- 用法：python3 dispatch.py run 建 Run；python3 dispatch.py close <派工号> 释放并关窗；python3 dispatch.py show 看每项走到哪。新对话一律经 launchq.py 起，不要手动 dev/check/fix。

launchq.py：常驻启动器
- 后台跑 python3 -u launchq.py run（同时只能一个）。排队：python3 launchq.py add <编号> <dev|takeover|check|fix> [轮次] [模型:等级] [交接说明]，比如 add T01 fix 2 sonnet:high。
- 上限写在 launch-cap.txt，改文件即生效。stability.json 里写了「用户定上限」就不再自动加量。
- 第一次用先建 stability.json：{"顺利交回": 0, "掉线或打断": 0, "目标": 15, "启动计数起点": 0, "用户定上限": 5}
- 改 CREDWATCH 路径（凭证变动日志，没有就随便指一个不存在的文件）。
- 记交回：python3 launchq.py ok <编号> <开发|核对|返修>；记掉线：python3 launchq.py drop <编号> <说明>。
- 改了 dispatch.py 要重启启动器才生效；只在它不在起对话时重启（窗口已满，或上一次起对话不到 50 秒）。

watch.py：Monitor 用的 10 秒巡检
- Monitor 里跑 python3 -u watch.py，报交回、提问、掉线、停住、网关告警、启动失败。30 分钟到期要重挂，重挂会重报旧事件。
- 网关告警要设环境变量 GATEWAY_LOG；GATEWAY_WARN 里的关键词是通用例子，按你自己的网关日志里真实出现的字样改。

inbox.py：收件
- python3 inbox.py next 5000 看新到的交回和提问正文。

collect.py：收一个交回
- python3 collect.py <编号> <dev|check|fix> [核对结论]：先关窗，再拿锁记结论，再记一次顺利交回。下一步用 launchq.py add 排队。

accept_admin.py：验收后把一页加进统一外壳的页面列表（这次专用，换项目照它的写法另写；INDEX、ADMIN 两个路径是占位，换成你自己的）。

briefs/：两份说明书样板（开发说明、核对说明），照它们的结构写新任务的说明书。
