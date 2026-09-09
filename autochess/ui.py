"""Keyboard-driven curses UI, with a line-based fallback and testable rendering."""
from concurrent.futures import ThreadPoolExecutor
import queue
import re
import threading
import time
import unicodedata

from .engine import CATALOG, SPELLS, TRAITS, XP_NEED, RuleError, synergies
from .agents import CodexAgent, LocalAgent, prepare_opponents
from .sprites import halfblocks, TerminalPalette


def clean(text):
    return ''.join(c for c in str(text) if not unicodedata.category(c).startswith('C'))


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in clean(text))


def clip(text, width):
    result, used = '', 0
    for c in clean(text):
        size = 0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1
        if used+size > width:
            break
        result += c
        used += size
    return result


def pad(text, width):
    text = clip(text, width)
    return text + ' '*max(0, width-display_width(text))


class Controller:
    def __init__(self, game, save_path, timeout=90, speed=.07):
        self.game, self.save_path = game, save_path
        self.timeout, self.speed = timeout, speed
        self.quit = self.hidden = self.help = self.paused = False
        self.focus = 'shop' if game.phase == 'prep' and game.players[0].hp > 0 else 'actions'
        self.shop_cursor = 0
        self.action_cursor = 0
        self.menu = None
        self.menu_index = 0
        self.menu_uid = None
        self.cursor = 3
        self.bench_cursor = 0
        self.held = None
        self.scout = None
        self.message = '左右选择棋子，Enter 招募；向下选择「开始战斗」。'
        self.error = None
        self.future = None
        self.pool = None
        self.cancel = threading.Event()
        self.updates = queue.Queue()
        self.frames = []
        self.frame_index = 0
        self.last_tick = 0
        self.battle_seats = (0, 1)

    @property
    def animating(self):
        return bool(self.frames) and self.frame_index < len(self.frames)-1

    def selected(self):
        p = self.game.players[0]
        if self.focus == 'board':
            return next((u for u in p.units if u.pos == self.cursor), None)
        if self.focus == 'bench':
            bench = [u for u in p.units if u.pos is None]
            return bench[self.bench_cursor] if self.bench_cursor < len(bench) else None
        return None

    def persist(self):
        self.game.save(self.save_path)

    def begin(self):
        if self.future:
            return
        if self.game.players[0].hp > 0 and not any(u.pos is not None for u in self.game.players[0].units):
            if self.game.players[0].units:
                self.game.arrange(0)
            else:
                self.focus = 'shop'
                self.message = '先在商店选择棋子，按 Enter 招募。'
                return
        self.error = None
        self.held = None
        self.cancel = threading.Event()
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=1)
        self.persist()
        agent = CodexAgent(model=self.game.model, timeout=self.timeout) if self.game.mode == 'codex' else LocalAgent()
        self.focus, self.action_cursor = 'actions', 0
        self.message = '对手正在准备。可选择「隐藏棋局」或「保存退出」。'
        self.future = self.pool.submit(prepare_opponents, self.game, agent, self.cancel, self.updates.put)

    def tick(self):
        if self.hidden or self.help or self.menu or self.paused:
            return
        while not self.updates.empty():
            self.message = self.updates.get_nowait()
        if self.future and self.future.done():
            result = self.future.result()
            self.future = None
            self.game = result.game
            self.focus, self.action_cursor = 'actions', 0
            self.error = result.error
            self.persist()
            if self.error:
                self.message = self.error + ' · 选择「重试连接」继续。'
                return
            matches = self.game.resolve_round()
            chosen = next((m for m in matches if m[0] == 0 or (m[1] == 0 and not m[2])), matches[0])
            a, b, ghost, battle_result = chosen
            self.battle_seats = (a, b)
            self.frames = battle_result.frames
            self.frame_index = 0
            self.last_tick = time.monotonic()
            self.message = f'{self.game.players[a].name} vs {self.game.players[b].name}' + (' [镜像阵容]' if ghost else '')
            self.persist()
        if self.animating and time.monotonic()-self.last_tick >= self.speed:
            self.frame_index += 1
            self.last_tick = time.monotonic()
            if not self.animating:
                self.action_cursor = 0
                self.message = self.result_message()

    def result_message(self):
        if self.game.finished:
            winner = self.game.players[self.game.standings()[0]].name
            place = self.game.standings().index(0)+1
            return f'本局结束 · 优胜 {winner} · 你排第 {place} · 选择「保存退出」结束。'
        if self.game.players[0].hp <= 0:
            return '你已淘汰，选择「下一回合」继续观战。'
        return self.game.players[0].last + ' · 选择「下一回合」继续。'

    def close(self):
        self.cancel.set()
        if self.future:
            result = self.future.result()
            self.game = result.game
            self.future = None
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
        self.persist()

    def actions(self):
        if self.future:
            return [('hide', '隐藏棋局'), ('quit', '保存退出')]
        if self.animating:
            return [('advance', '跳过动画'), ('pause', '继续播放' if self.paused else '暂停播放'),
                    ('hide', '隐藏棋局'), ('quit', '保存退出')]
        if self.game.finished:
            return [('quit', '保存退出'), ('help', '玩法说明')]
        if self.game.phase == 'result':
            return [('advance', '下一回合'), ('hide', '隐藏棋局'), ('quit', '保存退出')]
        if self.game.players[0].hp <= 0:
            return [('advance', '继续观战'), ('hide', '隐藏棋局'), ('quit', '保存退出')]
        p = self.game.players[0]
        label = '重试连接' if self.error else '上阵并开战' if p.units and not any(u.pos is not None for u in p.units) else '开始战斗'
        return [('advance', label), ('arrange', '自动上阵'), ('refresh', '刷新 2金'),
                ('xp', '升级 4金'), ('lock', '解锁商店' if p.locked else '锁定商店'), ('more', '更多')]

    def menu_items(self):
        if self.menu == 'unit':
            u = self.game.unit(self.game.players[0], self.menu_uid)
            refund = CATALOG[u.kind].cost * 3**(u.star-1)
            return ([('unit_deploy', '上阵'), ('unit_move', '选择上阵位置')] if u.pos is None else
                    [('unit_move', '移动位置'), ('unit_bench', '放回备战席')]) + [
                    ('unit_sell', f'出售 · 获得 {refund} 金币'), ('back', '返回')]
        if self.menu == 'scout':
            return [(f'scout:{i}', f'{p.name} · {p.hp} 生命 · {p.style}')
                    for i, p in enumerate(self.game.players) if i and p.hp > 0] + [('back', '返回')]
        return [('scout', '查看对手'), ('help', '玩法说明'), ('hide', '隐藏棋局'),
                ('quit', '保存退出'), ('back', '返回')]

    def open_menu(self, name):
        self.menu = name
        self.menu_index = 0

    def preferred_pos(self, unit):
        row = 0 if CATALOG[unit.kind].role == '守卫' else 2
        positions = [row*7+col for col in (3, 2, 4, 1, 5, 0, 6)] + list(range(21))
        used = {u.pos for u in self.game.players[0].units}
        return next((pos for pos in positions if pos not in used), positions[0])

    def perform(self, action):
        if action == 'quit':
            self.close()
            self.quit = True
            return
        if action in ('more', 'scout'):
            self.open_menu(action)
            return
        if action == 'hide':
            self.hidden = True
        elif action == 'help':
            self.help = True
        elif action == 'pause':
            self.paused = not self.paused
        elif action.startswith('scout:'):
            self.scout = int(action.split(':')[1])
            self.message = f'正在查看 {self.game.players[self.scout].name} 的阵容'
        elif action == 'advance':
            if self.paused:
                self.paused = False
            if self.animating:
                self.frame_index = len(self.frames)-1
                self.action_cursor = 0
                self.message = self.result_message()
            elif self.game.phase == 'result':
                if not self.game.finished:
                    self.game.next_round()
                    self.frames = []
                    self.scout = None
                    self.focus = 'shop' if self.game.players[0].hp > 0 else 'actions'
                    self.action_cursor = 0
                    self.message = '选择棋子招募，或向下选择「开始战斗」。'
                    self.persist()
            else:
                self.begin()
        elif action == 'arrange':
            self.game.arrange(0)
            self.held = None
            self.message = '已自动上阵。选择「开始战斗」即可继续。'
            self.persist()
        elif action in ('refresh', 'xp', 'lock'):
            if action == 'refresh':
                self.game.refresh(0)
                self.message = '已刷新商店，花费 2 金币。向上选择棋子。'
            elif action == 'xp':
                self.game.buy_xp(0)
                self.message = '经验 +4，花费 4 金币。等级决定上阵人数。'
            else:
                p = self.game.editable(0)
                p.locked = not p.locked
                self.message = '商店已锁定，下回合保留这些棋子。' if p.locked else '已解锁，下回合自动刷新商店。'
            self.persist()
        elif action.startswith('unit_'):
            unit = self.game.unit(self.game.players[0], self.menu_uid)
            if action == 'unit_move':
                self.held = unit.uid
                self.focus = 'board'
                self.cursor = unit.pos if unit.pos is not None else self.preferred_pos(unit)
                self.message = '方向键选择落点；Enter 放下，Esc 取消。已有棋子的格子会交换。'
            elif action == 'unit_deploy':
                self.game.move(0, unit.uid, self.preferred_pos(unit))
                self.focus, self.cursor = 'board', unit.pos
                self.message = '已上阵。选中棋子按 Enter 可调整位置。'
                self.persist()
            elif action == 'unit_bench':
                self.game.move(0, unit.uid, None)
                self.focus = 'bench'
                self.bench_cursor = [u for u in self.game.players[0].units if u.pos is None].index(unit)
                self.message = '已放回备战席。'
                self.persist()
            elif action == 'unit_sell':
                self.game.sell(0, unit.uid)
                self.message = f'已出售 {CATALOG[unit.kind].name}，金币已返还。'
                self.persist()
        self.menu = None

    def navigate(self, key):
        if self.menu:
            self.menu_index = (self.menu_index + (-1 if key in ('UP', 'LEFT') else 1)) % len(self.menu_items())
            return
        if self.held is not None:
            row, col = divmod(self.cursor, 7)
            row = max(0, min(2, row + (1 if key == 'DOWN' else -1 if key == 'UP' else 0)))
            col = (col + (1 if key == 'RIGHT' else -1 if key == 'LEFT' else 0)) % 7
            self.cursor = row*7+col
            return
        if self.future or self.game.phase != 'prep' or self.game.players[0].hp <= 0:
            self.focus = 'actions'
        if self.focus == 'board':
            row, col = divmod(self.cursor, 7)
            if key == 'DOWN' and row == 2:
                self.focus, self.bench_cursor = 'bench', col
            else:
                row = max(0, min(2, row + (1 if key == 'DOWN' else -1 if key == 'UP' else 0)))
                col = (col + (1 if key == 'RIGHT' else -1 if key == 'LEFT' else 0)) % 7
                self.cursor = row*7+col
        elif self.focus == 'bench':
            if key == 'UP':
                self.focus, self.cursor = 'board', 14+min(6, self.bench_cursor)
            elif key == 'DOWN':
                self.focus = 'shop'
            else:
                self.bench_cursor = (self.bench_cursor + (1 if key == 'RIGHT' else -1)) % 8
        elif self.focus == 'shop':
            if key == 'UP':
                self.focus = 'bench'
            elif key == 'DOWN':
                self.focus, self.action_cursor = 'actions', 0
            else:
                self.shop_cursor = (self.shop_cursor + (1 if key == 'RIGHT' else -1)) % 5
        elif self.focus == 'actions':
            if key == 'UP' and not self.future and self.game.phase == 'prep' and self.game.players[0].hp > 0:
                self.focus = 'shop'
            elif key in ('LEFT', 'RIGHT'):
                self.action_cursor = (self.action_cursor + (1 if key == 'RIGHT' else -1)) % len(self.actions())

    def confirm(self):
        if self.menu:
            self.perform(self.menu_items()[self.menu_index][0])
        elif self.held is not None:
            self.game.move(0, self.held, self.cursor)
            self.held = None
            self.message = '位置已更新。'
            self.persist()
        elif self.focus == 'actions':
            self.action_cursor %= len(self.actions())
            self.perform(self.actions()[self.action_cursor][0])
        elif self.focus == 'shop':
            kind = self.game.players[0].shop[self.shop_cursor]
            self.game.buy(0, self.shop_cursor)
            self.message = f'已招募 {CATALOG[kind].name}。继续选棋，或向下选择「{self.actions()[0][1]}」。'
            self.persist()
        else:
            unit = self.selected()
            if unit:
                self.menu_uid = unit.uid
                self.open_menu('unit')
            else:
                self.message = '这里没有棋子。到商店选择棋子，按 Enter 招募。'

    def key(self, key):
        if len(key) == 1:
            key = key.lower()
        if key in ('q', '\x03'):
            self.perform('quit')
            return
        if self.hidden:
            if key in ('b', 'ENTER', 'ESC'):
                self.hidden = False
            return
        if key == 'b':
            self.hidden = True
            return
        if self.help:
            if key in ('ENTER', 'ESC', '?', 'h'):
                self.help = False
            return
        if key == 'ESC':
            if self.menu:
                self.menu = None
            elif self.held is not None:
                self.held = None
                self.message = '已取消移动，棋子保持原位。'
            else:
                self.open_menu('more')
            return
        try:
            if key in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
                self.navigate(key)
            elif key == 'ENTER':
                self.confirm()
            # Existing shortcuts remain optional, and are no longer the primary UI.
            elif key in ('?', 'h'):
                self.perform('help')
            elif key == 'p':
                self.perform('pause')
            elif key in ('[', ']'):
                self.speed = max(.01, min(.4, self.speed + (.02 if key == '[' else -.02)))
            elif not (self.future or self.menu or self.held is not None or self.paused):
                if key == ' ':
                    self.focus, self.action_cursor = 'actions', 0
                    self.perform('advance')
                elif key == 'v':
                    self.open_menu('scout')
                elif self.game.phase == 'prep' and self.game.players[0].hp > 0:
                    if key in ('1', '2', '3', '4', '5'):
                        self.focus, self.shop_cursor = 'shop', int(key)-1
                        self.confirm()
                    elif key in ('d', 'f', 'l', 'a'):
                        self.perform({'d': 'refresh', 'f': 'xp', 'l': 'lock', 'a': 'arrange'}[key])
                    elif key == 'TAB':
                        zones = ['shop', 'actions', 'board', 'bench']
                        self.focus = zones[(zones.index(self.focus)+1) % 4]
                    elif key == 'e' and self.selected():
                        self.menu_uid = self.selected().uid
                        self.perform('unit_sell')
        except RuleError as error:
            self.message = str(error)


