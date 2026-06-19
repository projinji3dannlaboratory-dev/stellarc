#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OGP画像 (1200x630) を生成する。SNSシェア時のカード画像 og-image.png を出力。"""
import random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

ROOT = Path(__file__).resolve().parent
W, H = 1200, 630

def load_font(size):
    for p in (r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
              r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\msgothic.ttc",
              r"C:\Windows\Fonts\YuGothM.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

def load_mono(size):
    for p in (r"C:\Windows\Fonts\consolab.ttf", r"C:\Windows\Fonts\consola.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return load_font(size)

img = Image.new("RGB", (W, H), (4, 6, 13))
base = ImageDraw.Draw(img)
random.seed(20260619)

# 背景の微星
for _ in range(190):
    x, y = random.randint(0, W), random.randint(0, H)
    r = random.choice([1, 1, 1, 2])
    c = random.choice([(126, 140, 160), (125, 211, 200), (170, 182, 205), (255, 220, 170)])
    base.ellipse([x - r, y - r, x + r, y + r], fill=c)

# 銀河の「太陽」たち（グロー層）：大きさ＝時価総額/色＝業種のイメージ
suns = [
    (210, 360, 60, (255, 180, 84)),
    (1000, 175, 46, (125, 211, 200)),
    (1080, 470, 30, (201, 167, 255)),
    (150, 150, 26, (109, 184, 255)),
    (640, 110, 20, (255, 180, 84)),
    (560, 540, 24, (255, 159, 190)),
]
glow = Image.new("RGB", (W, H), (0, 0, 0))
gd = ImageDraw.Draw(glow)
for x, y, r, c in suns:
    gd.ellipse([x - r, y - r, x + r, y + r], fill=c)
glow = glow.filter(ImageFilter.GaussianBlur(30))
img = ImageChops.add(img, glow)

# 鋭いコア
core = ImageDraw.Draw(img)
for x, y, r, c in suns:
    cr = max(5, r // 6)
    core.ellipse([x - cr, y - cr, x + cr, y + cr], fill=(255, 247, 230))

# テキスト可読性のため中央に暗いグラデ帯
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
od.rectangle([0, 215, W, 470], fill=(4, 6, 13, 150))
overlay = overlay.filter(ImageFilter.GaussianBlur(40))
img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

d = ImageDraw.Draw(img)
AMBER = (255, 180, 84)
TXT = (236, 240, 248)
DIM = (150, 165, 185)
TEAL = (125, 211, 200)

# 上部ラベル
lab = load_mono(30)
d.text((82, 86), "STELLARC", font=lab, fill=AMBER)
d.text((250, 90), "COMPANY DISCOVERY OBSERVATORY", font=load_mono(20), fill=DIM)

# メインタイトル
title = load_font(86)
d.text((80, 250), "ホワイト企業発見マップ", font=title, fill=TXT)

# タグライン
d.text((84, 372), "全上場企業を、宇宙の銀河に。", font=load_font(38), fill=AMBER)
d.text((84, 430), "★ 大きさ＝時価総額   /   輝き＝優良企業度（成長率・利益率・働きやすさ・年収）",
       font=load_font(27), fill=DIM)

# 下部：価値提案 + URL
d.text((84, 535), "知られざる優良企業（暗黒巨星）を見つける、転職・就活の企業発見マップ",
       font=load_font(26), fill=TEAL)
url = "kigyo-map.projinji3dann-laboratory.com"
uf = load_mono(24)
ub = d.textbbox((0, 0), url, font=uf)
d.text((W - (ub[2] - ub[0]) - 40, 575), url, font=uf, fill=DIM)

out = ROOT / "og-image.png"
img.save(out, "PNG", optimize=True)
print("wrote", out, img.size)
