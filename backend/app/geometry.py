"""Alley-fit / turn / turnaround estimates from published vehicle specs.

Idealised low-speed kinematic (Ackermann / bicycle) model: full steering lock,
no tyre slip, instant steering, flat ground, vertical walls. Units: metres.
Published min turning radius is treated as the radius of the OUTER FRONT WHEEL
path (Toyota-style "tire" radius). If a maker quotes a body/wall radius the
results below are conservative.

Assumptions when a spec is not published (flagged in output):
  front track T = W - 0.28, front overhang = 0.45*(L-WB), rear = 0.55*(L-WB).
"""
import csv
import math
import sys


def _overhangs(L, WB, FOH=None, ROH=None):
    return (FOH if FOH is not None else 0.45 * (L - WB),
            ROH if ROH is not None else 0.55 * (L - WB))


def radii(W, L, WB, R, T=None, FOH=None, ROH=None, extra=0.0):
    """Return turning radii about the turn centre for rear-axle radius Rr >= Rr_min.

    extra: additional radius added to the rear axle (driver uses less than full lock).
    """
    T = T if T is not None else W - 0.28
    FOH, ROH = _overhangs(L, WB, FOH, ROH)
    Rr = math.sqrt(R * R - WB * WB) - T / 2 + extra          # rear-axle centre
    r_in = Rr - W / 2                                          # inner body side at rear axle
    r_out = math.hypot(Rr + W / 2, WB + FOH)                   # outer FRONT corner (front swing)
    r_tail = math.hypot(Rr + W / 2, ROH)                       # outer REAR corner (tail swing)
    return dict(Rr=Rr, r_in=r_in, r_out=r_out, r_tail=r_tail, side=Rr + W / 2,
                FOH=FOH, ROH=ROH, T=T)


def min_alley_for_turn_in(W, L, WB, R, street_A, c=0.3, **kw):
    """Min alley width B (wall-to-wall) to turn 90 deg from a street of width A into
    the alley in ONE forward arc (no reversing). Walls get clearance c.
    Searches rear-axle radii >= minimum (driver may use less lock)."""
    A = street_A - 2 * c
    best = math.inf
    for i in range(0, 400):
        g = radii(W, L, WB, R, extra=i * 0.02, **kw)
        yc = g["r_tail"] - A          # lowest admissible turn-centre height
        if yc > g["r_in"]:
            continue                  # street too narrow for this radius
        if yc >= 0:
            B = g["r_out"] - math.sqrt(g["r_in"] ** 2 - yc ** 2)
        else:
            B = max(g["side"], math.sqrt(max(g["r_out"] ** 2 - yc ** 2, 0))) - g["r_in"]
        best = min(best, B)
    return best + 2 * c


def uturn_one_go(W, L, WB, R, c=0.3, **kw):
    g = radii(W, L, WB, R, **kw)
    return g["r_out"] + g["r_tail"] + 2 * c


def body_corners(x, y, psi, W, FOH, ROH, WB):
    h = (math.cos(psi), math.sin(psi))
    n = (-math.sin(psi), math.cos(psi))
    pts = []
    for s in (-ROH, WB + FOH):
        for t in (-W / 2, W / 2):
            pts.append((x + s * h[0] + t * n[0], y + s * h[1] + t * n[1]))
    return pts


def body_center_offset(L, WB, FOH=None, ROH=None):
    """Forward offset from rear-axle pose to body-centre pose."""
    FOH, ROH = _overhangs(L, WB, FOH, ROH)
    return (WB + FOH - ROH) / 2


def _k_turn(W, L, WB, R, D, c, max_moves, step_deg, collect_poses, **kw):
    g = radii(W, L, WB, R, **kw)
    Rr, FOH, ROH = g["Rr"], g["FOH"], g["ROH"]
    lo, hi = c, D - c
    # heading north; start as far right as the tail swing of the first (left-lock) arc allows
    x, y, psi = min(hi - W / 2, hi - g["r_tail"] + Rr), 0.0, math.pi / 2
    target = 3 * math.pi / 2
    d = math.radians(step_deg)
    ys = []
    poses = [(x, y, psi)] if collect_poses else None

    def ok(px, py, pp):
        cs = body_corners(px, py, pp, W, FOH, ROH, WB)
        return all(lo - 1e-9 <= cx <= hi + 1e-9 for cx, _ in cs), cs

    if not ok(x, y, psi)[0]:
        return None, None, poses
    for move in range(1, max_moves + 1):
        forward = move % 2 == 1
        # forward: left lock (centre on left); reverse: right lock (centre on right)
        n = (-math.sin(psi), math.cos(psi)) if forward else (math.sin(psi), -math.cos(psi))
        cx, cy = x + Rr * n[0], y + Rr * n[1]
        progressed = False
        while psi < target:
            dx, dy = x - cx, y - cy
            cr, sr = math.cos(d), math.sin(d)
            nx, ny = cx + dx * cr - dy * sr, cy + dx * sr + dy * cr
            good, cs = ok(nx, ny, psi + d)
            if not good:
                break
            x, y, psi = nx, ny, psi + d
            ys.extend(p[1] for p in cs)
            if poses is not None:
                poses.append((x, y, psi))
            progressed = True
        if psi >= target:
            return move, (max(ys) - min(ys)) if ys else 0.0, poses
        if not progressed:
            return None, None, poses
    return None, None, poses


