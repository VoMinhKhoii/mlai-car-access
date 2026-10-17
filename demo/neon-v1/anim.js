// Vào Được — motion demo. Deterministic: render(t) draws frame at time t (seconds).
const W = 1920, H = 1080, TOTAL = 56;
const cv = document.getElementById('c'), x = cv.getContext('2d');
const C = { bg: '#03050b', cyan: '#2ee6ff', mag: '#ff2d8a', lime: '#a6ff3d', amber: '#ffb21e', red: '#ff3b4e',
  blue: '#2d7dff', water: '#38a3ff', white: '#eef4ff', dim: '#7c8aa8', unk: '#4f5d78' };
const FH = 'Montserrat', FB = '"Fira Sans"', FM = '"Source Code Pro"';

// ---------- utils
const cl = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const P = (t, a, b) => cl((t - a) / (b - a));
const E = {
  lin: t => t,
  out: t => 1 - Math.pow(1 - t, 3),
  in: t => t * t * t,
  io: t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  expo: t => t >= 1 ? 1 : 1 - Math.pow(2, -10 * t),
  exio: t => t <= 0 ? 0 : t >= 1 ? 1 : t < .5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2,
  back: t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
};
const rnd = i => { const s = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return s - Math.floor(s); };
const win = (t, a, b, fi = .4, fo = .4) => Math.min(E.out(P(t, a, a + fi)), 1 - E.in(P(t, b - fo, b)));
function hexA(h, a) { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }

// ---------- data prep
const FIT_NEED = 2.28, FIT_OK = 2.8;
const WAYS = D.ways.map((w, i) => {
  const p = w.p, cum = [0]; let L = 0, cx = 0, cy = 0;
  for (let k = 2; k < p.length; k += 2) { L += Math.hypot(p[k] - p[k - 2], p[k + 1] - p[k - 1]); cum.push(L); }
  for (let k = 0; k < p.length; k += 2) { cx += p[k]; cy += p[k + 1]; }
  cx /= p.length / 2; cy /= p.length / 2;
  let rad = 0; for (let k = 0; k < p.length; k += 2) rad = Math.max(rad, Math.hypot(p[k] - cx, p[k + 1] - cy));
  const fit = w.c <= 1 ? 'art' : w.c === 4 ? 'foot' : w.w == null ? 'unk' : w.w >= FIT_OK ? 'ok' : w.w >= FIT_NEED ? 'tight' : 'no';
  return { ...w, cum, L, cx, cy, rad, r: rnd(i + 1), fit,
    dC: Math.hypot(cx + 300, cy), dD: Math.hypot(cx - D.dst[0], cy - D.dst[1]), dS: Math.hypot(cx - D.stop[0], cy - D.stop[1]) };
});
function mkRoute(p) { const cum = [0]; let L = 0; for (let k = 2; k < p.length; k += 2) { L += Math.hypot(p[k] - p[k - 2], p[k + 1] - p[k - 1]); cum.push(L); } return { p, cum, L }; }
const R_CAR = mkRoute(D.car), R_WALK = mkRoute(D.walk), R_NAIVE = mkRoute(D.naive);
function ptAt(r, f) {
  const d = cl(f) * r.L; let i = 1; while (i < r.cum.length - 1 && r.cum[i] < d) i++;
  const a = r.cum[i - 1], b = r.cum[i], q = b > a ? (d - a) / (b - a) : 0, p = r.p;
  const x0 = p[2 * i - 2], y0 = p[2 * i - 1], x1 = p[2 * i], y1 = p[2 * i + 1];
  return [lerp(x0, x1, q), lerp(y0, y1, q), Math.atan2(y1 - y0, x1 - x0)];
}
function tracePart(p, cum, L, f0, f1) {
  const d0 = f0 * L, d1 = f1 * L; let started = false;
  for (let i = 1; i < cum.length; i++) {
    const a = cum[i - 1], b = cum[i]; if (b < d0) continue; if (a > d1) break;
    const x0 = p[2 * i - 2], y0 = p[2 * i - 1], x1 = p[2 * i], y1 = p[2 * i + 1], s = b - a || 1;
    const qa = cl((d0 - a) / s), qb = cl((d1 - a) / s);
    if (!started) { x.moveTo(lerp(x0, x1, qa), lerp(y0, y1, qa)); started = true; }
    x.lineTo(lerp(x0, x1, qb), lerp(y0, y1, qb));
  }
}
const BLK = (() => { const i = D.blk, p = D.naive; return [p[2 * i], p[2 * i + 1], R_NAIVE.cum[i] / R_NAIVE.L]; })();
const toLL = (wx, wy) => [10.8 - wy / 110540, 106.712 + wx / (111320 * Math.cos(10.8 * Math.PI / 180))];

// labelled alleys near destination for the scan scene
const LABELS = WAYS.filter(w => w.w != null && w.c >= 2 && w.dD < 650 && w.L > 35)
  .sort((a, b) => a.r - b.r).slice(0, 18);
// no-stopping signs on arterials near the stop
const SIGNS = WAYS.filter(w => w.c <= 1 && w.dS < 520 && w.L > 40).sort((a, b) => a.dS - b.dS).slice(0, 7);

// ---------- camera
let CAM = { x: 0, y: 0, s: .5, r: 0 };
function setCam(c) { x.setTransform(1, 0, 0, 1, 0, 0); x.translate(W / 2, H / 2); x.rotate(c.r); x.scale(c.s, c.s); x.translate(-c.x, -c.y); }
function w2s(c, px, py) { const dx = (px - c.x) * c.s, dy = (py - c.y) * c.s, co = Math.cos(c.r), si = Math.sin(c.r); return [W / 2 + dx * co - dy * si, H / 2 + dx * si + dy * co]; }
const KEYS = [ // t, x, y, scale(px/m), rot
  [0, D.dst[0], D.dst[1], 1.1, -.35],
  [5.6, D.dst[0] - 150, D.dst[1] - 80, .8, -.22],
  [11.6, -260, -40, .31, 0],
  [19.6, -200, 0, .34, .06],
  [22.6, (D.dst[0] + BLK[0]) / 2 - 60, (D.dst[1] + BLK[1]) / 2 - 20, 1.55, -.08],
  [27.4, D.dst[0] - 40, D.dst[1] - 10, 1.05, .04],
  [30.2, -250, -30, .3, 0],
  [35.4, -230, -10, .33, -.03],
  [38.4, D.stop[0] + 80, D.stop[1] - 40, 1.7, .1],
  [40.0, D.stop[0] + 60, D.stop[1] - 20, 1.6, .08],
];
function camAt(t) {
  if (t >= 40 && t < 49) return routeCam(t);
  if (t >= 49) {
    const q = E.io(P(t, 49, 55.5)), a = routeCam(48.99);
    return { x: lerp(a.x, -260, q), y: lerp(a.y, -20, q), s: Math.exp(lerp(Math.log(a.s), Math.log(.29), q)), r: lerp(a.r, -.12, q) };
  }
  let i = 0; while (i < KEYS.length - 1 && KEYS[i + 1][0] <= t) i++;
  const k0 = KEYS[i], k1 = KEYS[Math.min(i + 1, KEYS.length - 1)];
  const q = k1 === k0 ? 1 : E.exio(P(t, k0[0], k1[0]) * 0.999 + 0.0005);
  const qq = (i === 0 || i === 2 || i === 6) ? E.io(P(t, k0[0], k1[0])) : q;
  return { x: lerp(k0[1], k1[1], qq), y: lerp(k0[2], k1[2], qq), s: Math.exp(lerp(Math.log(k0[3]), Math.log(k1[3]), qq)), r: lerp(k0[4], k1[4], qq) };
}
const CAR_T0 = 40.6, CAR_T1 = 45.2, WALK_T0 = 46.0, WALK_T1 = 48.0;
function carF(t) { return E.io(P(t, CAR_T0, CAR_T1)); }
function routeCam(t) {
  const k = KEYS[KEYS.length - 1];
  const f = carF(t), [hx, hy] = ptAt(R_CAR, f);
  const [lx, ly] = ptAt(R_CAR, Math.max(0, f - .03));
  const into = E.io(P(t, 40, 41.4));
  const mid = [(D.stop[0] + D.dst[0]) / 2 + 60, (D.stop[1] + D.dst[1]) / 2];
  const fin = E.io(P(t, 44.6, 46.4));
  let cx = lerp(k[1], (hx + lx) / 2, into), cy = lerp(k[2], (hy + ly) / 2, into);
  let s = Math.exp(lerp(Math.log(k[3]), Math.log(.5 + .7 * Math.pow(Math.sin(Math.PI * f), 0) * 0 + (f < .5 ? lerp(.55, .42, f * 2) : lerp(.42, .9, (f - .5) * 2))), into));
  cx = lerp(cx, mid[0], fin); cy = lerp(cy, mid[1], fin); s = Math.exp(lerp(Math.log(s), Math.log(2.3), fin));
  const r = lerp(lerp(k[4], -.18, into), .05, fin) + .02 * Math.sin(t * .7);
  return { x: cx, y: cy, s, r };
}

