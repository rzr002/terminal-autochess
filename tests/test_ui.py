import unittest
from pathlib import Path
import tempfile
from autochess.engine import Game
try:
    from autochess.ui import Controller, render_lines, display_width, clip, plain_command
except ImportError:
    Controller = None


class UITests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Controller, '终端界面尚未实现')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Controller(Game(seed=6, mode='local'), Path(self.tmp.name) / 'save.json')
        self.addCleanup(self.c.close)

    def test_chinese_width_and_clipping(self):
        self.assertEqual(display_width('火花 2*'), 7)
        self.assertEqual(clip('火花 abc', 3), '火')
        self.assertEqual(clip('a\x1bb\nc', 20), 'abc')

    def test_default_board_contains_shop_and_all_opponents_at_two_sizes(self):
        for width, height in [(80, 24), (108, 38)]:
            lines = render_lines(self.c, width, height)
            text = '\n'.join(lines)
            self.assertEqual(len(lines), height)
            self.assertTrue(all(display_width(line) <= width for line in lines))
            for name in ('NOVA','MOSS','BLAZE','ECHO','ATLAS','JADE','ORBIT','商店','备战席'):
                self.assertIn(name, text)

    def test_boss_key_hides_all_game_content_and_prevents_actions(self):
        self.c.key('b')
        before = self.c.game.players[0].gold
        self.c.key('1')
        text = '\n'.join(render_lines(self.c, 108, 38))
        self.assertIn('service', text)
        self.assertNotIn('NOVA', text)
        self.assertNotIn('商店', text)
        self.assertEqual(self.c.game.players[0].gold, before)
        self.c.key('b')
        self.assertFalse(self.c.hidden)

    def press(self, *keys):
        for key in keys:
            self.c.key(key)

    def test_shop_purchase_only_needs_arrows_and_enter(self):
        self.assertEqual(self.c.focus, 'shop')
        self.press('RIGHT', 'ENTER')
        self.assertIsNone(self.c.game.players[0].shop[1])
        self.assertEqual(len(self.c.game.players[0].units), 1)

    def test_bench_menu_deploys_without_tab_or_shortcuts(self):
        self.press('ENTER', 'UP', 'ENTER')
        text = '\n'.join(render_lines(self.c, 80, 24))
        self.assertIn('上阵', text)
        self.assertIn('出售', text)
        self.press('ENTER')
        self.assertIsNotNone(self.c.game.players[0].units[0].pos)
        self.assertIsNone(self.c.menu)

    def test_arrows_reach_every_section(self):
        self.press('UP')
        self.assertEqual(self.c.focus, 'bench')
        self.press('UP')
        self.assertEqual(self.c.focus, 'board')
        self.press('DOWN')
        self.assertEqual(self.c.focus, 'bench')
        self.press('DOWN', 'DOWN')
        self.assertEqual(self.c.focus, 'actions')
        self.press('UP')
        self.assertEqual(self.c.focus, 'shop')

    def test_menu_move_can_cancel_then_move_to_chosen_cell(self):
        self.press('ENTER', 'UP', 'ENTER', 'ENTER')
        unit = self.c.game.players[0].units[0]
        original = unit.pos
        self.press('ENTER', 'ENTER')
        self.assertEqual(self.c.held, unit.uid)
        self.press('LEFT', 'ESC')
        self.assertEqual(unit.pos, original)
        self.c.cursor = original
        self.press('ENTER', 'ENTER', 'LEFT', 'ENTER')
        self.assertNotEqual(unit.pos, original)
        self.assertIsNone(self.c.held)

    def test_refresh_level_and_lock_are_visible_buttons(self):
        self.press('DOWN', 'RIGHT', 'RIGHT', 'ENTER')
        self.assertEqual(self.c.game.players[0].gold, 8)
        self.press('RIGHT', 'ENTER')
        self.assertEqual(self.c.game.players[0].level, 3)
        self.press('RIGHT', 'ENTER')
        self.assertTrue(self.c.game.players[0].locked)

    def test_champion_sale_via_context_menu(self):
        self.press('ENTER', 'UP', 'ENTER', 'DOWN', 'DOWN', 'ENTER')
        self.assertFalse(self.c.game.players[0].units)
        self.assertEqual(self.c.game.players[0].gold, 10)

    def test_one_button_deploys_and_starts_battle_then_enter_advances(self):
        self.press('ENTER', 'DOWN', 'ENTER')
        self.assertIsNotNone(self.c.future)
        self.assertTrue(any(u.pos is not None for u in self.c.game.players[0].units))
        self.c.future.result(timeout=10)
        self.c.tick()
        self.assertEqual(self.c.game.phase, 'result')
        if self.c.animating:
            self.press('ENTER')
        self.press('ENTER')
        self.assertEqual(self.c.game.round, 2)
        self.assertEqual(self.c.focus, 'shop')

    def test_more_menu_hides_and_enter_restores(self):
        self.press('DOWN', *(['RIGHT'] * 5), 'ENTER', 'DOWN', 'DOWN', 'ENTER')
        self.assertTrue(self.c.hidden)
        self.press('ENTER')
        self.assertFalse(self.c.hidden)

    def test_save_exit_is_available_without_a_letter_key(self):
        self.press('ENTER', 'DOWN', *(['RIGHT'] * 5), 'ENTER', 'DOWN', 'DOWN', 'DOWN', 'ENTER')
        self.assertTrue(self.c.quit)
        self.assertTrue(Game.load(self.c.save_path).players[0].units)

    def test_unaffordable_shop_choice_keeps_roster_unchanged(self):
        self.c.game.players[0].gold = 0
        self.press('ENTER')
        self.assertFalse(self.c.game.players[0].units)
        self.assertIn('金币不足', self.c.message)

    def test_main_screen_explains_selection_instead_of_hotkey_list(self):
        text = '\n'.join(render_lines(self.c, 80, 24))
        for label in ('刷新', '升级', '自动上阵', '开始战斗', '更多', 'Enter'):
            self.assertIn(label, text)
        for obsolete in ('1–5', 'TAB 切换', 'D 刷新', 'SPACE', '#1'):
            self.assertNotIn(obsolete, text)

    def test_quit_creates_a_resumable_save(self):
        self.c.key('1')
        self.c.key('q')
        self.assertTrue(self.c.quit)
        self.assertEqual(Game.load(self.c.save_path).players, self.c.game.players)

    def test_plain_commands_for_buy_move_and_sale(self):
        plain_command(self.c, 'buy 1')
        unit = self.c.game.players[0].units[0]
        plain_command(self.c, f'move {unit.uid} 0')
        self.assertEqual(unit.pos, 0)
        plain_command(self.c, f'sell {unit.uid}')
        self.assertFalse(self.c.game.players[0].units)

    def test_plain_hidden_and_paused_modes_do_not_mutate_game(self):
        from autochess.engine import RuleError
        for flag in ('hidden', 'paused'):
            setattr(self.c, flag, True)
            before = self.c.game.players[0].gold
            plain_command(self.c, 'buy 1')
            self.assertEqual(self.c.game.players[0].gold, before)
            setattr(self.c, flag, False)

    def test_combat_marks_friendly_and_enemy_units(self):
        self.c.game.phase = 'result'
        self.c.frames = [{'tick':0,'events':[], 'units':[
            {'kind':'spark','star':1,'side':0,'x':0,'y':3,'hp':10,'max_hp':10,'mana':0},
            {'kind':'spark','star':1,'side':1,'x':1,'y':3,'hp':10,'max_hp':10,'mana':0}]}]
        text = '\n'.join(render_lines(self.c, 108, 38))
        self.assertIn('火花', text)
        self.assertIn('+1*', text)
        self.assertIn('-1*', text)

    def test_small_window_still_exposes_exit_in_menu(self):
        self.press('ESC')
        text = '\n'.join(render_lines(self.c, 40, 10))
        self.assertIn('保存退出', text)

    def test_popup_has_no_board_text_behind_its_choices(self):
        self.press('ENTER', 'UP', 'ENTER')
        for width, height in ((80, 24), (108, 38)):
            text = '\n'.join(render_lines(self.c, width, height))
            self.assertIn('出售', text)
            self.assertNotIn('NOVA', text)
            self.assertTrue(all(display_width(line) <= width for line in text.splitlines()))

    def test_small_window_renders_resize_message(self):
        text = '\n'.join(render_lines(self.c, 40, 10))
        self.assertIn('80', text)

    def test_completed_opponents_are_not_replanned_on_retry(self):
        from autochess.agents import LocalAgent, prepare_opponents
        import threading
        result = prepare_opponents(self.c.game, LocalAgent(), threading.Event())
        self.c.game = result.game
        self.c.game.ai_passes = {'1': 1}
        self.c.game.resolve_round()
        self.c.game.next_round()
        self.assertEqual(self.c.game.ai_passes, {})


if __name__ == '__main__':
    unittest.main()
