"""CLI entry points for interactive play and reproducible simulations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import threading
import time

from .engine import Game
from .agents import CodexAgent, LocalAgent, AgentError, apply_plan, observe, prepare_opponents, configured_model
from .ui import Controller, run_curses, run_plain

ROOT = Path(__file__).resolve().parents[1]


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('请输入正整数')
    return number


def parser():
    p = argparse.ArgumentParser(description='摸鱼棋局：你和 7 位 AI 的终端自走棋。默认真实 Codex 对手，自动续存档。')
    p.add_argument('--agent', choices=['codex', 'local'], help='对手来源；新局默认 codex，local 为离线程序策略')
    p.add_argument('--model', help='Codex 模型 ID；默认读取本机配置')
    p.add_argument('--new', action='store_true', help='新开一局，旧存档自动备份')
    p.add_argument('--save', type=Path, default=ROOT / '.saves' / 'autosave.json', help='存档路径')
    p.add_argument('--seed', type=int, help='随机种子，便于复现')
    p.add_argument('--plain', action='store_true', help='使用逐行命令界面')
    p.add_argument('--headless', action='store_true', help='无界面模拟；玩家位由离线策略代打，对手遵循 --agent')
    p.add_argument('--rounds', type=positive, default=30, help='无界面模式最多运行轮数，默认30')
    p.add_argument('--timeout', type=positive, default=90, help='每次 Codex 请求超时秒数，默认90')
    p.add_argument('--check-codex', action='store_true', help='发出一次真实模型请求并校验行动')
    return p


def headless(args):
    game = Game(seed=args.seed, mode=args.agent or 'codex', model=args.model or configured_model())
    agent = CodexAgent(model=game.model, timeout=args.timeout) if game.mode == 'codex' else LocalAgent()
    hero = LocalAgent()
    rounds = []
    started = time.monotonic()
    for _ in range(min(30, args.rounds)):
        if game.finished:
            break
        if game.players[0].hp > 0:
            plan = hero.decide(observe(game, 0))
            apply_plan(game, 0, plan)
        cancel = threading.Event()
        result = prepare_opponents(game, agent, cancel)
        game = result.game
        if result.error:
            raise AgentError(result.error)
        rosters = [{'seat': i, 'name': p.name, 'gold': p.gold, 'level': p.level,
                    'board': [asdict(u) for u in p.units if u.pos is not None]} for i, p in enumerate(game.players)]
        game.resolve_round()
        rounds.append({'round': game.round, 'model_decisions': result.decisions if game.mode == 'codex' else 0,
                       'rosters': rosters, 'matches': game.history[-1]['results']})
        if game.finished or len(rounds) >= args.rounds:
            break
        game.next_round()
    report = {'opponent_source': game.mode, 'hero_source': 'local (simulation only)', 'model': game.model,
              'elapsed_seconds': round(time.monotonic()-started, 2), 'finished': game.finished,
              'rounds_played': len(rounds), 'standings': [{'rank': rank+1, 'name': game.players[i].name,
              'hp': game.players[i].hp} for rank, i in enumerate(game.standings())], 'rounds': rounds}
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.check_codex:
            game = Game(seed=args.seed, model=args.model or configured_model())
            started = time.monotonic()
            plan = CodexAgent(model=game.model, timeout=args.timeout).decide(observe(game, 1))
            apply_plan(game, 1, plan)
            print(json.dumps({'ok': True, 'source': 'codex', 'model': game.model,
                              'elapsed_seconds': round(time.monotonic()-started, 2), 'plan': plan}, ensure_ascii=False, indent=2))
            return 0
        if args.headless:
            headless(args)
            return 0
        if args.save.exists() and not args.new:
            game = Game.load(args.save)
            if args.agent and args.agent != game.mode:
                raise ValueError('存档的对手模式不同；请用 --new 新开一局，或使用原模式继续')
            if args.model:
                game.model = args.model
            print(f'继续第 {game.round} 轮 · {game.mode.upper()}')
        else:
            if args.save.exists():
                backup = args.save.with_name(args.save.stem + '.previous-' + str(time.time_ns()) + args.save.suffix)
                shutil.copy2(args.save, backup)
            game = Game(seed=args.seed, mode=args.agent or 'codex', model=args.model or configured_model())
        if game.mode == 'codex' and not shutil.which('codex'):
            raise ValueError('未找到 Codex CLI。安装并运行 codex login 后重试；离线试玩用 --agent local --new。')
        controller = Controller(game, args.save, timeout=args.timeout)
        if game.phase == 'result':
            controller.message = controller.result_message()
        if args.plain or not sys.stdin.isatty() or not sys.stdout.isatty():
            run_plain(controller)
        else:
            try:
                import curses
            except ImportError:
                run_plain(controller)
            else:
                try:
                    run_curses(controller)
                except curses.error as error:
                    print(f'全屏界面不可用：{error}。请加 --plain 重试。', file=sys.stderr)
                    return 1
        print(f'进度已保存：{args.save}')
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, AgentError) as error:
        print(f'错误：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
