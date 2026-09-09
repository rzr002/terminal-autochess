"""Opponent planners. The rules engine validates every model action atomically."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.request

from .engine import CATALOG, TRAITS, XP_NEED, Game, Player, Unit, RuleError


class AgentError(RuntimeError):
    pass


def configured_model():
    root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    try:
        model = tomllib.loads((root / 'config.toml').read_text(encoding='utf-8')).get('model')
        return model if isinstance(model, str) else None
    except (OSError, ValueError):
        return None


def observe(game, seat):
    p = game.players[seat]
    passes = getattr(game, 'ai_passes', {})
    return {'round': game.round, 'seat': seat, 'self': asdict(p),
            'reroll_allowed': passes.get(str(seat), 0) < 1,
            'opponents': [{'seat': i, 'name': other.name, 'hp': other.hp, 'level': other.level,
                           'board': [asdict(u) for u in other.units if u.pos is not None]}
                          for i, other in enumerate(game.players) if i != seat],
            'catalog': {k: asdict(c) for k, c in CATALOG.items()},
            'traits': TRAITS, 'xp_needed': XP_NEED}


def apply_plan(game, seat, plan):
    """All or nothing. A bad plan can never partly spend a player's gold."""
    try:
        required = {'sell', 'buy', 'xp_buys', 'formation', 'lock', 'reroll'}
        if not isinstance(plan, dict) or set(plan) != required:
            raise RuleError('行动字段不完整')
        if any(not isinstance(plan[k], list) for k in ('sell', 'buy', 'formation')):
            raise RuleError('行动列表格式错误')
        if type(plan['xp_buys']) is not int or not 0 <= plan['xp_buys'] <= 20:
            raise RuleError('经验购买次数无效')
        if type(plan['lock']) is not bool or type(plan['reroll']) is not bool:
            raise RuleError('锁定或刷新格式无效')
        if len(plan['sell']) > 16 or len(plan['buy']) > 5 or len(plan['formation']) > 8:
            raise RuleError('行动数量过多')
        trial = copy.deepcopy(game)
        p = trial.editable(seat)
        for uid in plan['sell']:
            if type(uid) is not int:
                raise RuleError('出售编号无效')
            trial.sell(seat, uid)
        for _ in range(plan['xp_buys']):
            trial.buy_xp(seat)
        for slot in plan['buy']:
            trial.buy(seat, slot)
        p = trial.players[seat]
        for u in p.units:
            u.pos = None
        used = set()
        for entry in plan['formation']:
            if not isinstance(entry, dict) or set(entry) != {'kind', 'pos'} or entry['kind'] not in CATALOG:
                raise RuleError('布阵棋子无效')
            pos = entry['pos']
            if type(pos) is not int or not 0 <= pos < 21 or pos in used:
                raise RuleError('布阵位置重复或越界')
            candidates = [u for u in p.units if u.kind == entry['kind'] and u.pos is None]
            if not candidates:
                raise RuleError(f'布阵中没有可用的 {entry["kind"]}')
            max(candidates, key=lambda u: u.star).pos = pos
            used.add(pos)
        if len(used) > p.level or sum(u.pos is None for u in p.units) > 8:
            raise RuleError('布阵超出人口或备战席上限')
        p.locked = plan['lock']
        if plan['reroll']:
            if not observe(game, seat)['reroll_allowed']:
                raise RuleError('本回合 AI 刷新次数已用完')
            trial.refresh(seat)
        game.__dict__.update(trial.__dict__)
    except (RuleError, TypeError, KeyError) as error:
        raise AgentError(f'AI 行动不合法：{error}') from error