def render_lines(c, width, height, *, pixel_cells=None):
    if pixel_cells is None:
        pixel_cells = []
    else:
        pixel_cells.clear()
    grid = [[' ' for _ in range(max(0, width))] for _ in range(max(0, height))]

    def put(y, x, text, limit=None):
        if not 0 <= y < height or x < 0 or x >= width:
            return
        end = min(width, x+limit) if limit is not None else width
        for char in clip(text, end-x):
            size = display_width(char)
            if size == 0:
                continue
            grid[y][x] = char
            if size == 2:
                grid[y][x+1] = ''
            x += size

    def sprite(kind, y, x, size):
        for dy, row in enumerate(halfblocks(kind, size)):
            for dx, (char, fg, bg) in enumerate(row):
                py, px = y+dy, x+dx
                if 0 <= py < height and 0 <= px < width:
                    put(py, px, char)
                    if fg is not None:
                        pixel_cells.append((py, px, char, fg, bg))

    def lines():
        return [''.join(row).rstrip() for row in grid]

    if c.hidden:
        put(1, 2, 'service-monitor / local')
        put(3, 2, 'STATUS     healthy')
        put(5, 2, 'queue      idle')
        put(7, 2, 'No pending tasks.')
        put(height-2, 2, 'Enter 返回')
        return lines()
    if width < 80 or height < 24:
        put(1, 1, '请将终端放大至 80 列 × 24 行')
        put(3, 1, '建议 108 × 38；Esc 打开菜单')
        if c.menu:
            items = c.menu_items()
            count = max(1, height-5)
            start = max(0, c.menu_index-count+1)
            for row, (i, (_, label)) in enumerate(list(enumerate(items))[start:start+count], 4):
                put(row, 1, f'[ {label} ]' if i == c.menu_index else f'  {label}', width-2)
            put(height-1, 1, '↑↓ 选择 · Enter 确认 · Esc 返回', width-2)
        return lines()
    if c.help:
        help_lines = [
            '摸鱼棋局 / 玩法说明                               Enter 或 Esc 返回',
            '', '只需方向键选择、Enter 确认；Esc 返回。',
            '左右选择棋子，上下在棋盘、备战席、商店和底部操作栏之间移动。',
            '商店：选中棋子按 Enter 招募；底部可选择刷新、升级、锁定。',
            '棋子：按 Enter 打开操作菜单，再选择上阵、移动或出售。',
            '第一局：招募棋子 → 向下选择「上阵并开战」→ Enter。',
            '更多：查看对手、玩法说明、隐藏棋局、保存退出。',
            '', '三枚同名同星自动合成，最高三星。等级决定上阵人数，备战席8格。',
            '每轮 +5 金币，每10金 +1 利息(最多5)，每2连胜/败 +1(最多3)。',
            '每轮 +2 经验；胜利 +1 金。60血，最多30轮。',
            '', '羁绊只数上阵的不同棋子：',
            *[f'  {name}   {description}' for name, description in TRAITS.items()],
            '', '操作自动存档；再次启动即可继续。',
            'Codex 连接失败时，选择「重试连接」；已完成的对手会保留。',
        ]
        for y, line in enumerate(help_lines[:height]):
            put(y, 1, line, width-2)
        return lines()
    g, p = c.game, c.game.players[0]
    large = width >= 100 and height >= 37
    side_x = 76 if large else 59
    field_width = side_x-3
    phase = '对手思考中' if c.future else '战斗中' if c.animating else '赛后结算' if g.phase == 'result' else '准备回合'
    if c.paused:
        phase = '已暂停'
    provider = 'CODEX / ' + (g.model or '本机默认模型') if g.mode == 'codex' else 'LOCAL / 离线策略'
    put(0, 1, '摸鱼棋局  /  IDLE ARENA')
    put(0, width-23, f'ROUND {g.round:02d} / 30')
    put(1, 1, f'{phase}  ·  {provider}')
    xp = f'{p.xp}/{XP_NEED[p.level]}' if p.level < 8 else 'MAX'
    deployed = sum(u.pos is not None for u in p.units)
    put(2, 1, f'生命 {p.hp:2d}/60   金币 {p.gold:3d}   Lv.{p.level} 经验 {xp}   上阵 {deployed}/{p.level}   利息 +{min(5, p.gold//10)}')
    pair = next((pair for pair in g.pairings() if 0 in pair[:2]), None)
    enemy = c.scout if c.scout is not None else (pair[1] if pair and pair[0] == 0 else pair[0] if pair else 1)
    if c.frames and g.phase == 'result':
        a, enemy = c.battle_seats
    else:
        a = 0
    header_y = 4 if large else 3
    put(header_y, 1, f'- {g.players[enemy].name}  ↓  VS  ↑  + {g.players[a].name}' + ('  [侦察]' if c.scout is not None and g.phase == 'prep' else ''))
    put(header_y, side_x, '排位 / 生命')
    pieces = {}
    if c.frames and g.phase == 'result':
        for unit in c.frames[c.frame_index]['units']:
            pieces[unit['y'], unit['x']] = unit
    else:
        for side, seat in [(0, 0), (1, enemy)]:
            for u in g.players[seat].units:
                if u.pos is None:
                    continue
                row, col = divmod(u.pos, 7)
                y, x = (3+row, col) if side == 0 else (2-row, 6-col)
                pieces[y, x] = {'kind': u.kind, 'star': u.star, 'side': side, 'hp': 1, 'max_hp': 1, 'mana': 0}
    for row in range(6):
        y = (5+row*3+(1 if row >= 3 else 0)) if large else 4+row
        for col in range(7):
            x = 2+col*(10 if large else 8)
            piece = pieces.get((row, col))
            own_pos = (row-3)*7+col
            cursor = row >= 3 and own_pos == c.cursor and c.focus == 'board' and g.phase == 'prep'
            if large and piece:
                sprite(piece['kind'], y, x, 6)
                put(y, x+6, CATALOG[piece['kind']].name, 4)
                status = f'{round(piece["hp"]/piece["max_hp"]*100)}%' if g.phase == 'result' else CATALOG[piece['kind']].role
                put(y+1, x+6, status, 4)
                badge = f'[{piece["star"]}]' if cursor else ('+' if piece['side'] == 0 else '-')+f'{piece["star"]}*'
                put(y+2, x+6, badge, 4)
            else:
                title = f'{CATALOG[piece["kind"]].name}{piece["star"]}*' if piece else ' ·  '
                if piece and c.frames and g.phase == 'result':
                    title = ('+' if piece['side'] == 0 else '-')+title
                cell = f'[{title}]' if cursor else ' '+title
                put(y, x, cell, 10 if large else 8)
        if large and row == 2:
            put(y+3, 1, '─'*field_width)
    for rank, seat in enumerate(g.standings()):
        other = g.players[seat]
        y = header_y+1+rank*(2 if large else 1)
        marker = '>' if seat == 0 else ' '
        status = f'{other.hp:2d}hp' if other.hp else ' OUT'
        put(y, side_x, f'{marker}{rank+1} {other.name:<6} {status}', width-side_x-1)
        if large:
            ready = 'READY' if seat in g.ready else f'Lv.{other.level}'
            put(y+1, side_x+3, f'{other.style} · {ready}', width-side_x-4)
    traits = synergies(p.units)
    if large:
        selected = c.selected()
        portrait = selected.kind if selected else p.shop[c.shop_cursor] if c.focus == 'shop' and g.phase == 'prep' else None
        if portrait:
            put(23, side_x, '怪兽形象')
            sprite(portrait, 24, side_x+2, 16)
            put(32, side_x+2, CATALOG[portrait].name)
            put(33, side_x+2, f'{CATALOG[portrait].origin} · {CATALOG[portrait].role}', width-side_x-3)
        else:
            put(23, side_x, '羁绊 / 不同棋子')
            for i, (name, count) in enumerate(sorted(traits.items(), key=lambda pair: -pair[1])):
                target = 4 if count >= 2 else 2
                put(25+i, side_x, f'{"◆" if count >= 2 else "·"} {name} {count}/{target}', width-side_x-1)
    else:
        trait_text = '  '.join(f'{name}{count}{"+" if count >= 2 else ""}' for name, count in traits.items()) or '买棋并上阵，激活羁绊'
        put(10, 1, trait_text, field_width)
    bench_y = 25 if large else 12
    put(bench_y, 1, ('▸ ' if c.focus == 'bench' else '') + '备战席 · 选中棋子后 Enter 操作')
    bench = [u for u in p.units if u.pos is None]
    for i in range(8):
        cursor = c.focus == 'bench' and c.bench_cursor == i
        x = 1+i*9
        if large and i < len(bench):
            unit = bench[i]
            sprite(unit.kind, bench_y+1, x, 4)
            put(bench_y+1, x+4, CATALOG[unit.kind].name, 5)
            put(bench_y+2, x+4, f'[{unit.star}]' if cursor else f'{unit.star}星', 5)
        else:
            text = f'{CATALOG[bench[i].kind].name}{bench[i].star}*' if i < len(bench) else ' -- '
            put(bench_y+1, x, ('['+text+']') if cursor else ' '+text, 9)
    shop_y = 29 if large else 16
    put(shop_y, 1, ('▸ ' if c.focus == 'shop' else '') + '商店 · 左右选择，Enter 招募' + (' · 已锁定' if p.locked else ''))
    cell_width = 15
    for i, kind in enumerate(p.shop):
        x = 1+i*cell_width
        if kind:
            champ = CATALOG[kind]
            sprite(kind, shop_y+1, x, 6)
            title = f'{champ.name}{champ.cost}金'
            put(shop_y+1, x+6, f'[{title}]' if c.focus == 'shop' and c.shop_cursor == i else title, 9)
            put(shop_y+2, x+6, champ.origin, 9)
            put(shop_y+3, x+6, champ.role, 9)
        else:
            put(shop_y+1, x, '[已招募]' if c.focus == 'shop' and c.shop_cursor == i else ' 已招募', cell_width)
    detail_y = 34 if large else 20
    selected = c.selected()
    if c.animating:
        events = c.frames[c.frame_index]['events']
        put(detail_y, 1, ' / '.join(events[-2:]), width-2)
    elif g.phase == 'result':
        put(detail_y, 1, c.result_message(), width-2)
    elif selected:
        champ = CATALOG[selected.kind]
        put(detail_y, 1, f'{champ.name} {selected.star}星 · {champ.origin}/{champ.role} · {SPELLS[champ.spell]}', width-2)
    elif c.focus == 'shop':
        kind = p.shop[c.shop_cursor]
        if kind:
            champ = CATALOG[kind]
            description = '金币不足' if p.gold < champ.cost else SPELLS[champ.spell]
            put(detail_y, 1, f'{champ.name} · {description}', width-2)
    elif c.focus == 'actions':
        action = c.actions()[c.action_cursor % len(c.actions())][0]
        description = {'advance': '自动上阵尚未布阵的棋子，然后开始战斗。' if p.units and not deployed else '准备好后开始本轮战斗。',
                       'arrange': '将高星、高费用棋子自动上阵，守卫在前，远程在后。',
                       'refresh': '花费 2 金币，更换商店的全部棋子。',
                       'xp': '花费 4 金币，获得 4 经验；升级后可上阵更多棋子。',
                       'lock': '锁定后，下回合保留当前商店。',
                       'more': '查看对手、玩法说明、隐藏棋局或保存退出。'}.get(action, '')
        put(detail_y, 1, description, width-2)
    def overlay():
        items = c.menu_items()
        box_w = min(70 if c.menu == 'unit' else 58, width-6)
        box_h = max(15, len(items)+7) if c.menu == 'unit' else len(items)+7
        x = (width-box_w)//2
        y = max(1, (height-box_h)//2)
        if c.menu == 'unit':
            unit = g.unit(p, c.menu_uid)
            champ = CATALOG[unit.kind]
            title = f'{champ.name} · {unit.star}星'
            description = f'{champ.origin} / {champ.role} · 选择要做的操作'
        else:
            title = '查看对手' if c.menu == 'scout' else '更多操作'
            description = '上下选择，按 Enter 确认'
        # Keep only status and controls behind a menu, so clipped board text
        # cannot compete with the choices or split a wide Chinese character.
        for row in range(3, height-3):
            grid[row] = [' '] * width
        pixel_cells.clear()
        for row in range(box_h):
            put(y+row, x, ' '*box_w)
            put(y+row, x, '│')
            put(y+row, x+box_w-1, '│')
        put(y, x, '┌'+'─'*(box_w-2)+'┐')
        put(y+box_h-1, x, '└'+'─'*(box_w-2)+'┘')
        put(y+1, x+3, title, box_w-6)
        put(y+2, x+3, description, box_w-6)
        menu_x = x+24 if c.menu == 'unit' else x+3
        if c.menu == 'unit':
            sprite(unit.kind, y+4, x+4, 16)
        for i, (_, label) in enumerate(items):
            text = f'[ {label} ]' if i == c.menu_index else f'  {label}'
            put(y+4+i, menu_x, text, box_w-(menu_x-x)-3)
        put(y+box_h-2, x+3, 'Esc 返回', box_w-6)

    action_text = []
    for i, (_, label) in enumerate(c.actions()):
        selected_action = c.focus == 'actions' and i == c.action_cursor % len(c.actions()) and not c.menu
        action_text.append(f'[{label}]' if selected_action else f' {label} ')
    put(height-3, 1, ' '.join(action_text), width-2)
    hint = '↑↓←→ 选择     Enter 确认     Esc 返回 / 菜单'
    if c.held is not None:
        hint = '↑↓←→ 选择落点     Enter 放下棋子     Esc 取消移动'
    elif c.menu:
        hint = '↑↓ 选择操作     Enter 确认     Esc 返回'
    put(height-2, 1, hint, width-2)
    put(height-1, 1, c.message, width-2)
    if c.menu:
        overlay()
    return lines()


def run_curses(c):
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, '')

    def loop(screen):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.timeout(40)
        screen.keypad(True)
        colors = curses.has_colors()
        pixel_palette = None
        if colors:
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            for index, color in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_MAGENTA), 1):
                curses.init_pair(index, color, background)
            pixel_palette = TerminalPalette(curses, background)
        keymap = {curses.KEY_LEFT: 'LEFT', curses.KEY_RIGHT: 'RIGHT', curses.KEY_UP: 'UP',
                  curses.KEY_DOWN: 'DOWN', curses.KEY_ENTER: 'ENTER', '\n': 'ENTER', '\r': 'ENTER',
                  '\t': 'TAB', '\x1b': 'ESC'}
        while not c.quit:
            c.tick()
            height, width = screen.getmaxyx()
            screen.erase()
            pixels = []
            for y, line in enumerate(render_lines(c, width, height, pixel_cells=pixels)):
                style = curses.A_NORMAL
                if colors:
                    if y in (0, 1):
                        style = curses.color_pair(1) | curses.A_BOLD
                    elif y == 2 or '商店 ·' in line:
                        style = curses.color_pair(3)
                    elif y == height-1:
                        style = curses.color_pair(4) if c.error else curses.color_pair(2)
                try:
                    screen.addstr(y, 0, line, style)
                    # Selection uses reverse video, including on monochrome terminals.
                    for match in re.finditer(r'\[[^\]]+\]', line):
                        x = display_width(line[:match.start()])
                        screen.addstr(y, x, match.group(), curses.A_REVERSE | curses.A_BOLD)
                except curses.error:
                    pass
            if pixel_palette:
                for y, x, char, fg, bg in pixels:
                    try:
                        screen.addstr(y, x, char, pixel_palette.style(fg, bg))
                    except curses.error:
                        pass
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key == curses.KEY_RESIZE:
                continue
            if key in keymap:
                c.key(keymap[key])
            elif isinstance(key, str):
                c.key(key)
    try:
        curses.wrapper(loop)
    finally:
        c.close()


