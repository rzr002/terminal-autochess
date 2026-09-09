#!/usr/bin/env python3
"""Read the generated atlas into terminal pixel data; never modify the source PNG.

Development tool only (Pillow). Runtime consumes the bundled JSON with stdlib.
"""
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autochess.engine import CATALOG

PALETTE = ['#10131c', '#fff4cf', '#c6edff', '#ffe11a', '#ff930d', '#ff5123',
           '#ed2688', '#b146f5', '#652aba', '#3579ef', '#05cde5', '#0089c9',
           '#123951', '#72a0bb', '#7b8185', '#af6037', '#683b26', '#0b643e',
           '#22b957', '#80da24', '#d8e5ba', '#ceb3ff']
RGB = [tuple(bytes.fromhex(color[1:])) for color in PALETTE]


def nearest(color):
    return min(range(len(RGB)), key=lambda i: sum((color[j]-RGB[i][j])**2 for j in range(3)))


def main():
    source = ROOT / 'assets' / 'monsters.png'
    image = Image.open(source).convert('RGBA')
    width, height = image.size
    sprites = {}
    for index, kind in enumerate(CATALOG):
        row, col = divmod(index, 6)
        left, right = max(0, round(col*width/6)-6), min(width, round((col+1)*width/6)+6)
        top, bottom = round(row*height/3), round((row+1)*height/3)
        w, h = right-left, bottom-top
        pixels = [[image.getpixel((left+x, top+y)) for x in range(w)] for y in range(h)]
        def background(x, y):
            pixel = pixels[y][x]
            return pixel[3] < 128 or max(pixel[:3]) < 38 or all(abs(pixel[i]-[16, 20, 28][i]) < 36 for i in range(3))
        # Flood only background connected to the cell boundary, preserving dark eyes.
        outside = set()
        queue = deque([(x, 0) for x in range(w)] + [(x, h-1) for x in range(w)] +
                      [(0, y) for y in range(h)] + [(w-1, y) for y in range(h)])
        while queue:
            x, y = queue.popleft()
            if (x, y) in outside or not (0 <= x < w and 0 <= y < h) or not background(x, y):
                continue
            outside.add((x, y))
            queue.extend([(x-1,y), (x+1,y), (x,y-1), (x,y+1)])
        inside = [(x, y) for y in range(h) for x in range(w) if (x, y) not in outside]
        if not inside:
            raise ValueError(f'{kind}: empty sprite')
        x0, x1 = min(x for x,y in inside), max(x for x,y in inside)+1
        y0, y1 = min(y for x,y in inside), max(y for x,y in inside)+1
        side = max(x1-x0, y1-y0)*1.10
        origin_x, origin_y = (x0+x1-side)/2, (y0+y1-side)/2
        rows = []
        for py in range(16):
            line = []
            for px in range(16):
                xs = range(round(origin_x+px*side/16), round(origin_x+(px+1)*side/16))
                ys = range(round(origin_y+py*side/16), round(origin_y+(py+1)*side/16))
                colors = [pixels[y][x][:3] for y in ys for x in xs
                          if 0 <= x < w and 0 <= y < h and (x, y) not in outside]
                if len(colors) < max(1, len(xs)*len(ys)*.22):
                    line.append(None)
                else:
                    # Map the representative source pixel to a small shared palette.
                    typical = tuple(sorted(c[i] for c in colors)[len(colors)//2] for i in range(3))
                    line.append(nearest(typical))
            rows.append(line)
        sprites[kind] = rows
    result = {'version': 1, 'size': 16, 'source': 'monsters.png',
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'palette': PALETTE, 'sprites': sprites}
    (ROOT / 'assets' / 'sprites.json').write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(f'Extracted {len(sprites)} distinct 16×16 portraits from {source.name}')


if __name__ == '__main__':
    main()
