"""Deterministic game rules. No terminal, model, network or wall-clock dependencies."""
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
import copy
import json
import random
from pathlib import Path


@dataclass(frozen=True)
class Champion:
    name: str
    cost: int
    origin: str
    role: str
    hp: int
    attack: int
    reach: int
    spell: str


CATALOG = {
    'spark': Champion('火花', 1, '霓虹', '守卫', 680, 48, 1, 'shield'),
    'volt': Champion('电弧', 1, '霓虹', '游侠', 400, 66, 3, 'burst'),
    'byte': Champion('字节', 2, '霓虹', '术士', 430, 46, 3, 'nova'),
    'chrome': Champion('铬甲', 3, '霓虹', '守卫', 1020, 68, 1, 'shield'),
    'pulse': Champion('脉冲', 3, '霓虹', '游侠', 610, 94, 4, 'burst'),
    'zero': Champion('零号', 4, '霓虹', '术士', 730, 64, 3, 'nova'),
    'bark': Champion('木灵', 1, '荒野', '守卫', 740, 42, 1, 'heal'),
    'fern': Champion('叶羽', 1, '荒野', '游侠', 420, 62, 3, 'burst'),
    'sage': Champion('苔语', 2, '荒野', '术士', 480, 42, 3, 'heal'),
    'bear': Champion('岩熊', 2, '荒野', '守卫', 850, 55, 1, 'shield'),
    'fang': Champion('风牙', 3, '荒野', '游侠', 620, 88, 3, 'burst'),
    'grove': Champion('森罗', 4, '荒野', '术士', 810, 60, 3, 'nova'),
    'oracle': Champion('星使', 1, '星界', '术士', 410, 44, 3, 'nova'),
    'comet': Champion('彗羽', 2, '星界', '游侠', 490, 76, 4, 'burst'),
    'moon': Champion('月盾', 2, '星界', '守卫', 810, 54, 1, 'shield'),
    'nebula': Champion('星云', 3, '星界', '术士', 610, 57, 3, 'nova'),
    'titan': Champion('天枢', 4, '星界', '守卫', 1230, 80, 1, 'shield'),
    'nova': Champion('极光', 4, '星界', '游侠', 750, 110, 4, 'burst'),
}
TRAITS = {
    '霓虹': '2/4：霓虹攻击 +15%/30%',
    '荒野': '2/4：荒野每秒回复 2%/4% 生命',
    '星界': '2/4：星界初始法力 +30/+60',
    '守卫': '2/4：守卫生命 +20%/40%，护甲 +15/+30',
    '游侠': '2/4：游侠攻击间隔 -20%/-35%',
    '术士': '2/4：术士技能效果 +30%/60%',
}
SPELLS = {'shield': '铁壁：回复自身生命并获得护甲', 'heal': '复苏：治疗生命比例最低的友军',
          'burst': '狙击：对目标造成 3 倍攻击伤害', 'nova': '星爆：伤害目标及相邻敌人'}
XP_NEED = {2: 4, 3: 8, 4: 12, 5: 20, 6: 28, 7: 36}
SHOP_ODDS = {2: (80, 20, 0, 0), 3: (65, 30, 5, 0), 4: (45, 35, 20, 0),
             5: (30, 35, 30, 5), 6: (20, 30, 35, 15), 7: (15, 25, 35, 25), 8: (10, 20, 35, 35)}
NAMES = ['你', 'NOVA', 'MOSS', 'BLAZE', 'ECHO', 'ATLAS', 'JADE', 'ORBIT']
STYLES = ['自由运营', '星界法术', '荒野续航', '霓虹快攻', '游侠后排', '守卫前排', '追星运营', '经济速升']


class RuleError(ValueError):
    pass


@dataclass
class Unit:
    uid: int
    kind: str
    star: int = 1
    pos: int | None = None


@dataclass
class Player:
    name: str
    style: str
    hp: int = 60
    gold: int = 10
    level: int = 2
    xp: int = 0
    units: list[Unit] = field(default_factory=list)
    shop: list[str | None] = field(default_factory=list)
    locked: bool = False
    streak: int = 0
    eliminated: int = 0
    last: str = '等待开战'
    income: int = 0


def synergies(units):
    counts = Counter()
    for kind in {u.kind for u in units if u.pos is not None}:
        c = CATALOG[kind]
        counts.update([c.origin, c.role])
    return dict(counts)


def tier(count):
    return 2 if count >= 4 else 1 if count >= 2 else 0


@dataclass
class BattleResult:
    winner: int | None
    survivors: list[int]
    frames: list[dict]


