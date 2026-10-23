#!/usr/bin/env python3
"""核对通过的后台页加进统一外壳：按模块顺序重排 index.html 里管理后台那一块的配置引用。

用法：python3 accept_admin.py <页面编号> …
"""
import os
import re
import sys

# 带尖括号的是占位，换成你自己的路径
INDEX = '<项目根>/<迭代目录>/原型还原版/小程序端/index.html'
ADMIN = '<项目根>/<迭代目录>/原型还原版/管理后台'
# 后台页面顺序：照上线菜单的模块顺序，外壳与登录放最前
ORDER = ['A-login', 'A-shell', 'T01', 'T02', 'C01', 'C02', 'R01', 'R02', 'R03', 'R04', 'D01', 'D02', 'D03',
         'O01', 'O02', 'O03', 'O04', 'O05', 'O06', 'O07', 'O08', 'O09', 'O10', 'S01', 'S02', 'S03', 'S04', 'S05']
HEAD = '<!-- 管理后台：每页一份配置在 ../管理后台/<页面编号>/config.js，状态页和正确样子在同一目录 -->\n'
TAIL = '<!-- 管理后台列表结束 -->'


def main(ids):
    s = open(INDEX, encoding='utf-8').read()
    a = s.index(HEAD) + len(HEAD)
    b = s.index(TAIL)
    have = re.findall(r'\.\./管理后台/([^/]+)/config\.js', s[a:b])
    for pid in ids:
        if pid not in ORDER:
            raise SystemExit(f'不认识的页面编号 {pid}')
        if not os.path.exists(os.path.join(ADMIN, pid, 'config.js')):
            raise SystemExit(f'{pid} 还没有 config.js')
    pages = [p for p in ORDER if p in set(have) | set(ids)]
    block = ''.join(f'<script src="../管理后台/{p}/config.js"></script>\n' for p in pages)
    open(INDEX, 'w', encoding='utf-8').write(s[:a] + block + s[b:])
    print('外壳里管理后台现在', len(pages), '页：', ' '.join(pages))


if __name__ == '__main__':
    main(sys.argv[1:])
