#!/usr/bin/env python3
"""生成菜单栏图标（template image）。

菜单栏图标和 app 图标的规范完全不同，不要混用：
- app 图标：1024 画布、圆角矩形主体、彩色、四周留白 9.8%
- 菜单栏图标：22pt 逻辑尺寸（@2x 出 44px），**纯黑 + 透明背景**的模板图

模板图的规则是「只有 alpha 有意义，颜色由系统决定」：系统会按当前是深色还是浅色
菜单栏自动把它反相成白色或黑色。所以必须用纯黑前景 + 全透明背景，任何彩色或
不透明的方块都会导致它在菜单栏里显示成一坨方块。

图形用「三层错开的窗口」，和 app 图标的内容对应，缩小到 22px 仍能看出是叠放窗口。
"""

import os
import sys

from PIL import Image, ImageDraw

# 菜单栏图标覆盖的漂亮尺寸（pt, scale）
SPECS = [(22, 1), (22, 2), (22, 3)]


def draw_glyph(px):
    """在 px×px 画布上画菜单栏图形。

    菜单栏只有 22pt，三层叠放的窗口在这个尺寸下会糊成一团（实测 stroke 挤在一起
    分不出层次）。改成「单窗口 + 向上箭头」：形状简单，22px 下依然清晰，
    而且"窗口往上顶"直接对应置顶语义。
    """
    scale = 8
    S = px * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    content = S * 0.74
    cx, cy = S / 2, S / 2

    # ── 窗口主体（略偏下，给上方箭头留位置）──
    win_w = content * 0.92
    win_h = content * 0.60
    radius = content * 0.10
    stroke = max(2, int(S * 0.048))
    x0 = cx - win_w / 2
    y0 = cy - win_h / 2 + content * 0.11
    x1 = x0 + win_w
    y1 = y0 + win_h

    d.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=radius,
        outline=(0, 0, 0, 255),
        width=stroke,
    )
    # 标题栏分隔线
    bar_y = y0 + win_h * 0.28
    d.line([x0 + stroke, bar_y, x1 - stroke, bar_y],
           fill=(0, 0, 0, 255), width=max(2, stroke // 2))

    # ── 向上箭头（在窗口上方，表示"置顶"）──
    ax = cx
    arrow_top = y0 - content * 0.30
    arrow_bottom = y0 - content * 0.02
    wing = content * 0.14
    arm = max(2, int(S * 0.048))
    # 竖杆
    d.line([ax, arrow_top, ax, arrow_bottom], fill=(0, 0, 0, 255), width=arm)
    # 箭头两翼
    d.line([ax, arrow_top, ax - wing, arrow_top + wing], fill=(0, 0, 0, 255), width=arm)
    d.line([ax, arrow_top, ax + wing, arrow_top + wing], fill=(0, 0, 0, 255), width=arm)

    return img.resize((px, px), Image.LANCZOS)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)

    # 22pt 用 @1x/@2x/@3x 三档
    for pt, scale in SPECS:
        px = pt * scale
        img = draw_glyph(px)
        suffix = "" if scale == 1 else f"@{scale}x"
        name = f"menubar_icon{suffix}.png"
        img.save(os.path.join(out_dir, name))
        print(f"  {name}  {px}x{px}")

    print(f"已生成 {len(SPECS)} 个尺寸 → {out_dir}")


if __name__ == "__main__":
    main()