def battle(left, right, seed):
    rng = random.Random(seed)
    fighters = []
    for side, team in enumerate((left, right)):
        traits = synergies(team)
        for u in team:
            if u.pos is None:
                continue
            c = CATALOG[u.kind]
            scale = (1, 1.8, 3.24)[u.star - 1]
            guard = tier(traits.get('守卫', 0)) if c.role == '守卫' else 0
            neon = tier(traits.get('霓虹', 0)) if c.origin == '霓虹' else 0
            wild = tier(traits.get('荒野', 0)) if c.origin == '荒野' else 0
            astral = tier(traits.get('星界', 0)) if c.origin == '星界' else 0
            ranger = tier(traits.get('游侠', 0)) if c.role == '游侠' else 0
            mage = tier(traits.get('术士', 0)) if c.role == '术士' else 0
            hp = round(c.hp * scale * (1 + guard * .2))
            row, col = divmod(u.pos, 7)
            fighters.append(dict(uid=u.uid, kind=u.kind, star=u.star, side=side,
                x=col if side == 0 else 6-col, y=3+row if side == 0 else 2-row,
                hp=hp, max_hp=hp, attack=c.attack*scale*(1+neon*.15),
                armor=(30 if c.role == '守卫' else 10)+guard*15,
                reach=c.reach, mana=astral*30, spell=c.spell, power=1+mage*.3,
                regen=wild*.02, delay=(2, 1.6, 1.3)[ranger], cooldown=rng.random()))
    frames = []

    def snap(tick, events):
        frames.append({'tick': tick, 'units': [
            {k: f[k] for k in ('uid', 'kind', 'star', 'side', 'x', 'y', 'hp', 'max_hp', 'mana')}
            for f in fighters if f['hp'] > 0], 'events': events})

    def distance(a, b):
        return max(abs(a['x']-b['x']), abs(a['y']-b['y']))

    def hit(target, raw):
        damage = max(1, round(raw * 100/(100 + target['armor'])))
        target['hp'] = max(0, target['hp'] - damage)
        target['mana'] = min(100, target['mana'] + 8)
        return damage

    snap(0, ['战斗开始'])
    for tick in range(1, 181):
        if len({f['side'] for f in fighters if f['hp'] > 0}) < 2:
            break
        events = []
        order = fighters[:]
        rng.shuffle(order)
        for f in order:
            if f['hp'] <= 0:
                continue
            enemies = [e for e in fighters if e['side'] != f['side'] and e['hp'] > 0]
            if not enemies:
                break
            if tick % 2 == 0:
                f['hp'] = min(f['max_hp'], f['hp'] + round(f['max_hp'] * f['regen']))
            target = min(enemies, key=lambda e: (distance(f, e), e['hp']))
            if distance(f, target) > f['reach']:
                # BFS finds a free cell in attack range, including paths around allies.
                occupied = {(e['x'], e['y']) for e in fighters if e['hp'] > 0 and e is not f}
                start = (f['x'], f['y'])
                queue = deque([(start, None)])
                seen = {start}
                while queue:
                    (x, y), first = queue.popleft()
                    if first and max(abs(x-target['x']), abs(y-target['y'])) <= f['reach']:
                        f['x'], f['y'] = first
                        break
                    neighbors = [(x+dx, y+dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
                    neighbors.sort(key=lambda p: max(abs(p[0]-target['x']), abs(p[1]-target['y'])))
                    for cell in neighbors:
                        if 0 <= cell[0] < 7 and 0 <= cell[1] < 6 and cell not in occupied and cell not in seen:
                            seen.add(cell)
                            queue.append((cell, first or cell))
                continue
            f['cooldown'] -= 1
            if f['cooldown'] > 0:
                continue
            f['cooldown'] += f['delay']
            label = CATALOG[f['kind']].name
            if f['mana'] >= 100:
                f['mana'] = 0
                power = f['power']
                if f['spell'] == 'shield':
                    f['hp'] = min(f['max_hp'], f['hp'] + round(f['max_hp']*.22*power))
                    f['armor'] += 12*power
                    events.append(f'{label} 施放铁壁')
                elif f['spell'] == 'heal':
                    ally = min((e for e in fighters if e['side'] == f['side'] and e['hp'] > 0), key=lambda e: e['hp']/e['max_hp'])
                    ally['hp'] = min(ally['max_hp'], ally['hp'] + round(f['max_hp']*.35*power))
                    events.append(f'{label} 治疗 {CATALOG[ally["kind"]].name}')
                else:
                    targets = [target] if f['spell'] == 'burst' else [e for e in enemies if distance(e, target) <= 1]
                    for enemy in targets:
                        hit(enemy, f['attack']*(3 if f['spell'] == 'burst' else 2.4)*power)
                    events.append(f'{label} 施放{"狙击" if f["spell"] == "burst" else "星爆"}')
            else:
                damage = hit(target, f['attack'] * rng.uniform(.92, 1.08))
                f['mana'] = min(100, f['mana'] + 25)
                events.append(f'{label} → {CATALOG[target["kind"]].name} -{damage}')
            if target['hp'] == 0:
                events.append(f'{CATALOG[target["kind"]].name} 倒下')
        # Overtime prevents infinite healing stalemates.
        if tick >= 120:
            for f in fighters:
                f['hp'] = max(0, f['hp'] - round(f['max_hp']*.03))
        snap(tick, events[-5:])
    survivors = [sum(f['side'] == s and f['hp'] > 0 for f in fighters) for s in (0, 1)]
    winner = 0 if survivors[0] and not survivors[1] else 1 if survivors[1] and not survivors[0] else None
    return BattleResult(winner, survivors, frames)


class Game:
    def __init__(self, seed=None, mode='codex', model=None):
        self.rng = random.Random(seed)
        self.round = 1
        self.phase = 'prep'
        self.mode = mode
        self.model = model
        self.next_uid = 1
        self.players = [Player(n, s) for n, s in zip(NAMES, STYLES)]
        self.ready = []
        self.ai_passes = {}
        self.history = []
        for p in self.players:
            p.shop = self.roll_shop(p.level)

    @property
    def finished(self):
        return sum(p.hp > 0 for p in self.players) <= 1 or (self.round >= 30 and self.phase == 'result')

    def make_unit(self, kind, star=1, pos=None):
        u = Unit(self.next_uid, kind, star, pos)
        self.next_uid += 1
        return u

    def roll_shop(self, level):
        costs = self.rng.choices([1, 2, 3, 4], SHOP_ODDS[level], k=5)
        return [self.rng.choice([k for k, c in CATALOG.items() if c.cost == cost]) for cost in costs]

    def editable(self, seat):
        if self.phase != 'prep' or self.finished or not 0 <= seat < 8 or self.players[seat].hp <= 0:
            raise RuleError('当前不能调整阵容')
        return self.players[seat]

    def buy(self, seat, slot):
        p = self.editable(seat)
        if type(slot) is not int or not 0 <= slot < 5 or p.shop[slot] is None:
            raise RuleError('这个商店位置没有棋子')
        kind = p.shop[slot]
        cost = CATALOG[kind].cost
        if p.gold < cost:
            raise RuleError('金币不足')
        # Trial merge keeps both purchase and capacity failure atomic.
        roster = copy.deepcopy(p.units) + [Unit(self.next_uid, kind)]
        for star in (1, 2):
            group = [u for u in roster if u.kind == kind and u.star == star]
            while len(group) >= 3:
                trio = sorted(group, key=lambda u: (u.pos is None, u.uid))[:3]
                keep = trio[0]
                keep.star += 1
                roster = [u for u in roster if u not in trio[1:]]
                group = [u for u in roster if u.kind == kind and u.star == star]
        if sum(u.pos is None for u in roster) > 8:
            raise RuleError('备战席已满；出售棋子或先上阵')
        p.units = roster
        p.gold -= cost
        p.shop[slot] = None
        self.next_uid += 1

    def unit(self, p, uid):
        found = next((u for u in p.units if u.uid == uid), None)
        if found is None:
            raise RuleError('找不到这枚棋子')
        return found

    def sell(self, seat, uid):
        p = self.editable(seat)
        u = self.unit(p, uid)
        p.gold += CATALOG[u.kind].cost * 3**(u.star-1)
        p.units.remove(u)

    def move(self, seat, uid, pos):
        p = self.editable(seat)
        u = self.unit(p, uid)
        if pos is not None and (type(pos) is not int or not 0 <= pos < 21):
            raise RuleError('棋盘位置须在 0–20 内')
        if u.pos == pos:
            return
        target = next((v for v in p.units if pos is not None and v.pos == pos), None)
        if pos is None and sum(v.pos is None for v in p.units) >= 8:
            raise RuleError('备战席已满')
        if u.pos is None and pos is not None and not target and sum(v.pos is not None for v in p.units) >= p.level:
            raise RuleError('上阵人口已满；可换下棋子或购买经验')
        if target:
            target.pos = u.pos
        u.pos = pos

    def refresh(self, seat):
        p = self.editable(seat)
        if p.gold < 2:
            raise RuleError('刷新需要 2 金币')
        p.gold -= 2
        p.shop = self.roll_shop(p.level)

    def gain_xp(self, p, amount):
        p.xp += amount
        while p.level < 8 and p.xp >= XP_NEED[p.level]:
            p.xp -= XP_NEED[p.level]
            p.level += 1
        if p.level == 8:
            p.xp = 0

    def buy_xp(self, seat):
        p = self.editable(seat)
        if p.gold < 4 or p.level >= 8:
            raise RuleError('购买经验需要 4 金币，最高 8 级')
        p.gold -= 4
        self.gain_xp(p, 4)

    def arrange(self, seat):
        p = self.editable(seat)
        chosen = sorted(p.units, key=lambda u: (u.star * 3 + CATALOG[u.kind].cost), reverse=True)[:p.level]
        for u in p.units:
            u.pos = None
        used = set()
        for u in chosen:
            row = 0 if CATALOG[u.kind].role == '守卫' else 2
            positions = [row*7+c for c in (3, 2, 4, 1, 5, 0, 6)] + list(range(21))
            u.pos = next(pos for pos in positions if pos not in used)
            used.add(u.pos)

    def pairings(self):
        alive = [i for i, p in enumerate(self.players) if p.hp > 0]
        # Round-dependent shuffle without consuming game RNG: preview equals actual pairing.
        random.Random(self.round * 7919 + sum(alive)*101).shuffle(alive)
        pairs = [(alive[i], alive[i+1], False) for i in range(0, len(alive)-1, 2)]
        if len(alive) % 2 and len(alive) > 1:
            pairs.append((alive[-1], alive[(self.round-1) % (len(alive)-1)], True))
        return pairs

    def resolve_round(self):
        if self.phase != 'prep' or self.finished:
            raise RuleError('这一轮已经结算')
        results = []
        for a, b, ghost in self.pairings():
            result = battle(self.players[a].units, self.players[b].units, self.rng.randrange(2**32))
            results.append((a, b, ghost, result))
            for side, seat in enumerate((a, b)):
                if ghost and side == 1:
                    continue
                p = self.players[seat]
                if result.winner == side:
                    p.gold += 1
                    p.streak = max(0, p.streak) + 1
                    p.last = '胜利 +1 金币'
                else:
                    damage = 2 + self.round//3 + (result.survivors[1-side] if result.winner is not None else 0)
                    p.hp = max(0, p.hp-damage)
                    p.streak = min(0, p.streak) - 1
                    p.last = f'{"平局" if result.winner is None else "落败"} -{damage} 生命'
                    if p.hp == 0:
                        p.eliminated = self.round
        self.phase = 'result'
        self.history.append({'round': self.round, 'results': [dict(a=a, b=b, ghost=g, winner=r.winner,
                             survivors=r.survivors) for a, b, g, r in results]})
        return results

    def next_round(self):
        if self.finished:
            return
        if self.phase != 'result':
            raise RuleError('请先完成战斗')
        self.round += 1
        self.phase = 'prep'
        self.ready = []
        self.ai_passes = {}
        for p in self.players:
            if p.hp <= 0:
                continue
            p.income = 5 + min(p.gold//10, 5) + min(abs(p.streak)//2, 3)
            p.gold += p.income
            self.gain_xp(p, 2)
            if not p.locked:
                p.shop = self.roll_shop(p.level)

    def standings(self):
        # Equal elimination rounds are tied in the UI; seat order is only a stable tiebreak.
        return sorted(range(8), key=lambda i: (self.players[i].hp > 0, self.players[i].eliminated,
                      self.players[i].hp, self.players[i].gold), reverse=True)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {k: v for k, v in self.__dict__.items() if k not in ('rng', 'players')}
        state.update(version=1, players=[asdict(p) for p in self.players], rng=self.rng.getstate())
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if data.pop('version') != 1:
                raise ValueError('不支持的存档版本')
            def tuples(value):
                return tuple(tuples(v) for v in value) if isinstance(value, list) else value
            rng_state = tuples(data.pop('rng'))
            rows = data.pop('players')
            g = cls.__new__(cls)
            g.__dict__.update(data)
            g.rng = random.Random()
            g.rng.setstate(rng_state)
            g.players = [Player(**{**p, 'units': [Unit(**u) for u in p['units']]}) for p in rows]
            if len(g.players) != 8 or g.phase not in ('prep', 'result') or not 1 <= g.round <= 30 or g.mode not in ('codex', 'local'):
                raise ValueError('存档状态无效')
            all_ids = []
            for p in g.players:
                positions = [u.pos for u in p.units if u.pos is not None]
                if not (2 <= p.level <= 8 and p.gold >= 0 and 0 <= p.hp <= 60 and len(p.shop) == 5):
                    raise ValueError('玩家状态无效')
                if len(positions) != len(set(positions)) or len(positions) > p.level or len(p.units)-len(positions) > 8:
                    raise ValueError('棋盘状态无效')
                if any(k is not None and k not in CATALOG for k in p.shop):
                    raise ValueError('商店无效')
                for u in p.units:
                    if u.kind not in CATALOG or u.star not in (1, 2, 3) or (u.pos is not None and (type(u.pos) is not int or not 0 <= u.pos < 21)):
                        raise ValueError('棋子无效')
                    all_ids.append(u.uid)
            if len(all_ids) != len(set(all_ids)) or (all_ids and g.next_uid <= max(all_ids)):
                raise ValueError('棋子编号无效')
            return g
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            raise ValueError(f'无法读取存档：{e}') from e
