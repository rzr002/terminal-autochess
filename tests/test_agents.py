import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from autochess.engine import Game, RuleError
try:
    from autochess.agents import observe, apply_plan, LocalAgent, CodexAgent, AgentError, prepare_opponents
except ImportError:
    observe = None


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(observe, 'AI 对手尚未实现')
        self.g = Game(seed=8, mode='local')

    def plan(self, **kwargs):
        return dict({'sell': [], 'buy': [], 'xp_buys': 0, 'formation': [], 'lock': False, 'reroll': False}, **kwargs)

    def test_observation_never_exposes_other_shops_benches_or_rng(self):
        p = self.g.players[2]
        p.units = [self.g.make_unit('spark'), self.g.make_unit('volt', pos=0)]
        obs = observe(self.g, 1)
        self.assertEqual(obs['self']['shop'], self.g.players[1].shop)
        other = obs['opponents'][1]
        self.assertNotIn('shop', other)
        self.assertNotIn('rng', obs)
        self.assertEqual([u['kind'] for u in other['board']], ['volt'])

    def test_plan_is_atomic_when_a_late_action_is_illegal(self):
        before = copy.deepcopy(self.g.__dict__)
        plan = self.plan(buy=[0, 0])
        with self.assertRaises(AgentError):
            apply_plan(self.g, 1, plan)
        self.assertEqual(self.g.players, before['players'])
        self.assertEqual(self.g.next_uid, before['next_uid'])

    def test_model_can_buy_and_position_a_new_unit(self):
        self.g.players[1].shop[0] = 'spark'
        plan = self.plan(buy=[0], formation=[{'kind': 'spark', 'pos': 2}])
        apply_plan(self.g, 1, plan)
        self.assertEqual(self.g.players[1].units[0].pos, 2)

    def test_formation_uses_upgraded_copy_after_merge(self):
        p = self.g.players[1]
        p.units = [self.g.make_unit('spark'), self.g.make_unit('spark')]
        p.shop[0] = 'spark'
        apply_plan(self.g, 1, self.plan(buy=[0], formation=[{'kind': 'spark', 'pos': 0}]))
        self.assertEqual([(u.star, u.pos) for u in self.g.players[1].units], [(2, 0)])

    def test_invalid_deployment_is_rejected_without_local_substitution(self):
        with self.assertRaises(AgentError):
            apply_plan(self.g, 1, self.plan(formation=[{'kind': 'zero', 'pos': 0}]))
        self.assertEqual(self.g.players[1].units, [])

    def test_bool_is_not_an_integer_buy_slot(self):
        with self.assertRaises(AgentError):
            apply_plan(self.g, 1, self.plan(buy=[True]))

    def test_duplicate_positions_are_rejected(self):
        p = self.g.players[1]
        p.units = [self.g.make_unit('spark'), self.g.make_unit('volt')]
        with self.assertRaises(AgentError):
            apply_plan(self.g, 1, self.plan(formation=[{'kind':'spark','pos':0}, {'kind':'volt','pos':0}]))

    def test_local_agent_produces_a_funded_deployed_team(self):
        plan = LocalAgent().decide(observe(self.g, 1))
        apply_plan(self.g, 1, plan)
        p = self.g.players[1]
        self.assertGreater(sum(u.pos is not None for u in p.units), 0)
        self.assertGreaterEqual(p.gold, 0)

    def test_prepare_has_seven_independent_opponents_and_can_resume(self):
        prepared = prepare_opponents(self.g, LocalAgent(), threading.Event())
        self.assertIsNone(prepared.error)
        self.assertEqual(sorted(prepared.game.ready), list(range(1, 8)))
        before = copy.deepcopy(prepared.game.players)
        again = prepare_opponents(prepared.game, LocalAgent(), threading.Event())
        self.assertEqual(again.game.players, before)
        self.assertTrue(all(p.units for p in again.game.players[1:]))

    def test_failed_agent_preserves_game_and_returns_error(self):
        class Broken:
            source = 'codex'
            def decide(self, obs, cancel=None):
                raise AgentError('connection failed')
        result = prepare_opponents(self.g, Broken(), threading.Event())
        self.assertIn('connection failed', result.error)
        self.assertEqual(result.game.ready, [])
        self.assertEqual(result.game.players, self.g.players)

    def test_real_subprocess_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'fake-codex'
            payload = json.dumps(self.plan())
            binary.write_text('#!/usr/bin/env python3\nimport sys,pathlib\na=sys.argv\nassert "--ignore-user-config" in a\nassert "read-only" in a\nassert "--ephemeral" in a\nassert "features.shell_tool=false" in a\npathlib.Path(a[a.index("-o")+1]).write_text(' + repr(payload) + ')\n')
            binary.chmod(0o755)
            plan = CodexAgent(binary=str(binary), timeout=3).decide(observe(self.g, 1))
            self.assertEqual(plan, self.plan())

    def test_subprocess_timeout_and_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'slow-codex'
            binary.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n')
            binary.chmod(0o755)
            with self.assertRaises(AgentError):
                CodexAgent(binary=str(binary), timeout=.1).decide(observe(self.g, 1))
            event = threading.Event()
            event.set()
            with self.assertRaises(InterruptedError):
                CodexAgent(binary=str(binary)).decide(observe(self.g, 1), event)

    def test_local_full_match_completes_with_legal_rosters(self):
        agent = LocalAgent()
        for _ in range(30):
            if self.g.finished:
                break
            for seat, p in enumerate(self.g.players):
                if p.hp:
                    apply_plan(self.g, seat, agent.decide(observe(self.g, seat)))
                    p = self.g.players[seat]
                    self.assertLessEqual(sum(u.pos is not None for u in p.units), p.level)
                    self.assertLessEqual(sum(u.pos is None for u in p.units), 8)
                    self.assertGreaterEqual(p.gold, 0)
            self.g.resolve_round()
            self.g.next_round()
        self.assertTrue(self.g.finished)


if __name__ == '__main__':
    unittest.main()