// ---------- precomputed overlays
function mkCanvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
const VIG = (() => { const c = mkCanvas(W, H), g = c.getContext('2d'); const gr = g.createRadialGradient(W / 2, H / 2, H * .35, W / 2, H / 2, H * 1.05);
  gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, 'rgba(0,0,0,.82)'); g.fillStyle = gr; g.fillRect(0, 0, W, H); return c; })();
const SCAN = (() => { const c = mkCanvas(W, H), g = c.getContext('2d'); g.fillStyle = 'rgba(0,0,0,.16)'; for (let y = 0; y < H; y += 3) g.fillRect(0, y, W, 1); return c; })();
const GRAIN = [0, 1, 2, 3].map(s => { const c = mkCanvas(480, 270), g = c.getContext('2d'), im = g.createImageData(480, 270);
  for (let i = 0; i < im.data.length; i += 4) { const v = rnd(i * .37 + s * 999) * 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; }
  g.putImageData(im, 0, 0); return c; });

// ---------- text helpers
function font(o) { return `${o.w || 800} ${o.size || 40}px ${o.f || FH}`; }
function T(str, px, py, o = {}) {
  x.save(); x.font = font(o); x.letterSpacing = (o.ls || 0) + 'px'; x.textAlign = o.al || 'left'; x.textBaseline = o.bl || 'alphabetic';
  x.globalAlpha *= (o.a ?? 1); x.fillStyle = o.c || C.white;
  if (o.glow) { x.shadowColor = o.glow; x.shadowBlur = o.gb || 24; }
  x.fillText(str, px, py); x.restore();
}
function measure(str, o) { x.save(); x.font = font(o); x.letterSpacing = (o.ls || 0) + 'px'; const m = x.measureText(str).width; x.restore(); return m; }
// per-character rise-from-mask reveal; p: 0..1 (in), out: 0..1 (exit)
function RT(str, px, py, p, o = {}, out = 0) {
  const ch = Array.from(str.normalize('NFC')), n = ch.length, d = o.stagger ?? .07, size = o.size || 40;
  const total = measure(str, o); let ox = o.al === 'center' ? px - total / 2 : o.al === 'right' ? px - total : px;
  x.save(); x.beginPath(); x.rect(ox - 40, py - size * 1.35, total + 80, size * 1.75); x.clip();
  let acc = '';
  for (let i = 0; i < n; i++) {
    const cx0 = ox + measure(acc, o); acc += ch[i];
    const q = E.expo(cl(p * (n * d + 1) - i * d)), qo = E.in(cl(out * (n * d + 1) - i * d));
    if (q <= 0) continue;
    const dy = (1 - q) * size * 1.1 - qo * size * 1.2;
    T(ch[i], cx0, py + dy, { ...o, al: 'left', a: (o.a ?? 1) * q * (1 - qo) });
  }
  x.restore();
}
function typed(str, px, py, p, o = {}, cursor = true) {
  const ch = Array.from(str), n = Math.floor(ch.length * cl(p)); const s = ch.slice(0, n).join('');
  T(s, px, py, o);
  if (cursor && p > 0 && p < 1.15) { const w = measure(s, o); x.save(); x.globalAlpha *= (o.a ?? 1); x.fillStyle = o.c || C.cyan; x.fillRect(px + w + 4, py - (o.size || 20) * .8, (o.size || 20) * .55, (o.size || 20) * .95); x.restore(); }
}
function glitchText(str, px, py, o, g) { // g: 0..1 intensity
  if (g > 0.01) {
    x.save(); x.globalCompositeOperation = 'lighter';
    const off = g * 14;
    T(str, px - off, py, { ...o, c: C.mag, a: (o.a ?? 1) * .8, glow: null });
    T(str, px + off, py + g * 3, { ...o, c: C.cyan, a: (o.a ?? 1) * .8, glow: null });
    x.restore();
  }
  T(str, px, py, o);
}
function kicker(num, label, px, py, a) {
  if (a <= 0) return;
  x.save(); x.globalAlpha = a;
  x.fillStyle = C.cyan; x.fillRect(px, py - 13, 34 * a, 3);
  T(num, px + 46, py, { f: FM, w: 600, size: 18, c: C.cyan, ls: 3 });
  T(label, px + 90, py, { f: FM, w: 500, size: 18, c: C.white, ls: 4, a: .85 });
  x.restore();
}
function panel(px, py, pw, ph, a, accent = C.cyan) {
  if (a <= 0) return;
  x.save(); x.globalAlpha = a;
  x.fillStyle = 'rgba(5,9,20,.82)'; x.strokeStyle = hexA(accent, .35); x.lineWidth = 1;
  x.beginPath(); x.roundRect(px, py, pw, ph, 6); x.fill(); x.stroke();
  x.strokeStyle = accent; x.lineWidth = 2; const k = 16;
  for (const [cx, cy, sx, sy] of [[px, py, 1, 1], [px + pw, py, -1, 1], [px, py + ph, 1, -1], [px + pw, py + ph, -1, -1]]) {
    x.beginPath(); x.moveTo(cx + sx * k, cy); x.lineTo(cx, cy); x.lineTo(cx, cy + sy * k); x.stroke();
  }
  x.restore();
}
function chip(str, px, py, col, a, size = 22) {
  if (a <= 0) return;
  const o = { f: FM, w: 700, size, ls: 2, c: '#04060c' }; const w = measure(str, o) + 28;
  x.save(); x.globalAlpha = a; x.shadowColor = col; x.shadowBlur = 30; x.fillStyle = col;
  x.beginPath(); x.roundRect(px, py - size - 8, w, size + 18, 4); x.fill(); x.restore();
  T(str, px + 14, py, { ...o, a });
  return w;
}

