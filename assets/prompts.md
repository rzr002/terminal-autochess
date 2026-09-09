# 像素怪兽生成提示词

使用内置 imagegen 工具。先生成统一图集，再用同一工具简化形象。实际使用的是第二次输出，原样复制为 `monsters.png`。

## 初次生成

Use case: stylized-concept.
Asset type: production sprite atlas for a minimalist terminal auto-battler.
Create ONE clean sprite sheet containing EXACTLY 18 distinct original tiny pixel-art monsters in an EXACT regular 6-column by 3-row grid. Landscape 1536x1024 canvas. Every one of the 18 cells is the same size (256x341.33). Center one full-body monster per cell with a very generous uniform empty margin; each monster occupies about 55% of its cell width and 45% of its height. Transparent background with genuine alpha. No background checkerboard baked into pixels.
EXTREMELY SIMPLE, chunky, cute 16x16-pixel creature designs enlarged with nearest-neighbor square pixels, about 4-6 flat colors each, two readable eye pixels. Clear silhouettes, no outlines thinner than a pixel. NO gradients, NO shading detail, NO smooth curves, NO anti-aliasing, NO scene, NO shadows, NO borders, NO grids, NO text, NO labels. All monsters fully visible and disjoint within their own cell; same pixel size across the sheet. Shape variety is essential, not eighteen reskins of the same blob.
Exact order, left to right:
ROW 1: neon/mechanical monsters.
1 compact orange flame-shaped robot with cyan stubby arms and two eyes, tank;
2 cyan electric cat with long ears and a yellow lightning tail, ranger;
3 magenta small square ghost with a cyan antenna and two eyes, mage;
4 wide steel-blue armored crab robot with an orange face visor, tank;
5 coral-red mechanical bird with long cyan wings, ranger;
6 purple floating one-eyed cube with two pink spark arms, mage.
ROW 2: woodland monsters.
1 tiny brown walking tree stump with a bright green sprout and eyes, tank;
2 mint-green leaf-winged tiny owl, ranger;
3 short moss-green mushroom wizard with a large amber cap and tiny feet, mage;
4 squat gray rock bear with green moss on its shoulders, tank;
5 lime-green little fox with pointed ears and a long bushy dark-green tail, ranger;
6 little dark-green horned tree spirit with warm yellow eyes and leaf arms, mage.
ROW 3: astral monsters.
1 lilac-white tiny round star wizard wearing a four-point star crown, mage;
2 pale-yellow comet fox with a long lavender comet tail, ranger;
3 lavender crescent-shell turtle with short navy feet, tank;
4 indigo-purple floating cosmic jellyfish with two yellow eyes and three short tentacles, mage;
5 blocky blue celestial golem with a gold diamond on its chest, tank;
6 small cyan-and-gold star moth with two angular large wings, ranger.
Use generous negative space. Make this an actual usable pixel sprite atlas, no mockup UI and no typography.

## 最终简化编辑

Edit the referenced 18-monster sprite atlas. Keep EXACTLY these 18 monsters, the same identity cues, and the same 6-column by 3-row ordering. Radically simplify ALL monsters into true extremely minimal 16x16 pixel sprites, then enlarge with nearest neighbor to 1536x1024. Each monster must use no more than FIVE flat colors including black/dark eyes. Solid square pixel clusters, VERY FEW blocks, like early 8-bit handheld game sprites. Remove every gradient, glow, halo, soft shadow, particle, shading texture and anti-aliasing. Make each cell exactly 256px wide and 1024/3px tall. Place each monster within a centered 160x160px square in its cell, with a large clear margin, no part outside its cell. Each sprite reads as a few simple geometric blocks and two eyes. Use one perfectly flat solid background color #10141C across the ENTIRE canvas including gaps between the monsters; do not use transparency or checkerboards. This exact background is necessary for game extraction. No text, borders, grids, badges or extra objects. Flat sprite atlas only. Preserve each monster's recognizable silhouette, with fewer and larger pixels. The required result is much simpler than the input; no ambient light anywhere.
