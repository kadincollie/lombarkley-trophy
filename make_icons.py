"""Generate the app icon set: a 'league office seal' — football under a small
crown, gold ring, stadium-night base. Renders 512/192 (maskable) + 180 (apple)."""
from PIL import Image, ImageDraw, ImageFont
import os, math

BASE   = (14, 24, 22)     # #0E1816 stadium charcoal-green
RING   = (245, 184, 65)   # #F5B841 sodium gold
CHALK  = (242, 244, 239)  # #F2F4EF
LACE   = (14, 24, 22)
TURF   = (61, 220, 132)   # #3DDC84

def draw_icon(size, maskable=True):
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(S * (0.04 if maskable else 0.0))
    # rounded-square background (maskable safe zone)
    r = int(S * 0.22)
    d.rounded_rectangle([0, 0, S-1, S-1], radius=r, fill=BASE)

    cx, cy = S/2, S/2 + S*0.02
    # gold seal ring
    ring_r = S*0.36
    d.ellipse([cx-ring_r, cy-ring_r, cx+ring_r, cy+ring_r], outline=RING,
              width=max(3, int(S*0.018)))
    inner_r = ring_r - S*0.03
    d.ellipse([cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r], outline=RING,
              width=max(1, int(S*0.006)))

    # football (ellipse) centered
    fw, fh = S*0.40, S*0.245
    fx0, fy0, fx1, fy1 = cx-fw/2, cy-fh/2, cx+fw/2, cy+fh/2
    d.ellipse([fx0, fy0, fx1, fy1], fill=CHALK)
    # laces
    lx = cx
    d.line([lx, cy-fh*0.28, lx, cy+fh*0.28], fill=LACE, width=max(3, int(S*0.016)))
    for i in range(-2, 3):
        yy = cy + i*(fh*0.14)
        d.line([lx-fw*0.06, yy, lx+fw*0.06, yy], fill=LACE, width=max(2, int(S*0.011)))
    # football end-seams
    d.arc([fx0+2, fy0, fx0+fw*0.5, fy1], 60, 300, fill=LACE, width=max(2,int(S*0.010)))
    d.arc([fx1-fw*0.5, fy0, fx1-2, fy1], 240, 120, fill=LACE, width=max(2,int(S*0.010)))

    # small crown above football (the 'regime')
    crown_w = S*0.20
    crown_h = S*0.10
    cyc = cy - fh*0.5 - crown_h*0.75
    left = cx - crown_w/2
    pts = [
        (left, cyc+crown_h),
        (left, cyc+crown_h*0.35),
        (left+crown_w*0.18, cyc+crown_h*0.62),
        (left+crown_w*0.33, cyc),
        (left+crown_w*0.5,  cyc+crown_h*0.55),
        (left+crown_w*0.67, cyc),
        (left+crown_w*0.82, cyc+crown_h*0.62),
        (left+crown_w, cyc+crown_h*0.35),
        (left+crown_w, cyc+crown_h),
    ]
    d.polygon(pts, fill=RING)

    # tiny turf tick at the bottom of the seal
    d.ellipse([cx-S*0.012, cy+ring_r-S*0.012, cx+S*0.012, cy+ring_r+S*0.012], fill=TURF)
    return img

here = os.path.dirname(__file__)
icons_dir = os.path.abspath(os.path.join(here, "..", "icons"))
os.makedirs(icons_dir, exist_ok=True)

master = draw_icon(512, maskable=True)
master.save(os.path.join(icons_dir, "icon-512.png"))
master.resize((192,192), Image.LANCZOS).save(os.path.join(icons_dir, "icon-192.png"))
# apple touch icon has no transparency + no rounded mask (iOS rounds it)
apple = draw_icon(180, maskable=False).convert("RGB")
apple.save(os.path.join(icons_dir, "apple-touch-icon.png"))
# favicon
draw_icon(64, maskable=True).save(os.path.join(icons_dir, "favicon.png"))
draw_icon(1024, maskable=True).save(os.path.join(icons_dir, "icon-1024.png"))
print("Icons written to", icons_dir)
for f in sorted(os.listdir(icons_dir)):
    print(" ", f)
