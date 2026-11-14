import sys, numpy as np, potrace
from PIL import Image, ImageFilter
src, out = sys.argv[1], sys.argv[2]
S = 1200
im = Image.open(src).convert('RGB').resize((S, S), Image.LANCZOS)
a = np.asarray(im).astype(np.int32)
PAL = [  # name, rgb, svg fill
 ('wall',       (2, 10, 20),     '#020a14'),
 ('ground',     (149, 157, 114), '#959d72'),
 ('river',      (14, 120, 152),  '#0e7898'),
 ('baselight',  (126, 156, 156), '#7e9c9c'),
 ('basemid',    (104, 138, 140), '#688a8c'),
 ('basedark',   (80, 112, 118),  '#507076'),
 ('red',        (150, 88, 100),  '#965864'),
 ('blue',       (78, 108, 150),  '#4e6c96'),
]
cols = np.array([p[1] for p in PAL])
d = ((a[:, :, None, :] - cols[None, None, :, :]) ** 2).sum(-1)
lab = d.argmin(-1).astype(np.uint8)
yy, xx = np.mgrid[0:S, 0:S]
inbase = (np.hypot(xx, S - yy) < 0.47 * S) | (np.hypot(S - xx, yy) < 0.47 * S)
R_, G_, B_ = a[:, :, 0], a[:, :, 1], a[:, :, 2]
names = [p[0] for p in PAL]; I = {n: i for i, n in enumerate(names)}
basecls = np.isin(lab, [I['baselight'], I['basemid'], I['basedark'], I['red'], I['blue']])
rivery = (R_ < 140) & (B_ > 116) & (R_ + G_ + B_ > 150)
fix = basecls & ~inbase
lab = lab.copy()
lab[fix & rivery] = I['river']
lab[fix & ~rivery & (R_ + G_ + B_ > 250)] = I['ground']
lab[fix & ~rivery & (R_ + G_ + B_ <= 250)] = I['wall']
lab[~inbase & (lab == I['ground']) & rivery] = I['river']
lab = np.asarray(Image.fromarray(lab).filter(ImageFilter.ModeFilter(7)))

riv = (lab == I['river'])
alpha = np.clip((149 - R_) / (149 - 14), 0, 1)
t = ((xx + yy) / (2 * S))
bins = 60; stops = []
for k in range(bins):
    m = riv & (t >= k / bins) & (t < (k + 1) / bins)
    stops.append(float(alpha[m].mean()) if m.sum() > 30 else None)

def path_d(mask):
    bm = potrace.Bitmap(~mask)
    pl = bm.trace(turdsize=30, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY, alphamax=1.1, opticurve=True, opttolerance=0.3)
    parts = []
    for c in pl:
        sp = c.start_point; s = f'M{sp.x:.1f},{sp.y:.1f}'
        for seg in c:
            if seg.is_corner: s += f'L{seg.c.x:.1f},{seg.c.y:.1f}L{seg.end_point.x:.1f},{seg.end_point.y:.1f}'
            else: s += f'C{seg.c1.x:.1f},{seg.c1.y:.1f} {seg.c2.x:.1f},{seg.c2.y:.1f} {seg.end_point.x:.1f},{seg.end_point.y:.1f}'
        parts.append(s + 'Z')
    return ''.join(parts)