// ---------- map
function drawGrid(c, a) {
  if (a <= 0) return;
  setCam(c); const step = c.s > 1 ? 50 : 250, R = Math.hypot(W, H) / 2 / c.s + step;
  x.strokeStyle = hexA('#3a5bb0', .13 * a); x.lineWidth = 1 / c.s; x.beginPath();
  for (let gx = Math.floor((c.x - R) / step) * step; gx < c.x + R; gx += step) { x.moveTo(gx, c.y - R); x.lineTo(gx, c.y + R); }
  for (let gy = Math.floor((c.y - R) / step) * step; gy < c.y + R; gy += step) { x.moveTo(c.x - R, gy); x.lineTo(c.x + R, gy); }
  x.stroke(); x.setTransform(1, 0, 0, 1, 0, 0);
}
const NEUTRAL = [['#5fe3ff', 2.6, 1], ['#2fa7e6', 1.7, .85], ['#2f67b0', 1.15, .75], ['#284d88', .95, .6], ['#26334f', .7, .5]];
const FITC = { art: '#5fe3ff', ok: C.lime, tight: C.amber, no: C.red, unk: C.unk, foot: '#2a3550' };
function drawMap(t, c, o) {
  const k = Math.pow(c.s / .5, .42), alpha = o.alpha ?? 1;
  if (alpha <= 0) return;
  const view = Math.hypot(W, H) / 2 / c.s;
  const groups = new Map();
  for (const w of WAYS) {
    if (Math.hypot(w.cx - c.x, w.cy - c.y) - w.rad > view) continue;
    const rv = o.reveal ? o.reveal(w) : 1; if (rv <= 0) continue;
    let col, lw, a;
    const [nc, nw, na] = NEUTRAL[w.c];
    const fp = o.fit ? o.fit(w) : 0;
    if (fp >= 1) { col = FITC[w.fit]; lw = w.c <= 1 ? nw : nw * (w.fit === 'unk' ? 1 : 1.5); a = w.fit === 'unk' ? .55 : w.fit === 'foot' ? .4 : 1; }
    else if (fp > 0) { col = '#ffffff'; lw = nw * 2.2; a = 1; }
    else { col = nc; lw = nw; a = na; }
    if (o.dimAlleys && w.c >= 2 && fp >= 1 && w.fit !== 'no' && w.fit !== 'art') a *= o.dimAlleys;
    const key = col + '|' + lw + '|' + a;
    let g = groups.get(key); if (!g) { g = { col, lw, a, ws: [] }; groups.set(key, g); }
    g.ws.push([w, rv]);
  }
  setCam(c); x.lineCap = 'round'; x.lineJoin = 'round';
  x.save(); x.globalCompositeOperation = 'lighter';
  for (const pass of [0, 1]) {
    for (const g of groups.values()) {
      x.beginPath();
      for (const [w, rv] of g.ws) {
        if (rv >= 1) { x.moveTo(w.p[0], w.p[1]); for (let i = 2; i < w.p.length; i += 2) x.lineTo(w.p[i], w.p[i + 1]); }
        else tracePart(w.p, w.cum, w.L, 0, rv);
      }
      x.strokeStyle = g.col;
      if (pass === 0) { x.globalAlpha = g.a * .16 * alpha; x.lineWidth = g.lw * 4.5 * k / c.s; }
      else { x.globalAlpha = g.a * alpha; x.lineWidth = g.lw * k / c.s; }
      x.stroke();
    }
  }
  x.restore(); x.setTransform(1, 0, 0, 1, 0, 0);
}
function drawPackets(t, c, a) { // light pulses flowing along arterials
  if (a <= 0) return;
  setCam(c); x.save(); x.globalCompositeOperation = 'lighter';
  const rr = 3.2 / c.s;
  for (let i = 0; i < WAYS.length; i++) {
    const w = WAYS[i]; if (w.c > 1 || w.L < 60) continue;
    for (let j = 0; j < 2; j++) {
      const f = ((t * (30 + 50 * w.r) / w.L) + w.r + j * .5) % 1;
      const p = ptAt(w, f);
      x.globalAlpha = a * .9; x.fillStyle = '#d8fbff';
      x.beginPath(); x.arc(p[0], p[1], rr, 0, 7); x.fill();
      x.globalAlpha = a * .25; x.fillStyle = C.cyan; x.beginPath(); x.arc(p[0], p[1], rr * 3, 0, 7); x.fill();
    }
  }
  x.restore(); x.setTransform(1, 0, 0, 1, 0, 0);
}
function strokeRoute(r, f0, f1, c, col, lw, glow = 5, dash = null, dashOff = 0) {
  setCam(c); x.save(); x.globalCompositeOperation = 'lighter'; x.lineCap = 'round'; x.lineJoin = 'round';
  if (dash) { x.setLineDash(dash.map(v => v / c.s)); x.lineDashOffset = dashOff / c.s; }
  x.strokeStyle = col;
  x.beginPath(); tracePart(r.p, r.cum, r.L, f0, f1);
  x.globalAlpha = .22; x.lineWidth = lw * glow / c.s; x.stroke();
  x.globalAlpha = 1; x.lineWidth = lw / c.s; x.stroke();
  x.restore(); x.setTransform(1, 0, 0, 1, 0, 0);
}
function ring(sx, sy, rad, col, a, lw = 2) { if (a <= 0 || rad <= 0) return; x.save(); x.globalAlpha = a; x.strokeStyle = col; x.lineWidth = lw; x.beginPath(); x.arc(sx, sy, rad, 0, 7); x.stroke(); x.restore(); }
function dot(sx, sy, rad, col, a) { if (a <= 0) return; x.save(); x.globalAlpha = a; x.fillStyle = col; x.shadowColor = col; x.shadowBlur = rad * 3; x.beginPath(); x.arc(sx, sy, rad, 0, 7); x.fill(); x.restore(); }

// ---------- car (blueprint, local meters, nose toward -y)
const VF3 = { W: 1.68, L: 3.19, WB: 2.075 };
function drawCar(cx, cy, sc, ang, a, col, fill = 'rgba(6,14,30,.9)') {
  const { W: cw, L: cl_, WB } = VF3;
  x.save(); x.translate(cx, cy); x.rotate(ang); x.scale(sc, sc); x.globalAlpha = a;
  x.lineWidth = 2.2 / sc; x.strokeStyle = col; x.lineJoin = 'round';
  // headlight beams
  const g = x.createLinearGradient(0, -cl_ / 2, 0, -cl_ / 2 - 3.2);
  g.addColorStop(0, hexA(col, .28)); g.addColorStop(1, hexA(col, 0));
  x.fillStyle = g; x.beginPath(); x.moveTo(-cw * .42, -cl_ / 2); x.lineTo(-cw * .9, -cl_ / 2 - 3.2); x.lineTo(cw * .9, -cl_ / 2 - 3.2); x.lineTo(cw * .42, -cl_ / 2); x.fill();
  // wheels
  x.fillStyle = col; for (const sy of [-1, 1]) for (const sx of [-1, 1]) { x.beginPath(); x.roundRect(sx * (cw / 2 - .02) - .1, sy * WB / 2 - .27, .2, .54, .05); x.fill(); }
  // body
  x.fillStyle = fill; x.shadowColor = col; x.shadowBlur = 25;
  x.beginPath(); x.roundRect(-cw / 2, -cl_ / 2, cw, cl_, [.5, .5, .32, .32]); x.fill(); x.stroke(); x.shadowBlur = 0;
  // glasshouse
  x.beginPath(); x.moveTo(-cw * .4, -cl_ / 2 + .95); x.lineTo(cw * .4, -cl_ / 2 + .95); x.lineTo(cw * .36, -cl_ / 2 + 1.45); x.lineTo(-cw * .36, -cl_ / 2 + 1.45); x.closePath(); x.stroke();
  x.beginPath(); x.roundRect(-cw * .36, -cl_ / 2 + 1.5, cw * .72, 1.05, .12); x.stroke();
  x.beginPath(); x.moveTo(-cw * .36, cl_ / 2 - .45); x.lineTo(cw * .36, cl_ / 2 - .45); x.lineTo(cw * .38, cl_ / 2 - .62); x.lineTo(-cw * .38, cl_ / 2 - .62); x.closePath(); x.stroke();
  // mirrors
  x.beginPath(); x.moveTo(-cw / 2, -cl_ / 2 + 1.0); x.lineTo(-cw / 2 - .12, -cl_ / 2 + 1.06); x.moveTo(cw / 2, -cl_ / 2 + 1.0); x.lineTo(cw / 2 + .12, -cl_ / 2 + 1.06); x.stroke();
  // lights
  x.fillStyle = '#ffffff'; x.shadowColor = '#fff'; x.shadowBlur = 18;
  x.fillRect(-cw * .42, -cl_ / 2 + .02, .32, .06); x.fillRect(cw * .42 - .32, -cl_ / 2 + .02, .32, .06);
  x.fillStyle = C.red; x.shadowColor = C.red; x.fillRect(-cw * .45, cl_ / 2 - .08, cw * .9, .05);
  x.restore();
}
function dimLine(x0, y0, x1, y1, label, col, a, off = 0, size = 20) {
  if (a <= 0) return;
  x.save(); x.globalAlpha = a; x.strokeStyle = col; x.fillStyle = col; x.lineWidth = 1.5;
  const ang = Math.atan2(y1 - y0, x1 - x0);
  x.beginPath(); x.moveTo(x0, y0); x.lineTo(x1, y1); x.stroke();
  for (const [px, py, s] of [[x0, y0, 1], [x1, y1, -1]]) {
    x.save(); x.translate(px, py); x.rotate(ang); x.beginPath(); x.moveTo(0, 0); x.lineTo(s * 12, -5); x.lineTo(s * 12, 5); x.closePath(); x.fill();
    x.beginPath(); x.moveTo(0, -10); x.lineTo(0, 10); x.stroke(); x.restore();
  }
  x.restore();
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  const o = { f: FM, w: 700, size, c: col, al: 'center', a };
  const tw = measure(label, o) + 16;
  x.save(); x.globalAlpha = a; x.fillStyle = C.bg; x.fillRect(mx - tw / 2 + off, my - size * .75, tw, size * 1.4); x.restore();
  T(label, mx + off, my + size * .35, o);
}