def k_turn(W, L, WB, R, D, c=0.3, max_moves=9, step_deg=0.25, **kw):
    """Simulate a multi-point turn. Returns (moves_needed, corridor_length_used) or (None, None)."""
    moves, length, _ = _k_turn(W, L, WB, R, D, c, max_moves, step_deg, False, **kw)
    return moves, length


def k_turn_path(W, L, WB, R, D, c=0.3, max_moves=9, step_deg=0.25, max_poses=120, **kw):
    """Simulate a turn and return a bounded sequence of (x, y, heading) poses for visualization."""
    if max_poses < 2:
        raise ValueError("max_poses must be at least 2")
    moves, length, poses = _k_turn(W, L, WB, R, D, c, max_moves, step_deg, True, **kw)
    if moves is None:
        return moves, length, []
    if len(poses) > max_poses:
        last = len(poses) - 1
        poses = [poses[round(i * last / (max_poses - 1))] for i in range(max_poses)]
    return moves, length, poses


def min_width_for_moves(W, L, WB, R, moves, c=0.3, **kw):
    """Smallest corridor width (scan 5 cm steps) from which EVERY wider corridor lets the
    greedy K-turn finish in <= `moves` moves (greedy policy is not monotonic, so we
    report the stable threshold). Returns (width, corridor length used at that width)."""
    widths = [round(math.hypot(L, W) + 2 * c + 0.05 * i, 2) for i in range(0, 260)]
    res = [k_turn(W, L, WB, R, D, c=c, **kw) for D in widths]
    stable = None
    for D, (m, used) in reversed(list(zip(widths, res))):
        if m is not None and m <= moves:
            stable = (D, used)
        else:
            break
    return stable if stable else (math.inf, None)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "vn_car_profiles.csv"
    c = 0.3
    print(f"clearance per wall c={c} m; widths are wall-to-wall metres")
    print(f"{'model':28s} {'W':>5s} {'R':>5s} {'r_in':>5s} {'r_out':>5s} "
          f"{'turnIn@A=4':>10s} {'@A=6':>6s} {'@A=8':>6s} {'Uturn1':>6s} "
          f"{'3pt':>5s} {'len3':>5s} {'5pt':>5s} {'diag':>5s}")
    for row in csv.DictReader(open(path, encoding="utf-8")):
        W, L, WB, R = (num(row.get(k)) for k in
                       ("width_mm", "length_mm", "wheelbase_mm", "min_turning_radius_m"))
        if not all((W, L, WB, R)):
            print(f"{row['brand'] + ' ' + row['model']:28s} missing spec")
            continue
        W, L, WB = W / 1000, L / 1000, WB / 1000
        T = num(row.get("track_front_mm"))
        kw = dict(T=T / 1000 if T else None)
        g = radii(W, L, WB, R, **kw)
        ti = [min_alley_for_turn_in(W, L, WB, R, A, c=c, **kw) for A in (4, 6, 8)]
        u1 = uturn_one_go(W, L, WB, R, c=c, **kw)
        k3, len3 = min_width_for_moves(W, L, WB, R, 3, c=c, **kw)
        k5, _ = min_width_for_moves(W, L, WB, R, 5, c=c, **kw)
        name = (row["brand"] + " " + row["model"])[:28]
        print(f"{name:28s} {W:5.2f} {R:5.2f} {g['r_in']:5.2f} {g['r_out']:5.2f} "
              f"{ti[0]:10.2f} {ti[1]:6.2f} {ti[2]:6.2f} {u1:6.2f} {k3:5.2f} "
              f"{(len3 or float('nan')):5.2f} {k5:5.2f} {math.hypot(L, W) + 2 * c:5.2f}")