u, v = xx.astype(float), yy.astype(float)   # image coords, v down; blue base bottom-left
blueQ = np.hypot(u, S - v) < 0.47 * S
redQ = np.hypot(S - u, v) < 0.47 * S
baseB = np.hypot(u, S - v) < 0.315 * S
baseR = np.hypot(S - u, v) < 0.315 * S
ground = (lab == I['ground']) | riv
walk = ground & ~baseB & ~baseR
h_, r_ = 0.5 * S - 0.12 * S, 0.15 * S
qx, qy = np.abs(u - S / 2) - (h_ - r_), np.abs(v - S / 2) - (h_ - r_)
sdf = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r_
ring = sdf > 0
dTop, dBot = np.minimum(u, v), np.minimum(S - u, S - v)
midlane = np.abs(u + v - S) / np.sqrt(2) < 0.046 * S
Z = {}
Z['toplane'] = walk & ring & (dTop < dBot)
Z['botlane'] = walk & ring & (dTop >= dBot)
Z['midlane'] = walk & ~ring & midlane
rest = walk & ~ring & ~midlane
rivgrow = np.asarray(Image.fromarray((riv * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(45))) > 0
mouth = rest & ~riv & rivgrow & (sdf > -0.065 * S)
riv = riv | mouth
Z['topriver'] = rest & riv & (u + v < S)
Z['botriver'] = rest & riv & (u + v >= S)
jung = rest & ~riv
Z['bluejungle'] = jung & (v > u)
Z['redjungle'] = jung & (v <= u)
# base pieces, split by corner
for nm in ['baselight', 'basemid', 'basedark']:
    Z['blue_' + nm] = (lab == I[nm]) & blueQ
    Z['red_' + nm] = (lab == I[nm]) & redQ
# ground inside the base quadrants (base paths/edges) counts as base-light
nearB = np.hypot(u, S - v) < 0.43 * S
nearR = np.hypot(S - u, v) < 0.43 * S
Z['basepath'] = walk & (nearB | nearR) & ~ring & ~midlane
for k in ['topriver','botriver','bluejungle','redjungle']: Z[k] = Z[k] & ~Z['basepath']
Z['blue_baseground'] = ground & baseB
Z['red_baseground'] = ground & baseR
Z['bluecircle'] = (lab == I['blue'])
Z['redcircle'] = (lab == I['red'])
paths = {k: path_d(m) for k, m in Z.items() if m.sum() > 150}
for k, m in Z.items(): print(k, int(m.sum()), file=sys.stderr)

WALL = '#0c111b'
BASE = {'blue_baselight': '#4b78b8', 'blue_basemid': '#355f9c', 'blue_basedark': '#244676', 'blue_baseground': '#4b78b8',
        'red_baselight': '#a9506a', 'red_basemid': '#8a3a50', 'red_basedark': '#62263a', 'red_baseground': '#a9506a',
        'bluecircle': '#3b82f6', 'redcircle': '#ef4444'}
def svg(fills, river_on_top=True, river_col='#1f6f9c'):
    gs = ''.join(f'<stop offset="{(k + .5) / bins:.3f}" stop-color="{river_col}" stop-opacity="{min(1, v_ * 1.08):.2f}"/>' for k, v_ in enumerate(stops) if v_ is not None)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}"><defs><linearGradient id="rv" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{S}" y2="{S}">{gs}</linearGradient></defs><rect width="{S}" height="{S}" fill="{WALL}"/>']
    for k, d_ in paths.items():
        f = fills.get(k)
        if not f: continue
        out.append(f'<path id="{k}" d="{d_}" fill="{f}" fill-rule="evenodd" stroke="{f}" stroke-width="1.2"/>')
    if river_on_top:
        out.append(f'<path id="river" d="{rpath}" fill="url(#rv)" fill-rule="evenodd"/>')
    out.append('</svg>')
    return ''.join(out)
rpath = path_d(riv & ~baseB & ~baseR)
THEME = '#2b3550'
LANESLATE = {k: THEME for k in ['toplane', 'botlane', 'midlane', 'basepath']}
themed = dict(LANESLATE); themed.update({k: THEME for k in ['topriver', 'botriver', 'bluejungle', 'redjungle']}); themed.update(BASE)
open('rift-themed.svg', 'w').write(svg(themed))
for side in ['blue', 'red']:
    f = dict(LANESLATE); f.update(BASE); f.update({'topriver': '#3fbfae', 'botriver': '#1f97b0'})
    own, enemy = ('bluejungle', 'redjungle') if side == 'blue' else ('redjungle', 'bluejungle')
    f[own] = '#3fae6a'; f[enemy] = '#1d6b3f'
    open(f'rift-jr-{side}.svg', 'w').write(svg(f, river_on_top=False))
NEW = {'toplane': THEME, 'midlane': THEME, 'botlane': THEME, 'topriver': '#1fa5b3', 'botriver': '#1fa5b3', 'bluejungle': '#2f9a5d', 'redjungle': '#2f9a5d', 'basepath': THEME}
NEW.update(BASE)
open('rift-zones-new.svg', 'w').write(svg(NEW, river_on_top=False))
print('ok', file=sys.stderr)
