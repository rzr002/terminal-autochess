# 验证记录

- `tests.txt`：64 项 unittest 全部通过；不调用真实模型。
- `codex-check.json`：一次真实 Codex 请求，并通过游戏规则校验。
- `codex-seven-opponents.json`：7 位真实 Codex 对手完成首轮，49.08 秒；玩家位在此无界面验证中由本地策略代打。
- `local-40-games.json`：随机种子 0–39，各自跑完完整离线比赛；无异常，16–22 轮结束。
- `terminal-80x24.txt`、`terminal-108x38.txt`：同一阵容的两种窗口布局。

联调时间：2026-09-09。实际模型延迟与策略表现会变化；此处未验证真实模型连续整局表现。

## 菜单交互更新

- `menu-80x24.txt`、`menu-108x38.txt`：方向键导航的商店与操作栏。
- `champion-menu-80x24.txt`、`champion-menu-108x38.txt`：上阵、移动、出售的中文菜单。
- 自动测试新增仅用方向键和 Enter 的招募、布阵、开战、下一回合、菜单退出，以及小窗口菜单等检查。

## 像素形象更新

- 新增全部18个形象独立性、16×16像素编码、4/6像素缩略图、终端颜色上限、图像边界以及隐藏/帮助/菜单清屏检查。
- `sprites-80x24.txt`、`sprites-108x38.txt`：商店和详情头像布局（文本文件不包含颜色）。
- `sprite-portrait-80x24.txt`、`sprite-portrait-108x38.txt`：棋子操作菜单的完整头像。
- 原始PNG与来源信息保存在 `assets/`。
