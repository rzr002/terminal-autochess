import copy
import tempfile
import unittest
from pathlib import Path

try:
    from autochess.engine import Game, RuleError, Unit, CATALOG, synergies, battle
except ImportError:
    Game = None


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Game, '自走棋引擎尚未实现')
        self.g = Game(seed=42)
        self.p = self.g.players[0]

    def add(self, kind='spark', star=1, pos=None):
        unit = self.g.make_unit(kind, star, pos)
        self.p.units.append(unit)
        return unit

    def test_eight_seats_and_five_card_shop(self):
        self.assertEqual(len(self.g.players), 8)
        self.assertTrue(all(len(p.shop) == 5 for p in self.g.players))
        self.assertEqual(self.g.round, 1)
        self.assertEqual(len({p.name for p in self.g.players}), 8)

    def test_buy_spends_gold_and_removes_shop_slot(self):
        self.p.shop[0] = 'spark'
        before = self.p.gold
        self.g.buy(0, 0)
        self.assertEqual(self.p.gold, before - CATALOG['spark'].cost)
        self.assertIsNone(self.p.shop[0])
        self.assertEqual(self.p.units[0].kind, 'spark')
        with self.assertRaises(RuleError):
            self.g.buy(0, 0)

    def test_unaffordable_buy_is_atomic(self):
        self.p.gold = 0
        before = copy.deepcopy(self.p)
        with self.assertRaises(RuleError):
            self.g.buy(0, 0)
        self.assertEqual(self.p, before)

    def test_three_copies_merge_and_preserve_board_position(self):
        self.add(pos=8)
        self.add()
        self.p.shop[0] = 'spark'
        self.g.buy(0, 0)
        self.assertEqual([(u.kind, u.star, u.pos) for u in self.p.units], [('spark', 2, 8)])

    def test_nine_copies_chain_merge(self):
        self.add(star=2, pos=0)
        self.add(star=2)
        self.add()
        self.add()
        self.p.shop[0] = 'spark'
        self.g.buy(0, 0)
        self.assertEqual([(u.star, u.pos) for u in self.p.units], [(3, 0)])

    def test_full_bench_can_buy_only_if_merge_frees_space(self):
        for i in range(8):
            self.add('spark' if i < 2 else 'bark')
        self.p.shop[0] = 'spark'
        self.g.buy(0, 0)
        self.assertEqual(len(self.p.units), 7)
        self.add('bark')
        self.p.shop[1] = 'oracle'
        with self.assertRaises(RuleError):
            self.g.buy(0, 1)

    def test_deployment_limit_and_swapping(self):
        self.p.level = 2
        a, b, c = self.add(), self.add('bark'), self.add('oracle')
        self.g.move(0, a.uid, 0)
        self.g.move(0, b.uid, 1)
        with self.assertRaises(RuleError):
            self.g.move(0, c.uid, 2)
        self.g.move(0, c.uid, 0)
        self.assertIsNone(a.pos)
        self.assertEqual(c.pos, 0)
        self.g.move(0, b.uid, 0)
        self.assertEqual((b.pos, c.pos), (0, 1))

    def test_synergies_count_unique_champions_only_on_board(self):
        self.add('spark', pos=0)
        self.add('spark', star=2, pos=1)
        self.add('volt')
        self.assertEqual(synergies(self.p.units).get('霓虹'), 1)
        self.p.units[2].pos = 2
        self.assertEqual(synergies(self.p.units)['霓虹'], 2)

    def test_refresh_and_xp_cost_and_level(self):
        self.p.gold = 30
        self.g.refresh(0)
        self.assertEqual(self.p.gold, 28)
        old = self.p.level
        self.g.buy_xp(0)
        self.assertEqual(self.p.gold, 24)
        self.assertGreater(self.p.level, old)

    def test_sell_refunds_embodied_copies(self):
        u = self.add(star=2)
        old = self.p.gold
        self.g.sell(0, u.uid)
        self.assertEqual(self.p.gold, old + CATALOG['spark'].cost * 3)
        self.assertFalse(self.p.units)

    def test_locked_shop_survives_next_round_and_interest_is_capped(self):
        self.p.gold = 100
        self.p.locked = True
        shop = self.p.shop[:]
        self.g.resolve_round()
        self.g.next_round()
        self.assertEqual(self.p.shop, shop)
        self.assertGreaterEqual(self.p.gold, 110)
        self.assertLessEqual(self.p.gold, 114)

    def test_battle_is_deterministic_and_does_not_mutate_rosters(self):
        a = [Unit(1, 'spark', 2, 0), Unit(2, 'volt', 1, 15)]
        b = [Unit(3, 'bark', 1, 0)]
        before = copy.deepcopy((a, b))
        result = battle(a, b, 88)
        self.assertEqual((a, b), before)
        self.assertEqual(result, battle(a, b, 88))
        self.assertEqual(result.winner, 0)
        self.assertGreater(len(result.frames), 1)
        self.assertLessEqual(len(result.frames), 182)

    def test_empty_board_loses_and_draw_hurts_both(self):
        self.assertEqual(battle([], [Unit(1, 'spark', 1, 0)], 1).winner, 1)
        self.assertIsNone(battle([], [], 1).winner)
        self.g.resolve_round()
        self.assertTrue(all(p.hp < 60 for p in self.g.players))

    def test_pairings_cover_every_alive_seat_once(self):
        self.assertEqual(sorted(i for pair in self.g.pairings() for i in pair[:2]), list(range(8)))
        self.g.players[7].hp = 0
        pairs = self.g.pairings()
        counts = {i: 0 for i in range(7)}
        for a, b, ghost in pairs:
            counts[a] += 1
            if not ghost:
                counts[b] += 1
        self.assertTrue(all(n == 1 for n in counts.values()))

    def test_round_cannot_resolve_twice_or_accept_purchases_after_combat(self):
        self.g.resolve_round()
        with self.assertRaises(RuleError):
            self.g.resolve_round()
        with self.assertRaises(RuleError):
            self.g.buy(0, 0)

    def test_save_resume_preserves_rng_and_rejects_corruption(self):
        self.g.buy(0, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'game.json'
            self.g.save(path)
            resumed = Game.load(path)
            self.assertEqual(resumed.players, self.g.players)
            self.g.refresh(0)
            resumed.refresh(0)
            self.assertEqual(resumed.players, self.g.players)
            path.write_text('{bad json', encoding='utf-8')
            with self.assertRaises(ValueError):
                Game.load(path)

    def test_match_has_a_finite_winner(self):
        for _ in range(40):
            if self.g.finished:
                break
            self.g.resolve_round()
            self.g.next_round()
        self.assertTrue(self.g.finished)
        self.assertEqual(len(self.g.standings()), 8)
        self.assertEqual(len(set(self.g.standings())), 8)


if __name__ == '__main__':
    unittest.main()
