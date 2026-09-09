"""Original monster sprites, rendered with Unicode half blocks on normal terminals."""
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def atlas():
    return json.loads((Path(__file__).resolve().parents[1] / 'assets' / 'sprites.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=128)
def sprite_pixels(kind, size=16):
    source = atlas()['sprites'][kind]
    if size not in (4, 6, 16):
        raise ValueError('Sprite size must be 4, 6 or 16')
    if size == 16:
        return tuple(tuple(row) for row in source)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            values = [source[sy][sx] for sy in range(round(y*16/size), round((y+1)*16/size))
                      for sx in range(round(x*16/size), round((x+1)*16/size))]
            visible = [value for value in values if value is not None]
            row.append(Counter(visible).most_common(1)[0][0] if len(visible) >= len(values)*.25 else None)
        rows.append(tuple(row))
    return tuple(rows)


@lru_cache(maxsize=128)
def halfblocks(kind, size=16):
    pixels = sprite_pixels(kind, size)
    rows = []
    for y in range(0, size, 2):
        row = []
        for top, bottom in zip(pixels[y], pixels[y+1]):
            if top is None and bottom is None:
                row.append((' ', None, None))
            elif top == bottom:
                row.append(('█', top, None))
            elif top is None:
                row.append(('▄', bottom, None))
            else:
                row.append(('▀', top, bottom))
        rows.append(tuple(row))
    return tuple(rows)


class TerminalPalette:
    """Allocate color pairs once, within the terminal's advertised capabilities."""
    def __init__(self, curses, background=-1):
        self.curses, self.background = curses, background
        self.pairs = {}
        self.colors = self._colors(max(0, getattr(curses, 'COLORS', 0)))
        self.limit = getattr(curses, 'COLOR_PAIRS', 0)
        self.rgb = [tuple(bytes.fromhex(color[1:])) for color in atlas()['palette']]
        self.indices = [min(range(len(self.colors)), key=lambda i: sum((rgb[j]-self.colors[i][j])**2 for j in range(3)))
                        if self.colors else 0 for rgb in self.rgb]

    @staticmethod
    def _colors(count):
        basic = [(0,0,0), (170,0,0), (0,170,0), (170,85,0), (0,0,170), (170,0,170), (0,170,170), (170,170,170),
                 (85,85,85), (255,85,85), (85,255,85), (255,255,85), (85,85,255), (255,85,255), (85,255,255), (255,255,255)]
        cube = [(r,g,b) for r in (0,95,135,175,215,255) for g in (0,95,135,175,215,255) for b in (0,95,135,175,215,255)]
        return (basic + cube + [(8+i*10,)*3 for i in range(24)])[:count]

    def style(self, foreground, background=None):
        if not self.colors or self.limit <= 5:
            return 0
        fg = self.indices[foreground]
        bg = self.background if background is None else self.indices[background]
        key = (fg, bg)
        if key not in self.pairs:
            index = 5+len(self.pairs)
            if index >= self.limit:
                # Reuse the nearest available pair rather than redefine a live color.
                key = min(self.pairs, key=lambda old: sum((self.colors[old[0]][i]-self.colors[fg][i])**2 for i in range(3)) +
                          (0 if old[1] == bg else 10000))
            else:
                try:
                    self.curses.init_pair(index, fg, bg)
                except self.curses.error:
                    return 0
                self.pairs[key] = index
        return self.curses.color_pair(self.pairs[key])