class LocalAgent:
    source = 'local'

    def decide(self, obs, cancel=None):
        if cancel and cancel.is_set():
            raise InterruptedError('已取消')
        # A private simulation is used solely to budget a legal plan.
        g = Game(seed=0, mode='local')
        seat = obs['seat']
        state = obs['self']
        g.players[seat] = Player(**{**state, 'units': [Unit(**u) for u in state['units']]})
        g.next_uid = max([u.uid for u in g.players[seat].units] + [10000]) + 1
        g.ai_passes = {str(seat): 0 if obs['reroll_allowed'] else 1}
        p = g.players[seat]
        plan = {'sell': [], 'buy': [], 'xp_buys': 0, 'formation': [], 'lock': False, 'reroll': False}
        preferences = {'星界法术': '星界', '荒野续航': '荒野', '霓虹快攻': '霓虹',
                       '游侠后排': '游侠', '守卫前排': '守卫'}
        preference = preferences.get(p.style)
        reserve = 0 if obs['round'] <= 3 or p.hp <= 22 else min(40, max(0, (obs['round']-3)*6))
        if p.style == '经济速升':
            reserve = min(reserve, 20)
        # Free low-value bench space before buying; avoid selling valuable pairs.
        if sum(u.pos is None for u in p.units) >= 7:
            counts = {}
            for u in p.units:
                counts[u.kind] = counts.get(u.kind, 0) + 1
            extras = sorted((u for u in p.units if u.pos is None and counts[u.kind] == 1),
                            key=lambda u: (u.star, CATALOG[u.kind].cost))
            for u in extras[:2]:
                if u.star == 1:
                    plan['sell'].append(u.uid)
                    g.sell(seat, u.uid)
        target_level = min(8, 2 + obs['round']//3 + (p.style == '经济速升'))
        while p.level < target_level and p.gold >= reserve + 8:
            g.buy_xp(seat)
            plan['xp_buys'] += 1

        def score(slot):
            k = p.shop[slot]
            if k is None:
                return -100
            c = CATALOG[k]
            copies = sum(u.kind == k and u.star < 3 for u in p.units)
            affinity = 2 if preference in (c.origin, c.role) else 0
            return c.cost + affinity + copies*3 + (4 if copies == 2 else 0)

        for slot in sorted(range(5), key=score, reverse=True):
            k = p.shop[slot]
            if k is None:
                continue
            copies = sum(u.kind == k and u.star < 3 for u in p.units)
            threshold = 0 if len(p.units) < p.level or copies >= 2 else reserve
            useful = len(p.units) < p.level + 3 or copies > 0
            if p.gold-CATALOG[k].cost < threshold or not useful:
                continue
            try:
                g.buy(seat, slot)
                plan['buy'].append(slot)
            except RuleError:
                continue
        g.arrange(seat)
        plan['formation'] = [{'kind': u.kind, 'pos': u.pos} for u in p.units if u.pos is not None]
        # Save remaining shop pairs when preserving interest; otherwise one optional roll.
        plan['lock'] = any(k and sum(u.kind == k and u.star == 1 for u in p.units) >= 2 for k in p.shop)
        plan['reroll'] = bool(obs['reroll_allowed'] and not plan['lock'] and p.gold >= reserve + 8 and obs['round'] >= 3)
        return plan


SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['sell', 'buy', 'xp_buys', 'formation', 'lock', 'reroll'],
          'properties': {
              'sell': {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 16},
              'buy': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 4}, 'maxItems': 5},
              'xp_buys': {'type': 'integer', 'minimum': 0, 'maximum': 20},
              'formation': {'type': 'array', 'maxItems': 8, 'items': {'type': 'object', 'additionalProperties': False,
                  'required': ['kind', 'pos'], 'properties': {'kind': {'type': 'string', 'enum': list(CATALOG)},
                                                           'pos': {'type': 'integer', 'minimum': 0, 'maximum': 20}}}},
              'lock': {'type': 'boolean'}, 'reroll': {'type': 'boolean'}}}
PROMPT = '''你在玩原创终端自走棋。你是一名独立玩家，目标是夺冠。根据 self.style 保持自己的运营风格，独立竞争。
只基于提供的观测做决策；禁止调用任何工具、文件或网络。不知道他人商店或备战席，也不知道未来商店。
规则：8人，初始60血10金2级。每轮5基础收入，10金1利息(上限5)，每2连胜/败1奖励(上限3)，胜利+1金。每轮自动+2经验。
每4金币购买4经验；xp_needed是每级到下一级所需经验。最高8级。上阵数<=等级；备战席<=8。
三枚同名同星棋子自动合成高一星，上限三星；合成保留已有棋盘位置优先。售出返还cost*3^(star-1)。
2星生命和攻击是1星1.8倍，3星3.24倍。守卫前排、远程后排。羁绊只计上阵的不同名字，不计重复名字。
己方棋盘3行7列，pos为0..20，0..6是前排，7..13中排，14..20后排。敌人从前方接近，左右镜像。
一次返回整批计划，严格按以下顺序执行：sell中现有uid出售 → xp_buys次购买经验 → buy中的0起始商店槽位按顺序购买 → formation完整重新布阵 → lock锁店 → 可选reroll。
formation使用购买合成后的棋子kind；同名优先使用最高星，需要两枚同名上阵时列两次。必须拥有指定棋子，位置不可重复。未列入的棋子留在备战席。
购买阶段每次买后备战席不得超过8(合成可以腾位)，资金总额必须足够；留意升级后经验归零/扣减。不要买重复的同一商店槽位。
reroll=true在末尾花2金刷新，并且你会再收到一次新商店观测进行购买布阵。每回合最多刷新一次；reroll_allowed=false时必须返回false。
请积极购买和上阵，凑羁绊，寻找三星，适时升人口；保持合理利息，低血量时花钱保命。确保回合结束时尽量满编。仅返回schema JSON。
观测：
'''


