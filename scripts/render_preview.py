#!/usr/bin/env python3
"""Export an actual offline game layout as an SVG for the repository README."""

import html
from pathlib import Path
import re
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autochess.agents import LocalAgent, apply_plan, observe, prepare_opponents
from autochess.engine import Game
from autochess.sprites import atlas
from autochess.ui import Controller, display_width, render_lines


def main():
    game = Game(seed=6, mode='local')
    agent = LocalAgent()
    for _ in range(4):
        apply_plan(game, 0, agent.decide(observe(game, 0)))
        game = prepare_opponents(game, agent, threading.Event()).game
        game.resolve_round()
        game.next_round()
    with tempfile.TemporaryDirectory(prefix='autochess-preview-') as temporary:
        controller = Controller(game, Path(temporary) / 'demo.json')
        pixels = []
        lines = render_lines(controller, 108, 38, pixel_cells=pixels)
        controller.close()

    cell_w, cell_h = 12, 24
    left, top = 24, 64
    width, height = 108*cell_w+48, 38*cell_h+88
    palette = atlas()['palette']
    background = '#111821'
    pixel_positions = {(y, x) for y, x, *_ in pixels}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
           '<title id="title">Idle Arena — offline terminal preview</title>',
           '<desc id="desc">Actual 108 by 38 game layout rendered from an offline match at round five. Chinese interface with pixel monsters, formation, bench, shop and arrow-key controls.</desc>',
           f'<rect width="{width}" height="{height}" rx="12" fill="{background}"/>',
           f'<path d="M0 44H{width}" stroke="#2c3644"/>',
           '<g font-family="Menlo, Consolas, DejaVu Sans Mono, monospace" font-size="14" fill="#92a0af">',
           '<text x="24" y="28">Idle Arena / offline demo / 108 × 38</text></g>',
           '<g font-family="Menlo, Consolas, Noto Sans Mono CJK SC, PingFang SC, monospace" font-size="18">']

    def rect(x, y, w, h, color):
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>')

    for y, line in enumerate(lines):
        color = '#75d9e9' if y in (0, 1) else '#e6c66c' if y == 2 or '商店 ·' in line else '#88ce9b' if y == 37 else '#d4dce5'
        selections = []
        for match in re.finditer(r'\[[^\]]+\]', line):
            start = display_width(line[:match.start()])
            end = start+display_width(match.group())
            selections.append((start, end))
            rect(left+start*cell_w, top+y*cell_h, (end-start)*cell_w, cell_h, '#d4dce5')
        x = 0
        for char in line:
            size = display_width(char)
            if char != ' ' and (y, x) not in pixel_positions:
                fill = background if any(a <= x < b for a, b in selections) else color
                svg.append(f'<text x="{left+x*cell_w}" y="{top+y*cell_h+19}" fill="{fill}" textLength="{size*cell_w}" lengthAdjust="spacingAndGlyphs">{html.escape(char)}</text>')
            x += size

    for y, x, char, fg, bg in pixels:
        px, py = left+x*cell_w, top+y*cell_h
        rect(px, py, cell_w, cell_h, background)
        if char == '█':
            rect(px, py, cell_w, cell_h, palette[fg])
        elif char == '▄':
            rect(px, py+cell_h//2, cell_w, cell_h//2, palette[fg])
        else:
            rect(px, py, cell_w, cell_h//2, palette[fg])
            if bg is not None:
                rect(px, py+cell_h//2, cell_w, cell_h//2, palette[bg])
    svg.append('</g></svg>')
    destination = ROOT / 'assets' / 'terminal-preview.svg'
    destination.write_text('\n'.join(svg)+'\n', encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
