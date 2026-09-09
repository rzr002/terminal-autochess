import unittest
from pathlib import Path
import tempfile
from autochess.engine import CATALOG, Game
from autochess.ui import Controller, render_lines, display_width
try:
    from autochess.sprites import atlas, sprite_pixels, halfblocks, TerminalPalette
except ImportError:
    atlas = None


class SpriteTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(atlas, '怪兽像素渲染尚未实现')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.save_path = Path(self.tmp.name) / 'game.json'

    def test_every_champion_has_a_distinct_portrait(self):
        data = atlas()
        self.assertEqual(set(data['sprites']), set(CATALOG))
        signatures = set()
        for kind in CATALOG:
            pixels = sprite_pixels(kind, 16)
            self.assertEqual(len(pixels), 16)
            self.assertTrue(all(len(row) == 16 for row in pixels))
            self.assertTrue(any(p is not None for row in pixels for p in row))
            self.assertTrue(any(p is None for row in pixels for p in row))
            signatures.add(str(pixels))
        self.assertEqual(len(signatures), 18)

    def test_halfblocks_preserve_every_pixel_in_portrait(self):
        for kind in CATALOG:
            pixels = sprite_pixels(kind, 16)
            cells = halfblocks(kind, 16)
            self.assertEqual(len(cells), 8)
            for y, row in enumerate(cells):
                for x, (char, fg, bg) in enumerate(row):
                    if char == ' ':
                        decoded = (None, None)
                    elif char == '█':
                        decoded = (fg, fg)
                    elif char == '▄':
                        decoded = (None, fg)
                    else:
                        decoded = (fg, bg)
                    self.assertEqual(decoded, (pixels[2*y][x], pixels[2*y+1][x]))

    def test_all_thumbnail_sizes_fit_their_cells(self):
        for size in (4, 6, 16):
            for kind in CATALOG:
                rows = halfblocks(kind, size)
                self.assertEqual((len(rows), len(rows[0])), (size//2, size))
                self.assertTrue(any(cell[1] is not None for row in rows for cell in row))

    def test_palette_respects_terminal_color_and_pair_limits(self):
        class FakeCurses:
            COLORS = 8
            COLOR_PAIRS = 10
            error = RuntimeError
            def __init__(self):
                self.calls = []
            def init_pair(self, pair, fg, bg):
                assert 0 <= pair < self.COLOR_PAIRS
                assert 0 <= fg < self.COLORS
                assert -1 <= bg < self.COLORS
                self.calls.append((pair, fg, bg))
            def color_pair(self, pair):
                return pair
        fake = FakeCurses()
        palette = TerminalPalette(fake, -1)
        for kind in CATALOG:
            for row in halfblocks(kind, 16):
                for char, fg, bg in row:
                    if fg is not None:
                        self.assertLess(palette.style(fg, bg), fake.COLOR_PAIRS)
        self.assertLessEqual(len(fake.calls), 5)

    def test_shop_and_large_board_draw_images_inside_terminal(self):
        c = Controller(Game(seed=6, mode='local'), self.save_path)
        c.key('ENTER'); c.key('UP'); c.key('ENTER'); c.key('ENTER')
        for width, height in ((80, 24), (108, 38)):
            cells = []
            lines = render_lines(c, width, height, pixel_cells=cells)
            self.assertTrue(cells)
            self.assertTrue(all(0 <= y < height and 0 <= x < width for y, x, *_ in cells))
            self.assertTrue(all(display_width(line) <= width for line in lines))
            if width > 100:
                self.assertTrue(any(y < 24 and x < 74 for y, x, *_ in cells))

    def test_hidden_and_help_pages_do_not_leak_sprite_overlays(self):
        c = Controller(Game(seed=6), self.save_path)
        for flag in ('hidden', 'help'):
            setattr(c, flag, True)
            cells = []
            render_lines(c, 108, 38, pixel_cells=cells)
            self.assertFalse(cells)
            setattr(c, flag, False)

    def test_unit_menu_shows_portrait_and_removes_shop_images(self):
        c = Controller(Game(seed=6, mode='local'), self.save_path)
        for key in ('ENTER', 'UP', 'ENTER'):
            c.key(key)
        cells = []
        lines = render_lines(c, 80, 24, pixel_cells=cells)
        self.assertTrue(cells)
        self.assertIn('出售', '\n'.join(lines))
        self.assertTrue(all(4 <= y < 20 for y, *_ in cells))
        self.assertLessEqual(max(x for _, x, *_ in cells)-min(x for _, x, *_ in cells), 15)


if __name__ == '__main__':
    unittest.main()