// ---------- scenes
function sceneIntro(t) {
  // scanning line
  const l1 = E.expo(P(t, .1, .9)), split = E.exio(P(t, .9, 1.7));
  const yTop = 540 - split * 210, yBot = 540 + split * 210, lw = 1500 * l1;
  const out = P(t, 5.2, 6.0);
  x.save(); x.globalAlpha = 1 - out;
  for (const yy of [yTop, yBot]) {
    x.save(); x.shadowColor = C.cyan; x.shadowBlur = 25; x.fillStyle = C.cyan; x.globalAlpha *= (1 - out);
    x.fillRect(960 - lw / 2, yy - 1, lw, 2); x.restore();
    T(`${(yy === yTop ? 'N' : 'S')} ·  10.8°N 106.7°E  ·  BÌNH THẠNH, TP.HCM`, 960 - lw / 2, yy + (yy === yTop ? -14 : 30), { f: FM, w: 500, size: 15, c: C.cyan, ls: 4, a: P(t, 1.2, 1.6) * (1 - out) });
  }
  x.restore();
  const g = Math.max(0, 1 - P(t, 1.5, 1.9)) * (t > 1.4 ? 1 : 0) + Math.max(0, 1 - Math.abs(t - 3.0) / .12) + P(t, 5.0, 5.6) * 1.5;
  x.save(); x.beginPath(); x.rect(0, yTop + 2, W, Math.max(0, yBot - yTop - 4)); x.clip();
  const sc = 1 + .04 * P(t, 1.5, 6) + E.in(P(t, 5.1, 6)) * .6;
  x.translate(960, 540); x.scale(sc, sc); x.translate(-960, -540);
  const p1 = P(t, 1.3, 2.5);
  RT('XE BẠN VÀO ĐƯỢC,', 960, 500, p1, { size: 120, w: 900, ls: -2, al: 'center', c: C.white, stagger: .05 }, P(t, 5.1, 5.8));
  RT('VÀ RA ĐƯỢC KHÔNG?', 960, 640, P(t, 2.6, 3.6), { size: 120, w: 900, ls: -2, al: 'center', c: C.mag, glow: C.mag, gb: 40, stagger: .05 }, P(t, 5.1, 5.8));
  if (g > .05 && t > 2.8) glitchText('VÀ RA ĐƯỢC KHÔNG?', 960, 640, { size: 120, w: 900, ls: -2, al: 'center', c: 'rgba(0,0,0,0)', a: cl(g) }, cl(g));
  x.restore();
  typed('CAN YOUR CAR GET IN — AND BACK OUT?', 960 - measure('CAN YOUR CAR GET IN — AND BACK OUT?', { f: FM, w: 500, size: 24, ls: 6 }) / 2, 790,
    P(t, 3.6, 4.6), { f: FM, w: 500, size: 24, ls: 6, c: C.cyan, a: 1 - P(t, 5.0, 5.5) });
}

function hud(t, c, a) {
  if (a <= 0) return;
  x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = a;
  x.strokeStyle = hexA(C.cyan, .55); x.lineWidth = 2; const m = 34, k = 40;
  for (const [cx, cy, sx, sy] of [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]]) {
    x.beginPath(); x.moveTo(cx + sx * k, cy); x.lineTo(cx, cy); x.lineTo(cx, cy + sy * k); x.stroke();
  }
  T('VÀO ĐƯỢC', 64, 78, { size: 20, w: 900, ls: 6, c: C.white });
  T('CAR ACCESS LAYER · HCMC', 64, 102, { f: FM, w: 500, size: 13, ls: 3, c: C.dim });
  const rec = (Math.floor(t * 2) % 2) ? 1 : .25;
  dot(W - 214, 72, 6, C.red, rec);
  const ss = Math.floor(t), ff = Math.floor((t % 1) * 60);
  T(`LIVE  00:${String(ss).padStart(2, '0')}:${String(ff).padStart(2, '0')}`, W - 64, 78, { f: FM, w: 600, size: 18, ls: 3, al: 'right', c: C.white });
  const [la, lo] = toLL(c.x, c.y);
  T(`${la.toFixed(5)}°N  ${lo.toFixed(5)}°E   Z ${(Math.log2(c.s) + 17).toFixed(2)}   HDG ${((c.r * 180 / Math.PI + 360) % 360).toFixed(1)}°`, 64, H - 56,
    { f: FM, w: 500, size: 15, ls: 2, c: C.dim });
  // scale bar
  const m100 = 100 * c.s, sb = m100 > 260 ? 50 : m100 < 40 ? 500 : 100;
  x.fillStyle = C.dim; x.fillRect(W - 64 - sb * c.s, H - 66, sb * c.s, 2); x.fillRect(W - 64 - sb * c.s, H - 72, 2, 8); x.fillRect(W - 66, H - 72, 2, 8);
  T(`${sb} m`, W - 64, H - 78, { f: FM, w: 500, size: 13, ls: 2, al: 'right', c: C.dim });
  x.restore();
}

function counters(t, t0, a) {
  const items = [[WAYS.length, 'STREET SEGMENTS', C.cyan], [WAYS.filter(w => w.w != null).length, 'ALLEYS WITH WIDTH EVIDENCE', C.lime],
    [D.cams.length, 'LIVE TRAFFIC CAMERAS', C.amber], [D.floods.length, 'HISTORICAL FLOOD RECORDS', C.water]];
  items.forEach(([n, label, col], i) => {
    const p = E.expo(P(t, t0 + i * .25, t0 + i * .25 + 1.6)), q = E.out(P(t, t0 + i * .25, t0 + i * .25 + .5));
    const px = 120 + i * 430, py = 950;
    x.save(); x.globalAlpha = a * q;
    x.fillStyle = col; x.fillRect(px, py - 62, 3, 78);
    T(Math.round(n * p).toLocaleString('en-US'), px + 22, py - 10, { size: 54, w: 800, c: C.white, glow: col, gb: 20, a: a * q });
    T(label, px + 24, py + 16, { f: FM, w: 500, size: 14, ls: 3, c: col, a: a * q });
    x.restore();
  });
}

function sceneCity(t) {
  const a = win(t, 6, 12.3, .3, .5);
  kicker('01', 'THE CITY', 120, 210, a * P(t, 6.2, 6.6));
  RT('Hàng nghìn con hẻm.', 116, 300, P(t, 6.5, 7.4), { size: 76, w: 800, ls: -1 }, P(t, 11.5, 12.1));
  RT('Hẹp hơn chiếc xe của bạn.', 116, 390, P(t, 7.2, 8.2), { size: 76, w: 800, ls: -1, c: C.mag, glow: C.mag, gb: 30 }, P(t, 11.6, 12.2));
  T('Thousands of alleys — many narrower than your car.', 120, 445, { f: FB, w: 400, size: 26, c: C.dim, a: a * P(t, 8.2, 8.8) });
  counters(t, 8.6, a);
}