def plain_command(c, text):
    parts = text.strip().lower().split()
    if not parts:
        c.key(' ')
        return
    command = parts[0]
    if c.hidden and command not in ('b', 'q', 'quit'):
        return
    if (c.paused or c.help or c.menu or c.future) and command in ('buy', 'move', 'sell'):
        return
    if command in ('buy', 'move', 'sell'):
        expected = 3 if command == 'move' else 2
        if len(parts) != expected:
            raise RuleError('用法：buy 1..5 / move 棋子编号 0..20或bench / sell 棋子编号')
        if command == 'buy':
            c.game.buy(0, int(parts[1])-1)
        elif command == 'move':
            c.game.move(0, int(parts[1]), None if parts[2] == 'bench' else int(parts[2]))
        else:
            c.game.sell(0, int(parts[1]))
        c.persist()
    elif command in ('next', 'fight'):
        c.key(' ')
    elif command in ('auto', 'refresh', 'xp', 'lock', 'quit', 'help'):
        c.key({'auto':'a','refresh':'d','xp':'f','lock':'l','quit':'q','help':'?'}[command])
    elif len(command) == 1:
        c.key(command)
    else:
        raise RuleError('未知命令，输入 help 查看说明')


def run_plain(c):
    print('逐行模式：buy 1 / auto / move 棋子编号 0..20或bench / sell 编号 / refresh / xp / fight / next / quit')
    try:
        while not c.quit:
            while c.future or c.animating:
                c.tick()
                if c.hidden or c.help or c.paused:
                    break
                if c.animating:
                    c.frame_index = len(c.frames)-1
                time.sleep(.05)
            print('\n'.join(render_lines(c, 100, 37)))
            if not c.hidden:
                units = c.game.players[0].units
                print('棋子：' + ' | '.join(f'#{u.uid} {CATALOG[u.kind].name}{u.star}* 位置:{u.pos if u.pos is not None else "bench"}' for u in units))
            try:
                plain_command(c, input('> '))
            except (RuleError, ValueError) as error:
                c.message = str(error)
                print(c.message)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        c.close()
