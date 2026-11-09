#!/usr/bin/env python3
"""生成符合 macOS 规范的 OptSnap 图标。

macOS 应用图标规范（从系统自带图标实测得到）：
- 画布是正方形，图形四周留白约 9.8%
- 主体是圆角矩形，圆角半径约等于边长的 22.4%（macOS Big Sur 之后的 squircle 近似）
- 圆角矩形外完全透明
- 带轻微渐变和细节，避免纯平色

沿用原图标的粉 → 蓝配色，主体画成「窗口叠放 + 顶部图钉」，直观点出置顶功能。
"""

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

# 原始配色（取自旧图标）
PINK = (244, 101, 129)
BLUE = (3, 112, 255)

# 系统图标的实测比例
PADDING_RATIO = 0.098        # 四周留白占画布的 9.8%
CORNER_RATIO = 0.224         # 圆角半径占主体边长的 22.4%


def lerp(a, b, t):
    return int(round(a + (b - a) * t))


def make_gradient(size, top, bottom):
    """竖向线性渐变。加一点自下而上的提亮，避免纯线性看着发闷。"""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        # 用缓动让上半部分过渡更快，视觉上更像系统图标的柔和渐变
        te = t ** 0.85
        for x in range(size):
            # 轻微的水平变化，模拟光照
            hx = (x / max(1, size - 1) - 0.5) * 0.06
            r = lerp(top[0], bottom[0], te) + int(hx * 40)
            g = lerp(top[1], bottom[1], te) + int(hx * 30)
            b = lerp(top[2], bottom[2], te) + int(hx * 40)
            px[x, y] = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    return img


def rounded_mask(size, radius):
    """生成圆角矩形遮罩（4x 超采样后缩小，得到平滑边缘）。"""
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle(
        [0, 0, size * scale - 1, size * scale - 1],
        radius=radius * scale,
        fill=255,
    )
    return big.resize((size, size), Image.LANCZOS)


def draw_content(size):
    """绘制图标主体内容：三层窗口叠放，最上层用实心白边突出「已置顶」。

    要点是缩到 16px 也要认得出是「窗口叠放」：
    - 每层只画粗边框 + 很淡的填充，靠边框区分层次，避免整块糊成一片
    - 三层错位要明显（对角错开），否则看起来像一个窗口
    - 最上层边框最亮、填充最实，视觉焦点落在它身上
    """
    scale = 4
    S = size * scale
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    win_w = S * 0.50
    win_h = S * 0.36
    radius = S * 0.05
    stroke = max(3, int(S * 0.020))
    cx, cy = S / 2, S / 2

    # 从最后层画到最前层。dx/dy 是相对中心的对角错位。
    # fill_alpha 递增、outline_alpha 递增，形成纵深。
    layers = [
        (-S * 0.105, -S * 0.085, 30, 110),
        (-S * 0.052, -S * 0.043, 45, 160),
        (0.0, 0.0, 70, 255),
    ]

    for dx, dy, fill_a, line_a in layers:
        x0 = cx - win_w / 2 + dx
        y0 = cy - win_h / 2 + dy
        x1 = x0 + win_w
        y1 = y0 + win_h

        d.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=radius,
            fill=(255, 255, 255, fill_a),
            outline=(255, 255, 255, line_a),
            width=stroke,
        )

        # 标题栏分隔线：靠它一眼看出这是「窗口」而不是普通圆角块
        bar_y = y0 + win_h * 0.26
        d.line(
            [x0 + stroke, bar_y, x1 - stroke, bar_y],
            fill=(255, 255, 255, int(line_a * 0.6)),
            width=max(2, stroke // 2),
        )

    return layer.resize((size, size), Image.LANCZOS)


def build_icon(canvas):
    """生成 canvas×canvas 的完整图标。"""
    pad = int(round(canvas * PADDING_RATIO))
    body = canvas - pad * 2
    radius = int(round(body * CORNER_RATIO))

    # 主体渐变：上粉下蓝
    grad = make_gradient(body, PINK, BLUE)

    # 顶部加一层柔和高光，让主体有体积感
    glow = Image.new("L", (body, body), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [-body * 0.25, -body * 0.55, body * 1.25, body * 0.42],
        fill=70,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(body * 0.08))
    white = Image.new("RGB", (body, body), (255, 255, 255))
    grad = Image.composite(white, grad, glow.point(lambda v: int(v * 0.45)))

    # 套圆角遮罩
    mask = rounded_mask(body, radius)
    body_img = Image.new("RGBA", (body, body), (0, 0, 0, 0))
    body_img.paste(grad, (0, 0), mask)

    # 叠内容
    content = draw_content(body)
    body_img = Image.alpha_composite(body_img, content)

    # 放回画布中央
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(body_img, (pad, pad), body_img)
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "icon.iconset"
    os.makedirs(out_dir, exist_ok=True)

    # Apple 要求的全套尺寸
    specs = [
        (16, 1), (16, 2), (32, 1), (32, 2),
        (128, 1), (128, 2), (256, 1), (256, 2),
        (512, 1), (512, 2),
    ]

    # 用 1024 渲染再缩，保证小尺寸也清晰
    master = build_icon(1024)

    for pt, scale in specs:
        px = pt * scale
        img = master.resize((px, px), Image.LANCZOS)
        name = f"icon_{pt}x{pt}{'@2x' if scale == 2 else ''}.png"
        img.save(os.path.join(out_dir, name))
        print(f"  {name}  {px}x{px}")

    master.save(os.path.join(out_dir, "icon_512x512@2x.png"))
    print(f"已生成 {len(specs)} 个尺寸 → {out_dir}")


if __name__ == "__main__":
    main()