function sceneCar(t) {
  const a = win(t, 12, 20.2, .5, .6);
  if (a <= 0) return;
  // dim the map
  x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.fillStyle = `rgba(2,4,10,${.78 * a})`; x.fillRect(0, 0, W, H); x.restore();
  const sc = 155, cx = 1250, cy = 560;
  // alley walls
  const aw = lerp(4.2, 2.0, E.io(P(t, 15.2, 18.6)));
  const fitS = aw >= FIT_OK ? 'ok' : aw >= FIT_NEED ? 'tight' : 'no';
  const col = { ok: C.lime, tight: C.amber, no: C.red }[fitS];
  const wa = a * E.out(P(t, 12.6, 13.4));
  const shake = fitS === 'no' ? Math.sin(t * 90) * 3 * (1 - P(t, 18.6, 19.4)) : 0;
  x.save(); x.globalAlpha = wa; x.translate(shake, 0);
  const scroll = (t * 160) % 40;
  for (const s of [-1, 1]) {
    const wx = cx + s * aw / 2 * sc;
    x.save(); x.beginPath(); x.rect(s < 0 ? wx - 600 : wx, 120, 600, 880); x.clip();
    x.fillStyle = 'rgba(10,16,30,.85)'; x.fillRect(s < 0 ? wx - 600 : wx, 120, 600, 880);
    x.strokeStyle = hexA(col, .28); x.lineWidth = 2; x.beginPath();
    for (let yy = -80 + scroll; yy < 1100; yy += 40) { x.moveTo(wx - 700, yy + 700 * s * -1 + 0); x.lineTo(wx + 700, yy - 700 * s * -1 + 0); }
    x.stroke(); x.restore();
    x.save(); x.strokeStyle = col; x.lineWidth = 3; x.shadowColor = col; x.shadowBlur = 20;
    x.beginPath(); x.moveTo(wx, 120); x.lineTo(wx, 1000); x.stroke(); x.restore();
  }
  // clearance bands
  const ca = a * P(t, 14.0, 14.6);
  x.fillStyle = hexA(col, .12 * ca / Math.max(a, .001));
  for (const s of [-1, 1]) x.fillRect(cx + s * VF3.W / 2 * sc + (s < 0 ? -0.3 * sc : 0), 220, .3 * sc, 680);
  x.setLineDash([6, 6]); x.strokeStyle = hexA(col, .7); x.lineWidth = 1.5;
  for (const s of [-1, 1]) { const ex = cx + s * (VF3.W / 2 + .3) * sc; x.beginPath(); x.moveTo(ex, 220); x.lineTo(ex, 900); x.stroke(); }
  x.setLineDash([]);
  x.restore();
  // car
  const ca2 = a * E.out(P(t, 12.4, 13.2));
  drawCar(cx + shake, cy + (1 - E.out(P(t, 12.4, 13.4))) * 300, sc, 0, ca2, C.cyan);
  // turning arc
  const ta = P(t, 13.2, 14.4) * (1 - P(t, 14.8, 15.4));
  if (ta > 0) {
    x.save(); x.globalAlpha = a * (1 - P(t, 14.8, 15.4)); x.strokeStyle = C.mag; x.lineWidth = 2; x.setLineDash([10, 8]);
    const R = 4.5 * sc, ox = cx + (4.5 - VF3.W / 2) * sc * 0 + 3.9 * sc, oy = cy + VF3.WB / 2 * sc;
    x.beginPath(); x.arc(ox, oy, R, Math.PI, Math.PI + E.out(ta) * 1.2, false); x.stroke(); x.setLineDash([]);
    T('R 4.50 m', ox - R * .8, oy - R * .72, { f: FM, w: 700, size: 22, c: C.mag, a: x.globalAlpha * P(t, 13.8, 14.2) });
    x.restore();
  }
  // dimension lines
  const dy = cy + VF3.L / 2 * sc + 50;
  dimLine(cx - VF3.W / 2 * sc, dy, cx + VF3.W / 2 * sc, dy, '1.68 m', C.cyan, a * P(t, 13.0, 13.5));
  dimLine(cx + VF3.W / 2 * sc + 70, cy - VF3.L / 2 * sc, cx + VF3.W / 2 * sc + 70, cy + VF3.L / 2 * sc, '3.19 m', C.cyan, a * P(t, 13.2, 13.7) * (1 - P(t, 15, 15.5)), 0);
  dimLine(cx - aw / 2 * sc, 190, cx + aw / 2 * sc, 190, `ALLEY ${aw.toFixed(2)} m`, col, wa * P(t, 13.4, 14));
  // left copy
  kicker('02', 'ALLEY FIT', 120, 220, a);
  RT('VinFast VF 3', 116, 310, P(t, 12.4, 13.2), { size: 72, w: 800, ls: -1 }, P(t, 19.6, 20.2));
  const spec = [['WIDTH', '1.68 m'], ['LENGTH', '3.19 m'], ['TURN RADIUS', '4.50 m'], ['CLEARANCE / WALL', '0.30 m']];
  spec.forEach(([k, v], i) => {
    const q = E.out(P(t, 13.0 + i * .18, 13.5 + i * .18)) * a;
    x.save(); x.globalAlpha = q; x.fillStyle = hexA(C.cyan, .25); x.fillRect(120, 352 + i * 54, 520, 1); x.restore();
    T(k, 120, 392 + i * 54, { f: FM, w: 500, size: 20, ls: 3, c: C.dim, a: q });
    T(v, 640, 392 + i * 54, { f: FM, w: 700, size: 26, al: 'right', c: C.white, a: q });
  });
  const nq = a * E.out(P(t, 14.0, 14.5));
  T('NEEDS ≥ 2.28 m CLEAR WIDTH', 120, 610, { f: FM, w: 700, size: 24, ls: 2, c: C.cyan, a: nq, glow: C.cyan, gb: 14 });
  const label = { ok: 'FITS', tight: 'TIGHT', no: "DOESN'T FIT" }[fitS];
  const flash = fitS === 'no' ? 1 + .5 * Math.max(0, Math.sin(t * 22)) * (1 - P(t, 18.6, 19.5)) : 1;
  chip(label, 120, 700, col, a * P(t, 14.4, 14.8) * Math.min(1, flash), 34);
  T(fitS === 'no' ? 'Standard GPS would send you in anyway.' : 'Width, turn-in and the way back out.', 120, 770, { f: FB, w: 400, size: 26, c: C.dim, a: a * P(t, 14.6, 15.2) });
}

function sceneScan(t, c) {
  const a = win(t, 20.2, 28.3, .4, .5);
  // naive route
  const nf = E.io(P(t, 20.4, 22.6)) * BLK[2];
  const blocked = t > 22.6;
  const na = 1 - P(t, 26.5, 27.6);
  if (na > 0 && t > 20.3) {
    x.save(); x.globalAlpha = na;
    strokeRoute(R_NAIVE, 0, Math.min(nf, BLK[2]), c, '#ffffff', 4, 4, [14, 10], -t * 60);
    if (blocked) strokeRoute(R_NAIVE, BLK[2], 1, c, C.red, 3, 3, [4, 10], -t * 30);
    x.restore();
    const [hx, hy] = ptAt(R_NAIVE, nf); const [sx, sy] = w2s(c, hx, hy);
    if (!blocked) dot(sx, sy, 9, '#fff', na);
    const lp = P(t, 20.8, 21.3) * na;
    if (lp > 0 && !blocked) { T('STANDARD GPS ROUTE', sx + 22, sy - 18, { f: FM, w: 700, size: 18, ls: 3, c: '#fff', a: lp }); }
    if (blocked) {
      const [bx, by] = w2s(c, BLK[0], BLK[1]); const bp = P(t, 22.6, 23.4);
      for (let i = 0; i < 3; i++) ring(bx, by, 10 + E.out(P(t, 22.6 + i * .25, 23.8 + i * .25)) * 140, C.red, (1 - P(t, 22.6 + i * .25, 23.8 + i * .25)) * na, 3);
      x.save(); x.globalAlpha = na; x.strokeStyle = C.red; x.lineWidth = 6; x.lineCap = 'round'; x.shadowColor = C.red; x.shadowBlur = 25;
      const s = 20 * E.back(cl(bp * 2)); x.beginPath(); x.moveTo(bx - s, by - s); x.lineTo(bx + s, by + s); x.moveTo(bx + s, by - s); x.lineTo(bx - s, by + s); x.stroke(); x.restore();
      chip('STUCK · 1.9 m CLEAR', bx + 40, by - 30, C.red, na * E.out(P(t, 22.8, 23.2)), 20);
    }
  }
  // scanner
  const sp = P(t, 23.4, 27.4);
  if (sp > 0 && sp < 1) {
    const [dx, dy] = w2s(c, D.dst[0], D.dst[1]); const rad = scanR(t) * c.s;
    ring(dx, dy, rad, C.lime, .9 * (1 - sp), 2.5);
    ring(dx, dy, rad * .96, C.lime, .25 * (1 - sp), 12);
    x.save(); x.globalCompositeOperation = 'lighter';
    const ang = t * 5.2; const g = x.createConicGradient(ang, dx, dy);
    g.addColorStop(0, 'rgba(166,255,61,.22)'); g.addColorStop(.08, 'rgba(166,255,61,0)'); g.addColorStop(1, 'rgba(166,255,61,0)');
    x.fillStyle = g; x.beginPath(); x.arc(dx, dy, rad, 0, 7); x.fill(); x.restore();
  }
  // width labels
  for (const w of LABELS) {
    const q = E.back(P(t, scanAt(w), scanAt(w) + .35)) * (1 - P(t, 28, 28.5));
    if (q <= 0) continue;
    const mp = ptAt(w, .5); const [sx, sy] = w2s(c, mp[0], mp[1]);
    if (sx < 60 || sx > W - 60 || sy < 60 || sy > H - 60) continue;
    const col = FITC[w.fit];
    x.save(); x.translate(sx, sy); x.scale(q, q);
    const o = { f: FM, w: 700, size: 16, c: '#03050b' }; const tw = measure(w.w.toFixed(1) + ' m', o) + 14;
    x.fillStyle = col; x.shadowColor = col; x.shadowBlur = 16; x.beginPath(); x.roundRect(-tw / 2, -13, tw, 24, 3); x.fill(); x.shadowBlur = 0;
    T(w.w.toFixed(1) + ' m', 0, 5, { ...o, al: 'center' }); x.restore();
  }
  // copy
  kicker('03', 'EVERY ALLEY, MEASURED', 120, 210, a);
  RT('Evidence, not guesses.', 116, 296, P(t, 23.3, 24.2), { size: 68, w: 800, ls: -1 }, P(t, 27.6, 28.2));
  T('Field tape · parcel gaps · listings · OSM — each with its source tier.', 120, 346, { f: FB, w: 400, size: 24, c: C.dim, a: a * P(t, 24, 24.6) });
  const la = a * E.out(P(t, 23.6, 24.2));
  panel(W - 420, 150, 340, 230, la);
  [['FITS', C.lime], ['TIGHT', C.amber], ["DOESN'T FIT", C.red], ['UNKNOWN · NO PROOF', C.unk]].forEach(([s, col], i) => {
    const q = la * E.out(P(t, 23.8 + i * .12, 24.3 + i * .12));
    x.save(); x.globalAlpha = q; x.fillStyle = col; x.shadowColor = col; x.shadowBlur = 12; x.fillRect(W - 390, 200 + i * 48, 36, 5); x.restore();
    T(s, W - 338, 208 + i * 48, { f: FM, w: 600, size: 18, ls: 2, c: C.white, a: q });
  });
  T('VF 3 · NEED 2.28 m', W - 390, 186 - 6, { f: FM, w: 500, size: 13, ls: 3, c: C.dim, a: 0 });
}
function scanR(t) { return E.out(P(t, 23.4, 27.4)) * 2600; }
function scanAt(w) { // time when scanner reaches way
  const r = w.dD; // invert scanR: r = out(p)*2600 → p = 1 - cbrt(1 - r/2600)
  const p = 1 - Math.cbrt(1 - Math.min(r / 2600, .999)); return 23.4 + p * 4;
}