class CodexAgent:
    source = 'codex'

    def __init__(self, binary=None, model=None, timeout=90):
        self.binary = binary or shutil.which('codex') or 'codex'
        self.model = model or configured_model()
        self.timeout = timeout

    @staticmethod
    def stop(process):
        if process.poll() is not None:
            return
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()

    def decide(self, obs, cancel=None):
        if cancel and cancel.is_set():
            raise InterruptedError('已取消')
        try:
            with tempfile.TemporaryDirectory(prefix='autochess-agent-') as folder:
                root = Path(folder)
                schema, output = root / 'schema.json', root / 'decision.json'
                schema.write_text(json.dumps(SCHEMA), encoding='utf-8')
                (root / 'prompt.txt').write_text(PROMPT + json.dumps(obs, ensure_ascii=False), encoding='utf-8')
                command = [self.binary, '-a', 'never', 'exec', '--ignore-user-config', '--sandbox', 'read-only',
                           '--skip-git-repo-check', '--ephemeral', '--color', 'never', '-C', folder,
                           '--output-schema', str(schema), '-o', str(output),
                           '-c', 'project_doc_max_bytes=0', '-c', 'web_search="disabled"',
                           '-c', 'model_reasoning_effort="low"']
                for feature in ('shell_tool', 'apps', 'plugins', 'multi_agent', 'memories', 'hooks'):
                    command += ['-c', f'features.{feature}=false']
                if self.model:
                    command += ['--model', self.model]
                command.append('-')
                env = os.environ.copy()
                for scheme, value in urllib.request.getproxies().items():
                    if scheme in ('http', 'https', 'all'):
                        env[f'{scheme.upper()}_PROXY'] = value
                    elif scheme == 'no':
                        env['NO_PROXY'] = value
                with (root / 'prompt.txt').open(encoding='utf-8') as source, (root / 'stdout.log').open('w') as stdout, (root / 'stderr.log').open('w') as stderr:
                    process = subprocess.Popen(command, stdin=source, stdout=stdout, stderr=stderr, cwd=folder,
                                               env=env, start_new_session=os.name == 'posix')
                    try:
                        start = time.monotonic()
                        while process.poll() is None:
                            if cancel and cancel.is_set():
                                raise InterruptedError('已取消')
                            if time.monotonic()-start >= self.timeout:
                                raise AgentError(f'Codex 等待超过 {self.timeout:g} 秒，按空格重试')
                            time.sleep(.05)
                        if process.returncode != 0:
                            raise AgentError(f'Codex 退出码 {process.returncode}；检查 codex login、模型和网络')
                        if not output.is_file():
                            raise AgentError('Codex 没有返回行动')
                        return json.loads(output.read_text(encoding='utf-8'))
                    finally:
                        self.stop(process)
        except (OSError, ValueError) as error:
            raise AgentError(f'Codex 请求失败：{error}') from error


@dataclass
class Preparation:
    game: Game
    error: str | None = None
    decisions: int = 0


def prepare_opponents(game, agent, cancel, progress=None):
    """Plan concurrently, apply on one worker. A private copy isolates the live UI.

    Completed opponents and refresh passes survive a failed request/retry.
    """
    result = Preparation(copy.deepcopy(game))
    g = result.game
    if not hasattr(g, 'ai_passes'):
        g.ai_passes = {}
    pending = [i for i in range(1, 8) if g.players[i].hp > 0 and i not in g.ready]
    try:
        for _ in range(2):
            if not pending or cancel.is_set():
                break
            again = []
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(agent.decide, observe(g, seat), cancel): seat for seat in pending}
                for future in as_completed(futures):
                    seat = futures[future]
                    if cancel.is_set():
                        continue
                    try:
                        plan = future.result()
                        apply_plan(g, seat, plan)
                        result.decisions += 1
                        if plan['reroll']:
                            g.ai_passes[str(seat)] = 1
                            again.append(seat)
                        else:
                            g.ready.append(seat)
                        if progress:
                            progress(f'{g.players[seat].name} 已{"刷新商店" if plan["reroll"] else "准备就绪"} · {len(g.ready)}/' + str(sum(p.hp > 0 for p in g.players[1:])))
                    except (AgentError, InterruptedError) as error:
                        result.error = f'{g.players[seat].name}：{error}'
                        cancel.set()
            pending = again
    except Exception as error:
        # Keep a usable save even if an unexpected provider failure occurs.
        result.error = f'准备中断：{error}'
    return result
