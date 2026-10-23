# rec-dispatcher

Claude Code 技能：用 Orca 多窗口批量派工的总代理手册，含一套可以改着用的脚本模板。

把一批同类的活拆成一项一个 Orca 窗口，由主控（总代理）写说明书、派发、巡检、收件、验收、对齐、汇报。适合逐页还原、逐页核对、批量对齐、批量测试、批量改文档这类大批量同构任务。

## 来历

来自两轮实战：同一个项目的两个端各 28 页，小程序端 28 页（126 个窗口）、管理后台 28 页（148 个窗口），共 270 多个窗口，全部验收进成品。

手册里的经验、规矩、踩过的坑、窗口数和 token 实测数据都是真的。项目本身的数据（路径、人名、编号、业务词）已全部换成模拟数据，示例业务是一个虚构的在线课程平台，里面的讲师、课程、订单、会员测评都是编的。

## 安装

```
git clone https://github.com/FeeJson/rec-dispatcher ~/.claude/skills/rec-dispatcher
```

Claude Code 从 ~/.claude/skills/ 下读取技能。

## 用法

1. 在 Claude Code 对话里说「用 rec 总代理派工」，或输入 /rec-dispatcher。
2. 填 SKILL.md 末尾的开场白：任务、范围、每项产出、验收标准、已定的口径、材料位置、并发上限。
3. 总代理按手册问清缺的信息，写两份说明书，把 templates/ 里的脚本拷到任务目录改常量，先派一个样板项跑通，再铺开。

SKILL.md 正文也可以整段复制到别的工具里当提示词用。

脚本用到三个环境变量，详见 templates/README.md：

- ORCA_WORKTREE_ID：必需，Orca 文件夹工作区编号，Orca 主控终端里自带。
- CLAUDE_LAUNCH_CMD：可选，起 claude 的命令，不设就是 claude。
- GATEWAY_LOG：可选，中转网关的日志路径，不设就不报网关告警。

## 依赖

- Orca：提供 orca 命令行和团队派工（orchestration）。
- Claude Code。
- Python 3：脚本只用标准库。

脚本按 macOS 写：

- Orca 命令路径写的是 /Applications/Orca.app/Contents/Resources/bin/orca，别的系统要改。
- 启动器的内存检查调用 macOS 的 memory_pressure，调用失败时当作内存充足。
- 状态文件的锁用 fcntl，Windows 上不能用。

## 目录说明

```
rec-dispatcher/
  SKILL.md                  手册正文，技能入口
  README.md                 本文件
  LICENSE                   MIT 许可证
  .gitignore                忽略脚本运行时生成的状态文件
  templates/
    README.md               脚本用法，换项目要改的常量
    dispatch.py             派工本体：建 Run，派开发、核对、返修、接手，关窗，看进度
    launchq.py              常驻启动器：排队，隔 70 秒一个，限并发，机器吃紧就暂停，自动加量
    watch.py                10 秒一轮的巡检，给 Monitor 用
    inbox.py                收件：看新到的交回和提问
    collect.py              收一个交回：先关窗，再拿锁记结论
    accept_admin.py         验收后把一页加进统一外壳的页面列表，这次专用，换项目照写法另写
    briefs/
      开发说明样板.md       开发窗口的任务说明样板
      核对说明样板.md       核对窗口的任务说明样板
```

## 改成自己的项目时

说明书和脚本里的示例数据是模拟的，下面这些写法要换成你自己的：

| 写法 | 含义 |
| --- | --- |
| `<项目根>` | 你的项目根目录 |
| `<迭代目录>` | 项目根下放这一轮材料的目录 |
| `<任务目录>` | 任务目录，相对项目根 |
| `<临时目录>` | 截图和临时脚本用的临时目录 |
| `<独立启动脚本>` | 带令牌、不读共用登录凭证的 claude 启动脚本，原因见 SKILL.md 的「派工工具」 |
| 原型还原版、还原工具 | 示例任务里两个目录的名字 |
| admin-web、mini-app、server/admin-api、示例项目 | 示例项目的仓库和模块名 |

提示词和说明书里「不要走 Trellis 流程」「Active task」这类字眼，是给用 Trellis 管任务的项目写的。你的项目没有这套流程，就删掉，或改成自己的约束。

## 许可证

MIT，见 LICENSE。