function sceneFlood(t, c) {
  const a = win(t, 28.3, 36.2, .5, .5);
  if (a <= 0) return;
  // cameras
  for (let i = 0; i < D.cams.length; i++) {
    const [cx_, cy_] = D.cams[i]; const ti = 29 + rnd(i * 3.1) * 2.2; const q = E.back(P(t, ti, ti + .4)) * a;
    if (q <= 0) continue;
    const [sx, sy] = w2s(c, cx_, cy_); if (sx < -20 || sx > W + 20 || sy < -20 || sy > H + 20) continue;
    x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = q;
    const hot = rnd(i * 7.7) < .12; const col = hot ? C.water : C.amber;
    x.strokeStyle = col; x.lineWidth = 1.5; x.shadowColor = col; x.shadowBlur = 10;
    x.strokeRect(sx - 4, sy - 4, 8, 8);
    if (hot) { const ph = ((t - ti) * .8 + rnd(i)) % 1; x.globalAlpha = q * (1 - ph); x.beginPath(); x.arc(sx, sy, Math.max(0, 6 + ph * 26), 0, 7); x.stroke(); }
    x.restore();
  }
  // flood records ripple
  for (let i = 0; i < D.floods.length; i++) {
    const [fx, fy, cm] = D.floods[i]; const ti = 30.3 + rnd(i * 1.3) * 2.5; if (t < ti) continue;
    const [sx, sy] = w2s(c, fx, fy); if (sx < -50 || sx > W + 50 || sy < -50 || sy > H + 50) continue;
    const r0 = 4 + Math.min(cm, 60) * .45;
    x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalCompositeOperation = 'lighter';
    const g = x.createRadialGradient(sx, sy, 0, sx, sy, r0 * 2.2 * E.out(P(t, ti, ti + .8)) + 1);
    g.addColorStop(0, hexA(C.water, .55 * a)); g.addColorStop(1, hexA(C.water, 0)); x.fillStyle = g;
    x.beginPath(); x.arc(sx, sy, r0 * 2.2, 0, 7); x.fill();
    for (let k = 0; k < 2; k++) { const ph = ((t - ti) * .6 + k * .5) % 1; x.globalAlpha = a * (1 - ph) * .7; x.strokeStyle = C.water; x.lineWidth = 1.5; x.beginPath(); x.arc(sx, sy, r0 + ph * r0 * 3, 0, 7); x.stroke(); }
    x.restore();
  }
  // copy
  kicker('04', 'WATER, OVER YOUR WHOLE STAY', 120, 210, a);
  RT('Triều cường. Mưa. Camera.', 116, 296, P(t, 29.0, 30.0), { size: 68, w: 800, ls: -1 }, P(t, 35.5, 36.1));
  T('Checked on the way in, while you\'re parked, and on the way out.', 120, 346, { f: FB, w: 400, size: 24, c: C.dim, a: a * P(t, 29.8, 30.4) });
  // AI camera callout
  const ca = a * E.out(P(t, 31.2, 31.7));
  if (ca > 0) {
    const i = D.cams.findIndex((p, k) => rnd(k * 7.7) < .12 && Math.abs(p[0] + 300) < 1500 && Math.abs(p[1]) < 900);
    const [sx, sy] = w2s(c, D.cams[i][0], D.cams[i][1]);
    x.save(); x.globalAlpha = ca; x.strokeStyle = C.water; x.lineWidth = 1.5; x.beginPath(); x.moveTo(sx, sy); x.lineTo(sx + 60, sy - 60); x.lineTo(sx + 120, sy - 60); x.stroke(); x.restore();
    panel(sx + 120, sy - 130, 330, 120, ca, C.water);
    typed('CAM TTH-406 · AI READ', sx + 140, sy - 96, P(t, 31.5, 32.2), { f: FM, w: 600, size: 15, ls: 2, c: C.water }, false);
    typed('standing water ~12 cm', sx + 140, sy - 64, P(t, 32.0, 32.8), { f: FM, w: 700, size: 20, c: C.white });
    typed('2 frames · 13 s apart', sx + 140, sy - 36, P(t, 32.5, 33.1), { f: FM, w: 500, size: 15, c: C.dim }, false);
  }
  tideChart(t, a);
}
function tideChart(t, a0) {
  const a = a0 * E.out(P(t, 30.4, 31.0)); if (a <= 0) return;
  const px = 420, py = 760, pw = 1080, ph = 230;
  panel(px, py, pw, ph, a, C.water);
  T('PHÚ AN · SÔNG SÀI GÒN · TIDE (m)', px + 24, py + 32, { f: FM, w: 600, size: 14, ls: 3, c: C.water, a });
  const ix = px + 30, iw = pw - 60, iy = py + 50, ih = ph - 70;
  const highs = D.tide.slice(0, 10), n = highs.length;
  const lv = v => iy + ih - (v - 1.25) / (1.75 - 1.25) * ih;
  // alarm lines
  [[1.4, 'BĐ1'], [1.5, 'BĐ2'], [1.6, 'BĐ3']].forEach(([v, s], i) => {
    const q = a * P(t, 30.8 + i * .1, 31.2 + i * .1);
    x.save(); x.globalAlpha = q * .7; x.setLineDash([4, 6]); x.strokeStyle = i === 2 ? C.red : C.amber; x.lineWidth = 1; x.beginPath(); x.moveTo(ix, lv(v)); x.lineTo(ix + iw, lv(v)); x.stroke(); x.restore();
    T(s, ix + iw + 4, lv(v) + 4, { f: FM, w: 600, size: 11, c: i === 2 ? C.red : C.amber, a: q });
  });
  const curve = u => { const k = u * (n - 1); const i0 = Math.floor(k), fr = k - i0; const h0 = highs[Math.min(i0, n - 1)], h1 = highs[Math.min(i0 + 1, n - 1)];
    const env = lerp(h0, h1, fr); return lerp(1.22, env, Math.pow(.5 + .5 * Math.cos(fr * 2 * Math.PI), 1.6)); };
  const dp = E.io(P(t, 30.8, 33.0));
  x.save(); x.beginPath(); x.rect(ix, iy - 10, iw, ih + 10); x.clip();
  // fill
  x.beginPath(); x.moveTo(ix, iy + ih);
  for (let k = 0; k <= 300 * dp; k++) { const u = k / 300; x.lineTo(ix + u * iw, lv(curve(u))); }
  x.lineTo(ix + dp * iw, iy + ih); x.closePath();
  const g = x.createLinearGradient(0, iy, 0, iy + ih); g.addColorStop(0, hexA(C.water, .45 * a)); g.addColorStop(1, hexA(C.water, 0)); x.fillStyle = g; x.fill();
  x.beginPath(); for (let k = 0; k <= 300 * dp; k++) { const u = k / 300; k ? x.lineTo(ix + u * iw, lv(curve(u))) : x.moveTo(ix, lv(curve(0))); }
  x.globalAlpha = a; x.strokeStyle = C.water; x.lineWidth = 2.5; x.shadowColor = C.water; x.shadowBlur = 14; x.stroke();
  x.restore();
  // dwell window
  const wp = E.exio(P(t, 33.0, 34.0)); if (wp <= 0) return;
  const pk = highs.indexOf(Math.max(...highs)), u0 = (pk - .25) / (n - 1), u1 = (pk + .25) / (n - 1);
  const wx0 = ix + u0 * iw, wx1 = ix + lerp(u0, u1, wp) * iw;
  x.save(); x.globalAlpha = a; x.fillStyle = hexA(C.mag, .16); x.fillRect(wx0, iy - 6, wx1 - wx0, ih + 6);
  x.strokeStyle = C.mag; x.lineWidth = 2; x.strokeRect(wx0, iy - 6, wx1 - wx0, ih + 6); x.restore();
  T('YOUR STAY', wx0 + 8, iy + 12, { f: FM, w: 700, size: 13, ls: 3, c: C.mag, a: a * P(t, 33.6, 34) });
  const pkx = ix + pk / (n - 1) * iw, pky = lv(highs[pk]);
  const q = P(t, 34.0, 34.4);
  dot(pkx, pky, 7, C.red, a * q); ring(pkx, pky, 7 + 30 * ((t * 1.3) % 1), C.red, a * q * (1 - (t * 1.3) % 1), 2);
  chip(`${highs[pk].toFixed(2)} m > BĐ3`, pkx + 18, pky - 4, C.red, a * E.out(q), 16);
}

