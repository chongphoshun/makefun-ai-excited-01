# main.py — "LIFTOFF": a rocket launches from a neon city at golden hour.
#
# Procedurally renders one 1024x1024 PNG to $MAKEFUN_OUTPUT_DIR/entry.png
# (default /output). Python 3.13 standard library only: zlib + struct write
# the PNG by hand. Fully deterministic: every random choice comes from a
# fixed seed, no timestamps, no dict-order dependence. Two runs produce
# identical bytes.
import math
import os
import random
import struct
import zlib

W = H = 1024


def clamp255(v):
    return 0 if v < 0 else (255 if v > 255 else v)


def lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


# ---------------- deterministic value noise ----------------
def _hash(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 974634211) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 4294967295.0


def make_noise(size, cells, seed):
    """Value-noise field size x size over a grid of `cells` cells, values 0..1."""
    g = [0.0] * ((cells + 1) * (cells + 1))
    for j in range(cells + 1):
        for i in range(cells + 1):
            g[j * (cells + 1) + i] = _hash(i, j, seed)
    out = [0.0] * (size * size)
    step = size / cells
    for y in range(size):
        gy = y / step
        j0 = int(gy)
        if j0 >= cells:
            j0 = cells - 1
        fy = gy - j0
        fy = fy * fy * (3 - 2 * fy)
        r0 = j0 * (cells + 1)
        r1 = (j0 + 1) * (cells + 1)
        for x in range(size):
            gx = x / step
            i0 = int(gx)
            if i0 >= cells:
                i0 = cells - 1
            fx = gx - i0
            fx = fx * fx * (3 - 2 * fx)
            a = g[r0 + i0]
            b = g[r0 + i0 + 1]
            c = g[r1 + i0]
            d = g[r1 + i0 + 1]
            out[y * size + x] = (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy
    return out


def fbm(size, seed):
    n1 = make_noise(size, 6, seed)
    n2 = make_noise(size, 12, seed + 7)
    n3 = make_noise(size, 24, seed + 13)
    return [0.55 * a + 0.3 * b + 0.15 * c for a, b, c in zip(n1, n2, n3)]


# ---------------- image ----------------
class Img:
    def __init__(self):
        self.p = bytearray(W * H * 3)

    def blend_px(self, x, y, r, g, b, a):
        """Alpha-blend one pixel. a in 0..255."""
        if a <= 0 or x < 0 or x >= W or y < 0 or y >= H:
            return
        o = (y * W + x) * 3
        p = self.p
        ia = 255 - a
        p[o] = (r * a + p[o] * ia) // 255
        p[o + 1] = (g * a + p[o + 1] * ia) // 255
        p[o + 2] = (b * a + p[o + 2] * ia) // 255

    def span(self, y, x0f, x1f, rgb, alpha=255):
        """Horizontal run with fractional-edge anti-aliasing."""
        if y < 0 or y >= H or x1f <= 0 or x0f >= W:
            return
        r, g, b = rgb
        if x0f < 0:
            x0f = 0.0
        if x1f > W:
            x1f = float(W)
        xi0 = int(math.ceil(x0f))
        xi1 = int(math.floor(x1f))
        row = y * W * 3
        if alpha >= 255:
            if xi1 > xi0:
                n = xi1 - xi0
                self.p[row + xi0 * 3: row + xi1 * 3] = bytes((r, g, b)) * n
            if xi0 > 0 and xi0 < W and x0f < xi0:
                self.blend_px(xi0 - 1, y, r, g, b, int((xi0 - x0f) * 255))
            if xi1 >= 0 and xi1 < W and x1f > xi1:
                self.blend_px(xi1, y, r, g, b, int((x1f - xi1) * 255))
        else:
            xs = max(0, int(math.floor(x0f)))
            xe = min(W, int(math.ceil(x1f)) + 1)
            for x in range(xs, xe):
                cov = 1.0
                if x + 1 <= x0f:
                    cov = 0.0
                elif x < x0f:
                    cov = x + 1 - x0f
                if x >= x1f:
                    cov = 0.0
                elif x + 1 > x1f:
                    cov = min(cov, x1f - x)
                if cov > 0:
                    self.blend_px(x, y, r, g, b, int(alpha * cov))

    def ellipse(self, cx, cy, rx, ry, rgb, alpha=255, ylo=None, yhi=None):
        y0 = max(0, int(math.floor(cy - ry)))
        y1 = min(H - 1, int(math.ceil(cy + ry)))
        if ylo is not None:
            y0 = max(y0, ylo)
        if yhi is not None:
            y1 = min(y1, yhi)
        for y in range(y0, y1 + 1):
            t = (y - cy) / ry
            if t < -1 or t > 1:
                continue
            dx = rx * math.sqrt(1 - t * t)
            self.span(y, cx - dx, cx + dx, rgb, alpha)

    def disc(self, cx, cy, r, rgb, alpha=255):
        self.ellipse(cx, cy, r, r, rgb, alpha)

    def poly(self, pts, rgb, alpha=255):
        """Scanline polygon fill, pts = [(x,y),...]."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(H - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x1, y1p = pts[i]
                x2, y2p = pts[(i + 1) % n]
                if (y1p <= yc < y2p) or (y2p <= yc < y1p):
                    t = (yc - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self.span(y, xs[k], xs[k + 1], rgb, alpha)

    def rect(self, x, y, w, h, rgb, alpha=255):
        for yy in range(max(0, y), min(H, y + h)):
            self.span(yy, x, x + w, rgb, alpha)

    def hline(self, y, x0, x1, rgb, alpha=255, thick=1):
        for yy in range(y, min(H, y + thick)):
            self.span(yy, x0, x1, rgb, alpha)

    # ---- sky base pass: vertical gradient + radial glows + noise tint ----
    def paint_base(self, stops, glow=None, noise=None, noise_tint=(0, 0, 0),
                   noise_amp=0.0, vignette=0.0, glow2=None):
        """stops: [(pos0..1, (r,g,b)), ...]. glow: (cx,cy,radius,(r,g,b),peak).
        noise: low-res field list (size S x S) sampled bilinearly."""
        grad = [None] * H
        for y in range(H):
            t = y / (H - 1)
            c = stops[-1][1]
            for i in range(len(stops) - 1):
                p0, c0 = stops[i]
                p1, c1 = stops[i + 1]
                if p0 <= t <= p1:
                    f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                    c = lerp3(c0, c1, f)
                    break
            grad[y] = c
        S = 0
        if noise is not None:
            S = int(math.sqrt(len(noise)))

        def glow_lut(radius, peak):
            n = (radius * radius >> 8) + 2
            tab = [0.0] * n
            for i in range(n):
                d2 = i << 8
                # exp falloff tapered smoothly to exactly 0 at the edge
                edge = 1.0 - d2 / (radius * radius)
                if edge < 0:
                    edge = 0.0
                tab[i] = peak * math.exp(-d2 / (radius * radius * 0.55)) * edge * edge
            return tab

        gl = None
        if glow is not None:
            gl = (glow[0], glow[1], glow_lut(glow[2], glow[4]), glow[3])
        gl2 = None
        if glow2 is not None:
            gl2 = (glow2[0], glow2[1], glow_lut(glow2[2], glow2[4]), glow2[3])
        p = self.p
        nt_r, nt_g, nt_b = noise_tint
        for y in range(H):
            gr, gg, gb = grad[y]
            base = y * W * 3
            dyv = (y - H / 2) / (H / 2)
            vrow = 1.0 - vignette * dyv * dyv
            gy2 = None
            if gl is not None:
                gy2 = (y - gl[1]) * (y - gl[1])
            gy2b = None
            if gl2 is not None:
                gy2b = (y - gl2[1]) * (y - gl2[1])
            if noise is not None:
                ny = y * (S - 1) / (H - 1)
                ny0 = int(ny)
                ny1 = min(S - 1, ny0 + 1)
                nfy = ny - ny0
                nrow0 = ny0 * S
                nrow1 = ny1 * S
            for x in range(W):
                r, g, b = gr, gg, gb
                if gl is not None:
                    dx = x - gl[0]
                    d2 = (dx * dx + gy2) >> 8
                    if d2 < len(gl[2]):
                        gv = gl[2][d2]
                        if gv > 0.001:
                            cr, cg, cb = gl[3]
                            r += (cr - r) * gv
                            g += (cg - g) * gv
                            b += (cb - b) * gv
                if gl2 is not None:
                    dx = x - gl2[0]
                    d2 = (dx * dx + gy2b) >> 8
                    if d2 < len(gl2[2]):
                        gv = gl2[2][d2]
                        if gv > 0.001:
                            cr, cg, cb = gl2[3]
                            r += (cr - r) * gv
                            g += (cg - g) * gv
                            b += (cb - b) * gv
                if noise is not None:
                    nx = x * (S - 1) / (W - 1)
                    nx0 = int(nx)
                    nx1 = min(S - 1, nx0 + 1)
                    nfx = nx - nx0
                    nv = (noise[nrow0 + nx0] + (noise[nrow0 + nx1] - noise[nrow0 + nx0]) * nfx)
                    nv += ((noise[nrow1 + nx0] + (noise[nrow1 + nx1] - noise[nrow1 + nx0]) * nfx) - nv) * nfy
                    na = (nv - 0.5) * noise_amp
                    r += nt_r * na
                    g += nt_g * na
                    b += nt_b * na
                if vignette:
                    dxv = (x - W / 2) / (W / 2)
                    v = vrow * (1.0 - vignette * dxv * dxv)
                    r *= v
                    g *= v
                    b *= v
                o = base + x * 3
                p[o] = clamp255(int(r))
                p[o + 1] = clamp255(int(g))
                p[o + 2] = clamp255(int(b))

    def stars(self, seed, count, y_max, bright=1.0, colors=None):
        rnd = random.Random(seed)
        for _ in range(count):
            x = rnd.uniform(0, W)
            y = rnd.uniform(0, y_max)
            r = rnd.uniform(0.5, 1.8)
            a = int(rnd.uniform(90, 255) * bright)
            col = (255, 255, 255) if colors is None else rnd.choice(colors)
            self.disc(x, y, r, col, a)
            if r > 1.5:
                self.span(int(y), x - 4, x + 4, col, a // 3)
                for yy in range(int(y) - 4, int(y) + 5):
                    self.blend_px(int(x), yy, col[0], col[1], col[2], a // 4)

    def save(self, path, level=6):
        raw = bytearray()
        stride = W * 3
        for y in range(H):
            raw.append(0)  # filter None
            raw += self.p[y * stride:(y + 1) * stride]
        comp = zlib.compress(bytes(raw), level)

        def chunk(typ, data):
            c = struct.pack(">I", len(data)) + typ + data
            return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", comp)
        png += chunk(b"IEND", b"")
        with open(path, "wb") as f:
            f.write(png)
        return len(png)

# ---------------- 5x7 block font (each row is 5 bits) ----------------
FONT = {
 'A': [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11], 'B': [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
 'C': [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E], 'D': [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
 'E': [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F], 'F': [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
 'G': [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F], 'H': [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
 'I': [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E], 'J': [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
 'K': [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11], 'L': [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
 'M': [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11], 'N': [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
 'O': [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E], 'P': [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
 'Q': [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D], 'R': [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
 'S': [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E], 'T': [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
 'U': [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E], 'V': [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
 'W': [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11], 'X': [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
 'Y': [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04], 'Z': [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
 ' ': [0, 0, 0, 0, 0, 0, 0], '!': [0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04],
 '.': [0, 0, 0, 0, 0, 0x0C, 0x0C], "'": [0x04, 0x04, 0x08, 0, 0, 0, 0],
 '-': [0, 0, 0, 0x1F, 0, 0, 0], ':': [0, 0x0C, 0x0C, 0, 0x0C, 0x0C, 0],
}


def text_width(s, scale):
    return len(s) * 6 * scale - scale


def _text_raw(img, s, x, y, scale, rgb, alpha):
    cx = x
    for ch in s:
        glyph = FONT.get(ch, FONT[' '])
        for row in range(7):
            bits = glyph[row]
            for col in range(5):
                if bits & (1 << (4 - col)):
                    img.rect(cx + col * scale, y + row * scale, scale, scale, rgb, alpha)
        cx += 6 * scale


def draw_text(img, s, x, y, scale, rgb, glow_rgb=None, glow_alpha=90):
    """Crisp block text. scale = pixel size of one font cell unit."""
    s = s.upper()
    if glow_rgb is not None:
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            _text_raw(img, s, x + dx, y + dy, scale, glow_rgb, glow_alpha)
    _text_raw(img, s, x, y, scale, rgb, 255)

# ---------------- scene: "LIFTOFF" ----------------
def render():
    img = Img()
    rnd2 = random.Random(99)

    # sky: indigo -> magenta -> burning orange horizon, with nebula noise
    noise = fbm(256, 11)
    img.paint_base(
        stops=[(0.0, (10, 8, 42)), (0.35, (48, 22, 88)), (0.62, (150, 48, 96)),
               (0.80, (255, 122, 48)), (1.0, (255, 176, 84))],
        glow=(770, 640, 420, (255, 214, 120), 0.85),
        glow2=(430, 700, 260, (255, 140, 60), 0.55),
        noise=noise, noise_tint=(60, 30, 90), noise_amp=0.35, vignette=0.22)
    img.stars(7, 260, 480, bright=0.9)

    # sun disc + halo rings
    img.disc(770, 640, 150, (255, 226, 150), 60)
    img.disc(770, 640, 110, (255, 226, 150), 90)
    img.disc(770, 640, 78, (255, 240, 190), 255)
    img.disc(770, 640, 60, (255, 252, 230), 255)

    # god rays from the sun (translucent wedges)
    for (dx, wdt, a) in ((-460, 110, 60), (-280, 70, 52), (-100, 150, 66), (50, 80, 52), (240, 120, 56)):
        img.poly([(770, 640), (770 + dx - wdt, 1024), (770 + dx + wdt, 1024)], (255, 200, 110), a)

    # distant haze: very soft wide bands low in the sky, nothing disc-like
    img.ellipse(240, 330, 320, 13, (255, 150, 110), 18)
    img.ellipse(880, 260, 300, 12, (255, 170, 130), 16)
    img.ellipse(140, 500, 280, 11, (255, 140, 90), 16)

    # birds
    for (bx, by, s) in [(300, 240, 9), (330, 260, 7), (620, 300, 8), (660, 320, 6), (250, 350, 7)]:
        img.poly([(bx - s, by), (bx, by - s * 0.6), (bx + s, by)], (20, 14, 44), 220)

    # city skyline: back layer, then darker front layer with lit windows
    x = -10
    back = []
    while x < 1034:
        w = rnd2.randint(46, 96)
        h = rnd2.randint(110, 250)
        back.append((x, w, h))
        x += w + rnd2.randint(2, 10)
    for (bx, bw, bh) in back:
        img.rect(bx, 1024 - bh, bw, bh, (52, 44, 96))
    x = -10
    front = []
    while x < 1034:
        w = rnd2.randint(40, 84)
        h = rnd2.randint(170, 330)
        front.append((x, w, h))
        x += w + rnd2.randint(2, 8)
    for (bx, bw, bh) in front:
        img.rect(bx, 1024 - bh, bw, bh, (16, 14, 38))
        if rnd2.random() < 0.4:  # rooftop antenna + beacon
            ax = bx + bw // 2
            img.rect(ax, 1024 - bh - 26, 3, 26, (16, 14, 38))
            img.disc(ax + 1, 1024 - bh - 28, 3, (255, 60, 90), 255)
    win_cols = [(255, 200, 110), (120, 230, 255), (255, 110, 170), (255, 240, 180)]
    for (bx, bw, bh) in front:
        top = 1024 - bh
        for wy in range(top + 14, 1010, 22):
            for wx in range(bx + 8, bx + bw - 8, 16):
                if rnd2.random() < 0.42:
                    img.rect(wx, wy, 6, 9, rnd2.choice(win_cols), 235)
    for (bx, bw, bh) in front[::5]:  # neon edge strips on a few towers
        img.rect(bx + bw - 3, 1024 - bh, 3, bh, (0, 240, 255), 200)

    # ground + crowd silhouettes watching the launch
    img.rect(0, 1000, 1024, 24, (8, 7, 20))
    for i in range(46):
        cx = 30 + i * 21 + rnd2.randint(-6, 6)
        hh = rnd2.randint(16, 26)
        img.ellipse(cx, 1000 - hh // 2, 5, hh // 2, (8, 7, 20))
        img.disc(cx, 1000 - hh - 4, 5, (8, 7, 20))
        if rnd2.random() < 0.5:  # raised arm
            img.rect(cx + 4, 1000 - hh - 12, 3, 14, (8, 7, 20))
        if rnd2.random() < 0.22:  # phone light
            img.disc(cx + 6, 1000 - hh - 12, 2, (180, 240, 255), 255)

    # exhaust plume: soft glow + smooth teardrop flame + billowing smoke
    def flame_poly(wscale, ytop, ybot, col, alpha):
        left, right = [], []
        steps = 26
        for i in range(steps + 1):
            t = i / steps
            y = ytop + t * (ybot - ytop)
            wob = 1.0 + 0.16 * math.sin(t * 17.0) * (1 - t) + 0.08 * math.sin(t * 41.0 + 1.3)
            w = (36 * (1 - t * 0.88) + 6 * math.sin(t * 9.0)) * wob * wscale
            left.append((430 - max(2.0, w), y))
            right.append((430 + max(2.0, w), y))
        img.poly(left + right[::-1], col, alpha)

    img.ellipse(430, 790, 120, 170, (255, 140, 50), 46)
    img.ellipse(430, 800, 80, 130, (255, 190, 80), 60)
    for i in range(16):  # smoke: wide stretched ellipses, low alpha
        t = i / 15.0
        side = -1 if i % 2 else 1
        sx = 430 + side * (55 + t * 215 + rnd2.uniform(-16, 16))
        sy = 720 + t * 290 + rnd2.uniform(-18, 18)
        base_r = 34 + t * 48
        for (ox, oy, rr, aa) in ((0, 0, base_r, 40), (-base_r * 0.8, 12, base_r * 0.75, 34),
                                 (base_r * 0.7, -10, base_r * 0.65, 30), (0, -base_r * 0.5, base_r * 0.6, 26)):
            img.ellipse(sx + ox, sy + oy, rr * 1.45, rr * 0.62, (118, 102, 132), aa)
            img.ellipse(sx + ox, sy + oy - 5, rr * 1.0, rr * 0.45, (150, 128, 148), aa // 2)
    flame_poly(1.0, 640, 835, (255, 110, 35), 255)
    flame_poly(0.62, 645, 790, (255, 200, 80), 255)
    flame_poly(0.32, 648, 740, (255, 252, 225), 255)

    # rocket
    cx = 430
    img.poly([(cx, 268), (cx - 34, 372), (cx + 34, 372)], (255, 92, 42))   # nose
    img.rect(cx - 34, 372, 68, 268, (238, 242, 248))                        # body
    img.rect(cx - 34, 372, 10, 268, (200, 208, 220))                        # shading L
    img.rect(cx + 24, 372, 10, 268, (200, 208, 220))                        # shading R
    img.rect(cx - 34, 500, 68, 26, (255, 92, 42))                           # orange band
    img.rect(cx - 34, 556, 68, 10, (30, 40, 70))                            # dark band
    img.disc(cx, 428, 17, (30, 40, 70))                                     # window rim
    img.disc(cx, 428, 12, (140, 220, 255))                                  # window
    img.disc(cx - 4, 424, 4, (255, 255, 255))                               # window glint
    img.poly([(cx - 34, 560), (cx - 78, 668), (cx - 34, 644)], (255, 92, 42))  # fin L
    img.poly([(cx + 34, 560), (cx + 78, 668), (cx + 34, 644)], (255, 92, 42))  # fin R
    img.poly([(cx - 34, 600), (cx - 58, 668), (cx - 34, 648)], (200, 60, 30))  # fin shade L
    img.poly([(cx + 34, 600), (cx + 58, 668), (cx + 34, 648)], (200, 60, 30))  # fin shade R
    img.rect(cx + 28, 372, 5, 268, (255, 190, 110), 220)                    # rim light, sun side
    for i in range(60):  # sparks / speed streaks
        sx = 300 + rnd2.uniform(0, 260)
        sy = 300 + rnd2.uniform(0, 560)
        ln = rnd2.randint(6, 22)
        img.hline(int(sy), int(sx), int(sx + ln), (255, 220, 150), 200, thick=2)

    # headline
    tw = text_width("LIFTOFF", 13)
    draw_text(img, "LIFTOFF", (1024 - tw) // 2, 64, 13, (255, 255, 255),
              glow_rgb=(255, 120, 40), glow_alpha=110)
    return img


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    img = render()
    n = img.save(os.path.join(out_dir, "entry.png"))
    print("wrote %s (%d bytes)" % (os.path.join(out_dir, "entry.png"), n))


if __name__ == "__main__":
    main()