function sceneLegal(t, c) {
  const a = win(t, 36.2, 40.6, .4, .5);
  if (a <= 0) return;
  // sign stamps along arterials near the stop
  SIGNS.forEach((w, i) => {
    const ti = 37.0 + i * .18, q = E.back(P(t, ti, ti + .35)) * a; if (q <= 0) return;
    setCam(c); x.save(); x.globalCompositeOperation = 'lighter'; x.strokeStyle = C.red; x.globalAlpha = q * .8; x.lineCap = 'round';
    x.lineWidth = 7 / c.s; x.beginPath(); x.moveTo(w.p[0], w.p[1]); for (let k = 2; k < w.p.length; k += 2) x.lineTo(w.p[k], w.p[k + 1]); x.stroke(); x.restore(); x.setTransform(1, 0, 0, 1, 0, 0);
    const mp = ptAt(w, .5); const [sx, sy] = w2s(c, mp[0], mp[1]);
    x.save(); x.translate(sx, sy); x.scale(q, q); x.globalAlpha = Math.min(1, a);
    x.fillStyle = '#1d5cff'; x.strokeStyle = C.red; x.lineWidth = 6; x.shadowColor = C.red; x.shadowBlur = 20;
    x.beginPath(); x.arc(0, 0, 22, 0, 7); x.fill(); x.stroke(); x.shadowBlur = 0;
    x.beginPath(); x.moveTo(-15, -15); x.lineTo(15, 15); x.moveTo(15, -15); x.lineTo(-15, 15); x.stroke(); x.restore();
  });
  // valid stop point
  const [sx, sy] = w2s(c, D.stop[0], D.stop[1]); const q = P(t, 38.4, 38.9) * a;
  for (let k = 0; k < 3; k++) { const ph = ((t - 38.4) * .7 + k / 3) % 1; ring(sx, sy, 12 + ph * 70, C.lime, q * (1 - ph), 2); }
  dot(sx, sy, 10, C.lime, q);
  chip('LEGAL STOP', sx + 26, sy - 22, C.lime, q * E.out(P(t, 38.7, 39.1)), 18);
  kicker('05', 'LEGAL TO STOP?', 120, 210, a);
  RT('Luật 36/2024 · Điều 18', 116, 296, P(t, 36.6, 37.5), { size: 68, w: 800, ls: -1 }, P(t, 40.0, 40.5));
  T('Signs, local lists and the law — every answer carries its citation.', 120, 346, { f: FB, w: 400, size: 24, c: C.dim, a: a * P(t, 37.2, 37.8) });
}

function sceneAnswer(t, c) {
  const a = 1 - P(t, 48.6, 49.4); if (t < 40.4 || a <= 0) return;
  const f = carF(t);
  // car route comet
  strokeRoute(R_CAR, 0, f, c, C.cyan, 5, 5);
  strokeRoute(R_CAR, Math.max(0, f - .06), f, c, '#ffffff', 5, 3);
  const [hx, hy, ang] = ptAt(R_CAR, f), [sx, sy] = w2s(c, hx, hy);
  if (f < 1) {
    x.save(); x.translate(sx, sy); x.rotate(ang + c.r); x.globalAlpha = a; x.fillStyle = '#fff'; x.shadowColor = C.cyan; x.shadowBlur = 30;
    x.beginPath(); x.moveTo(16, 0); x.lineTo(-10, -10); x.lineTo(-5, 0); x.lineTo(-10, 10); x.closePath(); x.fill(); x.restore();
    const cq = P(t, 41.0, 41.5) * (1 - P(t, 44.6, 45.0));
    T(`${Math.round(f * D.carLen).toLocaleString('en-US')} m · ARTERIALS ONLY · DRY`, sx + 26, sy - 22, { f: FM, w: 700, size: 16, ls: 2, c: C.cyan, a: cq });
  }
  // stop drop
  const [px, py] = w2s(c, D.stop[0], D.stop[1]); const dq = P(t, 45.0, 45.5);
  if (dq > 0) {
    for (let k = 0; k < 3; k++) ring(px, py, 10 + E.out(P(t, 45.1 + k * .15, 46.2 + k * .15)) * 120, C.lime, (1 - P(t, 45.1 + k * .15, 46.2 + k * .15)) * a, 3);
    const yy = py - 40 - (1 - E.back(dq)) * 120;
    x.save(); x.globalAlpha = a * dq; x.fillStyle = C.lime; x.shadowColor = C.lime; x.shadowBlur = 30;
    x.beginPath(); x.moveTo(px, py - 4); x.lineTo(px - 18, yy + 10); x.arc(px, yy, 22, Math.PI * .8, Math.PI * .2); x.closePath(); x.fill(); x.restore();
    T('P', px, yy + 10, { size: 28, w: 900, al: 'center', c: '#03050b', a: a * dq });
  }
  // walk
  const wf = E.io(P(t, WALK_T0, WALK_T1));
  if (wf > 0) {
    strokeRoute(R_WALK, 0, wf, c, C.mag, 4, 4, [2, 12], -t * 40);
    const [wx, wy] = ptAt(R_WALK, wf); const [s2x, s2y] = w2s(c, wx, wy); dot(s2x, s2y, 7, '#fff', a);
  }
  const [dx, dy] = w2s(c, D.dst[0], D.dst[1]); const pq = P(t, 45.6, 46.0);
  if (pq > 0) {
    for (let k = 0; k < 2; k++) { const ph = ((t - 45.6) * .8 + k / 2) % 1; ring(dx, dy, 10 + ph * 50, C.mag, a * pq * (1 - ph), 2); }
    dot(dx, dy, 9, C.mag, a * pq);
    T('ĐÍCH · DOOR', dx + 22, dy + 6, { f: FM, w: 700, size: 16, ls: 2, c: C.mag, a: a * pq });
  }
  // verdict card
  const vq = E.expo(P(t, 46.2, 47.0)) * a;
  if (vq > 0) {
    const vx = W - 640 + (1 - vq) * 200, vy = 230;
    panel(vx, vy, 560, 560, vq, C.lime);
    T('ARRIVAL PLAN · VF 3', vx + 36, vy + 52, { f: FM, w: 600, size: 15, ls: 4, c: C.lime, a: vq });
    RT('Dừng tại P,', vx + 34, vy + 128, P(t, 46.5, 47.2), { size: 56, w: 900, ls: -1 });
    RT(`đi bộ ${D.walkLen} m`, vx + 34, vy + 196, P(t, 46.7, 47.4), { size: 56, w: 900, ls: -1, c: C.lime, glow: C.lime, gb: 26 });
    T(`~${Math.max(1, Math.round(D.walkLen / 70))} phút · park and walk the last stretch`, vx + 36, vy + 240, { f: FB, w: 400, size: 22, c: C.dim, a: vq * P(t, 47.2, 47.6) });
    [['Alley Fit', 'arterials + verified alleys only'], ['Flood', 'dry: in · parked · out'], ['Legal stop', 'Luật 36/2024 Đ.18 · cited'], ['Way out', 'no reversing into a dead end']].forEach(([k, v], i) => {
      const q = E.out(P(t, 47.3 + i * .15, 47.7 + i * .15)) * vq, yy = vy + 310 + i * 58;
      x.save(); x.globalAlpha = q; x.strokeStyle = C.lime; x.lineWidth = 3.5; x.lineCap = 'round'; x.shadowColor = C.lime; x.shadowBlur = 12;
      x.beginPath(); x.moveTo(vx + 40, yy - 8); x.lineTo(vx + 50, yy + 2); x.lineTo(vx + 68, yy - 18); x.stroke(); x.restore();
      T(k, vx + 88, yy, { size: 24, w: 700, c: C.white, a: q });
      T(v, vx + 524, yy, { f: FM, w: 500, size: 15, c: C.dim, al: 'right', a: q });
    });
  }
  kicker('06', 'THE ANSWER', 120, 210, a * P(t, 40.6, 41.0));
}

function sceneOutro(t) {
  if (t < 49) return;
  const a = 1 - P(t, 55.0, 56);
  x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.fillStyle = `rgba(2,4,10,${.55 * E.out(P(t, 49.4, 51))})`; x.fillRect(0, 0, W, H); x.restore();
  const p = P(t, 49.6, 50.8);
  const g = Math.max(0, 1 - Math.abs(t - 50.9) / .1) + Math.max(0, 1 - Math.abs(t - 52.6) / .08) * .7;
  x.save(); x.globalAlpha = a;
  const sc = 1 + .03 * P(t, 49.6, 56);
  x.translate(960, 520); x.scale(sc, sc); x.translate(-960, -520);
  RT('VÀO ĐƯỢC', 960, 560, p, { size: 210, w: 900, ls: -4, al: 'center', c: C.white, glow: C.cyan, gb: 60, stagger: .08 });
  if (g > .02) glitchText('VÀO ĐƯỢC', 960, 560, { size: 210, w: 900, ls: -4, al: 'center', c: 'rgba(0,0,0,0)' }, g);
  x.restore();
  const lw = 900 * E.exio(P(t, 50.6, 51.6));
  x.save(); x.globalAlpha = a; x.fillStyle = C.cyan; x.shadowColor = C.cyan; x.shadowBlur = 20; x.fillRect(960 - lw / 2, 620, lw, 2); x.restore();
  RT('Xe bạn vào được, và ra được, không?', 960, 690, P(t, 51.0, 52.0), { size: 40, w: 600, al: 'center', c: C.white, a, stagger: .02 });
  T('A CAR ACCESS LAYER FOR HCMC · ALLEY FIT · FLOOD · STOP LEGALITY', 960, 750, { f: FM, w: 500, size: 17, ls: 4, al: 'center', c: C.cyan, a: a * P(t, 51.8, 52.4) });
  T('MLAI HACKATHON 2026  ·  TASCO × GOONG TRACK', 960, 960, { f: FM, w: 600, size: 18, ls: 6, al: 'center', c: C.dim, a: a * P(t, 52.4, 53.0) });
}

// ---------- frame
const CUTS = [6, 12, 20, 28, 36, 40, 49];
function render(t) {
  x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.shadowBlur = 0;
  x.fillStyle = C.bg; x.fillRect(0, 0, W, H);
  const bgG = x.createRadialGradient(960, 540, 0, 960, 540, 1100); bgG.addColorStop(0, '#0a1430'); bgG.addColorStop(1, 'rgba(3,5,11,0)');
  x.fillStyle = bgG; x.fillRect(0, 0, W, H);
  const c = camAt(t); CAM = c;
  // map visibility
  let mapA = t < 6 ? .35 * E.out(P(t, 2.0, 4.5)) * (1 - P(t, 4.8, 5.6)) + E.out(P(t, 5.6, 6.2)) : 1;
  const reveal = w => t >= 11 ? 1 : E.out(P(t, 2.0 + Math.max(0, (w.dC - 150)) / 3600 * 6.5 + w.r * .4, 2.6 + Math.max(0, (w.dC - 150)) / 3600 * 6.5 + w.r * .4 + .9));
  const fit = w => {
    if (t >= 49) return 1;
    if (t < 23.4) return 0;
    if (t >= 28.6 && t < 36.2) return 1;
    const s = scanAt(w); return t < s ? 0 : t < s + .25 ? .5 : 1;
  };
  drawGrid(c, mapA * (t < 6 ? .4 : 1));
  const dimA = t >= 28.6 && t < 36.2 ? .35 : t >= 40 && t < 49 ? .45 : null;
  drawMap(t, c, { reveal, fit, alpha: mapA * (t >= 28.6 && t < 36.2 ? .7 : 1), dimAlleys: dimA });
  drawPackets(t, c, mapA * (t < 20 || t > 49 ? 1 : .5) * (t < 6 ? 0 : 1));
  x.setTransform(1, 0, 0, 1, 0, 0);
  const scrim = (t >= 6 && t < 12.4) || (t >= 20 && t < 40.6) ? 1 : 0;
  if (scrim) { const sg = x.createLinearGradient(0, 0, 1000, 0); sg.addColorStop(0, 'rgba(3,5,11,.75)'); sg.addColorStop(1, 'rgba(3,5,11,0)'); x.fillStyle = sg; x.fillRect(0, 0, 1000, H); }
  if (t < 6.2) sceneIntro(t);
  if (t >= 6 && t < 12.5) sceneCity(t);
  if (t >= 12 && t < 20.5) sceneCar(t);
  if (t >= 20 && t < 28.6) sceneScan(t, c);
  if (t >= 28 && t < 36.5) sceneFlood(t, c);
  if (t >= 36 && t < 40.8) sceneLegal(t, c);
  if (t >= 40 && t < 49.5) sceneAnswer(t, c);
  sceneOutro(t);
  x.setTransform(1, 0, 0, 1, 0, 0);
  hud(t, c, E.out(P(t, 6.0, 6.8)) * (1 - P(t, 49, 50)));
  // cut flashes + glitch slices
  for (const ct of CUTS) {
    const d = t - ct; if (d < -0.05 || d > .35) continue;
    const g = Math.max(0, 1 - Math.abs(d) / .2);
    x.save(); x.globalCompositeOperation = 'lighter'; x.fillStyle = `rgba(120,200,255,${.22 * g})`; x.fillRect(0, 0, W, H); x.restore();
    const n = 7;
    for (let i = 0; i < n; i++) {
      const sy = Math.floor(rnd(ct * 10 + i + Math.floor(t * 30)) * H), sh = 6 + rnd(i * 3 + ct) * 60, off = (rnd(i + ct * 7 + Math.floor(t * 30)) - .5) * 120 * g;
      x.drawImage(cv, 0, sy, W, sh, off, sy, W, sh);
    }
  }
  // post
  x.globalAlpha = 1; x.drawImage(VIG, 0, 0);
  x.globalAlpha = .55; x.drawImage(SCAN, 0, 0);
  x.globalAlpha = .045; x.drawImage(GRAIN[Math.floor(t * 24) % 4], 0, 0, W, H);
  x.globalAlpha = 1;
  const fade = Math.min(P(t, 0, .25), 1 - P(t, 55.4, 56));
  if (fade < 1) { x.fillStyle = `rgba(0,0,0,${1 - fade})`; x.fillRect(0, 0, W, H); }
}
window.render = render; window.TOTAL = TOTAL;
window.ready = Promise.all(['900 100px Montserrat', '800 100px Montserrat', '600 100px Montserrat', '400 30px "Fira Sans"', '500 20px "Source Code Pro"', '700 20px "Source Code Pro"', '600 20px "Source Code Pro"']
  .map(f => document.fonts.load(f, 'ĐƯỢC ạ'))).then(() => true);
if (!location.search.includes('render')) {
  const t0 = performance.now(); const q = new URLSearchParams(location.search); const st = +(q.get('t') || 0);
  window.ready.then(() => { const loop = () => { render((st + (performance.now() - t0) / 1000) % TOTAL); requestAnimationFrame(loop); }; loop(); });
}
