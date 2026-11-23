"""Bottom-fill pour channel: pour beside the model, fill from the base up.

Pouring from the top drapes silicone over the master and traps air on a
complex sculpt. The bottom-fill channel is a straight pipe standing on the
parting seam just outside the case, joined to it by a thin fin at every height.
At the bottom a gate opens into the cavity right above its floor, so the
silicone enters at the base and rises evenly around the model. The top funnel
(if on) becomes the riser and air escape.

The channel sits ON the parting seam - the same contoured surface the split
uses - so each half carries half of it: when the halves come apart the cured
sprue lifts out of two half-channels instead of being locked inside one half.
Its radius is its own setting: it does not depend on the silicone thickness.
"""

import math
import types

import bpy
import bmesh
from mathutils import Vector

from . import util


def seam_frame(mold, axis, props, parting=None, radial_center=None, flip=False):
    """Where the channel can go: a namespace with ``center``, the horizontal
    direction ``d`` along the seam it runs out on, the seam's normal ``n`` and
    ``point(t, z)`` - the point on the parting surface ``t`` out along ``d``
    from the centre at height ``z``. Two-piece split: either end of the seam
    (the side the model reaches out least, or the other with ``flip``); radial
    split: the first seam."""
    mn, mx = util.world_bbox(mold)
    multipart = int(getattr(props, "parts_count", 2)) >= 3
    if multipart:
        c = radial_center if radial_center is not None else (mn + mx) * 0.5
        center = Vector((c.x, c.y, 0.0))
        d = Vector((1.0, 0.0, 0.0))
        n = Vector((0.0, 1.0, 0.0))

        def point(t, z):
            return Vector((center.x + t, center.y, z))
        return types.SimpleNamespace(center=center, d=d, n=n, point=point,
                                     multipart=True, sides=(d,))
    ai = {'X': 0, 'Y': 1}[axis]
    h = next(i for i in range(3) if i != ai and i != 2)
    center = (mn + mx) * 0.5
    center.z = 0.0
    cap = (mx[ai] - mn[ai]) * 0.4
    off = max(min(getattr(props, "split_offset", 0.0), cap), -cap)
    if parting is not None:
        off = parting.off
    seam_flat = center[ai] + off
    n = Vector((0.0, 0.0, 0.0)); n[ai] = 1.0

    def make(sgn):
        d = Vector((0.0, 0.0, 0.0)); d[h] = sgn

        def point(t, z):
            p = center.copy()
            p[h] = center[h] + sgn * t
            p.z = z
            s = None
            if parting is not None:
                from . import split as _split
                s = _split.parting_at(parting, p[h], z)
            p[ai] = seam_flat if s is None else s
            return p
        return d, point

    sides = []
    for sgn in (1.0, -1.0):
        sides.append(make(sgn))
    # the side where the mold reaches out least gets the channel (shortest fin)
    reach = []
    for d, point in sides:
        r = _reach(mold, point, d, (mn.z + mx.z) * 0.5, (mx - mn).length + 10.0)
        reach.append(r if r is not None else 1e9)
    k = 0 if reach[0] <= reach[1] else 1
    if flip:
        k = 1 - k
    d, point = sides[k]
    return types.SimpleNamespace(center=center, d=d, n=n, point=point,
                                 multipart=False, ai=ai, h=h)


def _reach(obj, point, d, z, far):
    """How far out along ``d`` (from the frame centre) ``obj`` reaches at height
    z on the seam surface, or None. The ray starts on the surface far out, then
    once more from the surface position where it first hit (a contoured seam
    is not straight)."""
    t_hit = None
    o = point(far, z)
    for _ in range(3):
        hit, loc, _n, _i = obj.ray_cast(o, -d)
        if not hit:
            return t_hit
        t_new = far - (loc - o).dot(-d)
        if t_hit is not None and abs(t_new - t_hit) < 0.05:
            return t_new
        t_hit = t_new
        o = point(t_hit, z) + d * (far - t_hit)
    return t_hit


def _sweep(name, pts, r, coll, segs=32):
    """A closed round tube of radius ``r`` along the polyline ``pts`` (rings kept
    perpendicular to the line, capped at both ends)."""
    pts = [Vector(p) for p in pts]
    clean = [pts[0]]
    for p in pts[1:]:
        if (p - clean[-1]).length > 1e-4:
            clean.append(p)
    pts = clean
    if len(pts) < 2:
        return None
    tans = []
    for i in range(len(pts)):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        tans.append((b - a).normalized())
    ref = Vector((0.0, 0.0, 1.0))
    if abs(tans[0].dot(ref)) > 0.9:
        ref = Vector((1.0, 0.0, 0.0))
    u = tans[0].cross(ref).normalized()
    bm = bmesh.new()
    rings = []
    for i, p in enumerate(pts):
        t = tans[i]
        u = (u - t * u.dot(t))
        if u.length < 1e-6:
            u = t.orthogonal()
        u.normalize()
        v = t.cross(u)
        rings.append([bm.verts.new(p + (u * math.cos(2 * math.pi * k / segs)
                                        + v * math.sin(2 * math.pi * k / segs)) * r)
                      for k in range(segs)])
    for i in range(len(rings) - 1):
        for k in range(segs):
            kn = (k + 1) % segs
            bm.faces.new((rings[i][k], rings[i][kn], rings[i + 1][kn], rings[i + 1][k]))
    c0 = bm.verts.new(pts[0])
    c1 = bm.verts.new(pts[-1])
    for k in range(segs):
        kn = (k + 1) % segs
        bm.faces.new((rings[0][kn], rings[0][k], c0))
        bm.faces.new((rings[-1][k], rings[-1][kn], c1))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return util.new_mesh_object(name, bm, coll)


def _sheet(name, frame, rows, thick, coll):
    """A thin solid lying on the seam surface: for each height z in ``rows`` a
    span ``(z, t_in, t_out)`` along the seam, ``thick`` across it (half to each
    side, so the split halves it)."""
    K = 8
    bm = bmesh.new()
    grid = {}
    for side, sgn in ((0, -0.5), (1, 0.5)):
        for i, (z, t0, t1) in enumerate(rows):
            for k in range(K + 1):
                t = t0 + (t1 - t0) * k / K
                grid[(side, i, k)] = bm.verts.new(frame.point(t, z) + frame.n * (sgn * thick))
    m = len(rows)
    for i in range(m - 1):
        for k in range(K):
            bm.faces.new((grid[(0, i, k)], grid[(0, i, k + 1)],
                          grid[(0, i + 1, k + 1)], grid[(0, i + 1, k)]))
            bm.faces.new((grid[(1, i, k)], grid[(1, i + 1, k)],
                          grid[(1, i + 1, k + 1)], grid[(1, i, k + 1)]))
    for i in range(m - 1):                       # inner and outer edges
        for k in (0, K):
            bm.faces.new((grid[(0, i, k)], grid[(0, i + 1, k)],
                          grid[(1, i + 1, k)], grid[(1, i, k)]))
    for i in (0, m - 1):                         # bottom and top edges
        for k in range(K):
            bm.faces.new((grid[(0, i, k)], grid[(1, i, k)],
                          grid[(1, i, k + 1)], grid[(0, i, k + 1)]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return util.new_mesh_object(name, bm, coll)


def build_channel(mold, cavity, model, props, frame, floor_z, coll, open_below=False,
                  hug=False, wing=None, keep_out=()):
    """Weld the channel's pipe, fin and mouth onto the still-solid ``mold``
    (before the cavity is carved). ``floor_z`` is the lowest height the gate may
    open into the cavity (the cavity floor, a key plate's rim, a Locking Base's
    model base); ``open_below`` = the pipe runs on down through the open bottom.

    ``hug`` (Follow Model): instead of one straight pipe out at the mold's
    widest point, the pipe follows the case at every height, just outside it,
    so a model that narrows under an overhang doesn't get a wing as wide as
    the overhang all the way down. ``wing`` (a namespace: ``thickness``,
    ``ext``, ``bolt_r``, ``bolt_zs``, ``axis``) is the clamp wing when there is
    one: its channel side is then rebuilt at full thickness out to ``ext``
    beyond the pipe, so it can still be clamped (and keyed) over the pipe, and
    its bolt holes there are drilled again outboard of the pipe. ``keep_out``
    lists the top pour funnels as ``(x, y, radius)``: a Follow Model pipe that
    tops out near the middle of the model is moved out until its mouth stands
    clear of them.

    Returns the geometry the bore phase needs, or ``(None, reason)``."""
    mn, mx = util.world_bbox(mold)
    far = (mx - mn).length + 20.0
    bore_r = max(getattr(props, "channel_radius", 4.0), 1.0)
    jacket = props.box_style == 'POUR_BOX'
    wall = max(props.shell_wall if jacket else props.wall_thickness, 1.6)
    tube_out = bore_r + wall
    gap = getattr(props, "silicone_gap", props.wall_thickness)

    # The gate: just above the floor, where the cavity is at the seam.
    gate_z = floor_z + (bore_r if open_below else bore_r + 0.4)
    t_cav = None
    for _ in range(12):
        t_cav = _reach(cavity, frame.point, frame.d, gate_z, far)
        if t_cav is not None:
            break
        gate_z += 1.0
    if t_cav is None:
        return None, "the channel found no cavity to open into at the base"

    # How far out the mold reaches along the seam, height by height.
    mmn_z, mmx_z = util.world_bbox(model)[0].z, util.world_bbox(model)[1].z
    top = mmx_z + (gap if jacket else 0.0)
    z0 = gate_z - tube_out
    rows_z = []
    nz = max(int((top - z0) / 3.0), 4)
    for i in range(nz + 1):
        rows_z.append(z0 + (top - z0) * i / nz)
    reach = [(z, _reach(mold, frame.point, frame.d, z, far)) for z in rows_z]
    hits = [r for _z, r in reach if r is not None]
    if not hits:
        return None, "the channel found no mold wall on the seam"
    t_pipe = max(hits) + tube_out - 1.0           # welded 1 mm into the widest point
    shell_top = max((z for z, r in reach if r is not None), default=top)
    throat = max(top + 3.0, shell_top + 1.5)
    fh = max(getattr(props, "funnel_height", 12.0), 1.0)
    apex = throat + max(fh * 0.6, 6.0)
    mouth_r = max(bore_r * 1.8, bore_r + 3.0)
    fin_t = max(2.0 * wall, 3.0)

    path = edge_rows = None
    if hug:
        smooth = getattr(props, "channel_smooth", 0.5)
        path, shell = _hug_path(cavity, frame, z0, throat, far, wall, bore_r,
                                tube_out, smooth=smooth)
        if path is None:
            return None, "the channel found no cavity wall to follow"
        t_min = _clear_of(frame, path[-1][1], throat, mouth_r + wall, keep_out, far)
        if t_min > path[-1][1] + 1e-6:
            path, shell = _hug_path(cavity, frame, z0, throat, far, wall, bore_r,
                                    tube_out, smooth=smooth, t_top=t_min)
        t_pipe = _interp(path, gate_z)
        pipe_pts = [frame.point(t, z) for z, t in path]
        pipe = _tube("MF_chan", _stub(pipe_pts, tube_out), tube_out, coll)
        reach_at = dict(reach)
        rows, edge_rows = [], []
        for (z, t), (_z, sh) in zip(path, shell):
            if wing is not None:
                # ext is measured square to the pipe, round its bends too: the
                # edge is the outline of everything within tube_out + ext of
                # the pipe's centre line, or the wing beside a leaning or bent
                # pipe is too narrow for a key or a tongue
                e_ = tube_out + wing.ext
                t_out = t + e_
                for (za, ta), (zb, tb) in zip(path, path[1:]):
                    for f_ in (0.0, 0.25, 0.5, 0.75, 1.0):
                        zj, tj = za + (zb - za) * f_, ta + (tb - ta) * f_
                        dz_ = abs(zj - z)
                        if dz_ < e_:
                            t_out = max(t_out, tj + math.sqrt(e_ * e_ - dz_ * dz_))
                r = _nearest(reach, z)
                if r is not None:
                    t_out = max(t_out, r)
                edge_rows.append((z, t_out))
            else:
                t_out = t
            rows.append((z, min(sh - 3.0, t - 0.5), t_out))
        fin = _sheet("MF_chanfin", frame, rows,
                     wing.thickness if wing is not None else fin_t, coll)
    else:
        # Pipe along the seam, from under the gate to the throat.
        steps = max(int((throat - z0) / 4.0), 2)
        pipe_pts = [frame.point(t_pipe, z0 + (throat - z0) * i / steps)
                    for i in range(steps + 1)]
        pipe = _tube("MF_chan", _stub(pipe_pts, tube_out), tube_out, coll)
        # Fin: from the mold's surface out to the pipe at every height, so the
        # pipe is never a cantilever where the model narrows.
        rows = []
        for z, r in reach:
            # 3 mm into the case: between the sampled heights the surface may dip
            # in, and a fin that only touched it would leave slits (anything that
            # reaches into the cavity is carved away with it)
            t_in = (r - 3.0) if r is not None else t_pipe - tube_out
            t_in = min(t_in, t_pipe - 0.5)
            rows.append((z, t_in, t_pipe))
        rows.append((throat, t_pipe - tube_out, t_pipe))
        fin = _sheet("MF_chanfin", frame, rows, fin_t, coll)
    t_top = _interp(path, throat) if path else t_pipe
    # Mouth: a cup above the throat to pour into.
    tp = frame.point(t_top, throat)
    cup = util.add_cone("MF_chancup", Vector((tp.x, tp.y, (throat + apex) * 0.5)),
                        tube_out, mouth_r + wall, apex - throat, 'Z', coll, segments=48)
    # Collar: the gate runs from the pipe to the cavity through the fin, which
    # is thinner than the gate - without a tube round it the gate would cut
    # through the fin's faces and leak out sideways.
    n_c = max(int((t_pipe - t_cav) / 2.0), 2)
    collar_pts = [frame.point(t_pipe - (t_pipe - (t_cav - 1.0)) * i / n_c, gate_z)
                  for i in range(n_c + 1)]
    collar = _sweep("MF_chancollar", collar_pts, tube_out, coll)
    elbow = util.add_sphere("MF_chancollar", frame.point(t_pipe, gate_z), tube_out, coll,
                            subdiv=3)
    for part in (pipe, fin, cup, collar, elbow):
        if part is not None:
            util.boolean(mold, part, 'UNION')
            util.remove_object(part)
    geo = {"frame": frame, "t_pipe": t_pipe, "t_cav": t_cav, "gate_z": gate_z,
           "z0": z0, "throat": throat, "apex": apex, "bore_r": bore_r,
           "mouth_r": mouth_r, "open_below": open_below, "floor_z": floor_z,
           "cup": (tp.x, tp.y, mouth_r + wall), "reach": reach,
           "tube_out": tube_out, "hug": bool(hug), "path": path,
           "edge_rows": edge_rows, "bolts_redrilled": 0}
    if hug and wing is not None and wing.bolt_zs:
        geo["bolts_redrilled"] = _redrill_bolts(mold, geo, wing, coll)
    return geo, ""


def _interp(rows, z):
    """Linear read of ``(z, t)`` rows at ``z`` (clamped to their ends)."""
    if z <= rows[0][0]:
        return rows[0][1]
    for (z0, t0), (z1, t1) in zip(rows, rows[1:]):
        if z0 <= z <= z1:
            return t0 + (t1 - t0) * ((z - z0) / (z1 - z0) if z1 > z0 else 0.0)
    return rows[-1][1]


def _nearest(rows, z):
    """The value of the ``(z, t)`` row nearest ``z`` that has one, or None."""
    best = None
    for zz, t in rows:
        if t is not None and (best is None or abs(zz - z) < abs(best[0] - z)):
            best = (zz, t)
    return None if best is None else best[1]


def _hug_path(cavity, frame, z0, throat, far, wall, bore_r, tube_out, step=2.0,
              smooth=0.5, t_top=None):
    """The Follow Model pipe's axis: ``(z, t)`` every ``step`` mm from ``z0`` up
    to the throat, just outside the case - the cavity's reach plus the wall is
    the case's outside there, and the bore sits a little beyond it. Each height
    takes the widest case within a bore's radius above and below, so the bore
    never cuts into a ledge it passes under (a mushroom's cap). Heights with no
    cavity on the seam (above the top, below the floor) take the nearest that
    has one.

    ``smooth`` (0 to 1, the Smoothing setting) limits how sharply the pipe
    may bend: it may lean at most ``smooth_angle(smooth)`` from vertical, and
    where the case changes faster the pipe is moved OUT - never in - until it
    doesn't (the least pipe that stays outside the case and leans no more).

    The last stretch below the throat (a tube's radius and 2 mm) runs straight
    up, at least ``t_top`` out: the mouth is an upright cup on a flat base,
    and a pipe arriving at a lean left a gap under it that the bore cut open.

    Also returns the case's own outline, ``(z, t)``. ``(None, None)`` if the
    seam never meets the cavity."""
    n = max(int((throat - z0) / step), 2)
    zs = [z0 + (throat - z0) * i / n for i in range(n + 1)]
    raw = [(z, _reach(cavity, frame.point, frame.d, z, far)) for z in zs]
    if all(t is None for _z, t in raw):
        return None, None
    shell = [(z, (t if t is not None else _nearest(raw, z)) + wall) for z, t in raw]
    win = bore_r + 1.0
    path = []
    for z, _t in shell:
        widest = max(t for zz, t in shell if abs(zz - z) <= win)
        path.append((z, widest + bore_r + 0.6))
    # Bend limit: sweep up and down, pulling each point out to within the
    # allowed lean of its neighbour - the least smooth curve above the path.
    lean = math.tan(math.radians(smooth_angle(smooth)))
    t = [tt for _z, tt in path]
    run = [i for i, (z, _t) in enumerate(path) if z >= throat - tube_out - 2.0]
    for _ in range(3):
        top = max([t[i] for i in run] + ([t_top] if t_top is not None else []))
        for i in run:
            t[i] = top
        for order in (range(1, len(t)), range(len(t) - 2, -1, -1)):
            for i in order:
                j = i - 1 if order.step > 0 else i + 1
                dz = abs(path[i][0] - path[j][0])
                t[i] = max(t[i], t[j] - lean * dz)
        if max(t[i] for i in run) - min(t[i] for i in run) < 1e-6:
            break
    return [(z, tt) for (z, _o), tt in zip(path, t)], shell


def _clear_of(frame, t, z, cup_r, keep_out, far):
    """The least ``t`` (from ``t`` outward) at which a mouth of radius
    ``cup_r`` at height ``z`` stands 1.5 mm clear of every ``(x, y, r)`` in
    ``keep_out`` (the top pour funnels)."""
    while t < far:
        p = frame.point(t, z)
        if all(math.hypot(p.x - x, p.y - y) >= r + cup_r + 1.5 for x, y, r in keep_out):
            return t
        t += 0.5
    return t


def _stub(pts, r):
    """``pts`` with a short upright stub on the end: the mouth is an upright
    cup on a flat base at the throat, and a pipe arriving at any lean (a
    contoured seam leans it, so does Follow Model) left a wedge of gap under
    the cup's base that the bore then cut open."""
    top = Vector(pts[-1])
    return list(pts) + [Vector((top.x, top.y, top.z + r))]


def _tube(name, pts, r, coll, angle=15.0):
    """A round tube of radius ``r`` along a polyline that may bend sharply. One
    sweep folds over itself on the inside of a sharp bend (a hole in the
    wall once it is welded on), so the line is cut at every bend of more
    than ``angle`` degrees into nearly straight runs, each swept on its own,
    with a ball at each bend, all united into one solid."""
    pts = [Vector(p) for p in pts]
    bends = set(id(b) for b in _bends(pts, angle))
    runs, cur = [], [pts[0]]
    for p in pts[1:]:
        cur.append(p)
        if id(p) in bends:
            runs.append(cur)
            cur = [p]
    runs.append(cur)
    pieces = [_sweep(name, run, r, coll) for run in runs if len(run) >= 2]
    pieces += [util.add_sphere(name, p, r, coll, subdiv=3)
               for p in pts if id(p) in bends]
    pieces = [o for o in pieces if o is not None]
    if not pieces:
        return None
    tube = pieces[0]
    for o in pieces[1:]:
        util.boolean(tube, o, 'UNION')
        util.remove_object(o)
    return tube


def _bends(pts, angle=15.0):
    """The inner points of a polyline where it turns by more than ``angle``
    degrees."""
    out = []
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        u, v = b - a, c - b
        if u.length > 1e-6 and v.length > 1e-6 and u.angle(v) > math.radians(angle):
            out.append(b)
    return out


def smooth_angle(smooth):
    """The steepest lean from vertical (degrees) the Follow Model pipe may
    take at Smoothing ``smooth``: 80 at 0 (it follows nearly every step of
    the case), 45 at 0.5, 15 at 1 (a gentle sweep)."""
    s = min(max(float(smooth), 0.0), 1.0)
    return 80.0 - 70.0 * s if s <= 0.5 else 45.0 - 60.0 * (s - 0.5)


def _redrill_bolts(mold, geo, wing, coll):
    """Bolt holes on the channel's side of a Follow Model wing: the pipe and the
    rebuilt wing filled the ones drilled before, so drill each again outboard
    of the pipe, at the same height, where there is room. Returns how many."""
    fr = geo["frame"]
    made = 0
    for z in wing.bolt_zs:
        if abs(z - geo["gate_z"]) < geo["tube_out"] + wing.bolt_r + 0.5:
            continue
        edge = wing_edge(geo, z)
        if edge is None:
            continue
        lo, hi = _axis_span(geo, z - wing.bolt_r, z + wing.bolt_r)
        out = hi + geo["tube_out"]
        if edge - out < 2.0 * wing.bolt_r + 1.5:
            continue
        c = fr.point((out + edge) * 0.5, z)
        hole = util.add_cone("MF_wbolt", c, wing.bolt_r, wing.bolt_r,
                             wing.thickness + 2.4, wing.axis, coll)
        util.boolean(mold, hole, 'DIFFERENCE')
        util.remove_object(hole)
        made += 1
    return made


def axis_at(geo, z):
    """Where the channel's pipe axis is at height ``z``: ``t`` out along its
    seam from the frame's centre (constant for a straight pipe)."""
    path = geo.get("path")
    return _interp(path, z) if path else geo["t_pipe"]


def _axis_span(geo, z0, z1):
    """Nearest and furthest the pipe's axis comes between heights z0 and z1."""
    path = geo.get("path")
    if not path:
        return geo["t_pipe"], geo["t_pipe"]
    ts = [axis_at(geo, z0), axis_at(geo, z1)] + [t for z, t in path if z0 <= z <= z1]
    return min(ts), max(ts)


def wing_edge(geo, z):
    """Where the clamp wing on the channel's side ends at height ``z`` (``t``
    out along the seam from the frame's centre): for a straight pipe, how far
    the mold reached before the channel was welded on - the wing's own edge,
    which the pipe now hides; for Follow Model, the edge of the wing rebuilt
    over the pipe. The nearer of the two sampled heights round ``z`` (the
    wing may dip between them); None outside the sampled heights."""
    rows = [(zz, r) for zz, r in (geo.get("edge_rows") or geo.get("reach", ()))
            if r is not None]
    for (z0, r0), (z1, r1) in zip(rows, rows[1:]):
        if z0 <= z <= z1:
            return min(r0, r1)
    return None


def key_spot(geo, z, key_r, inset):
    """Where a wing key of radius ``key_r`` (its socket's, fit clearance
    included) sits on the channel's side at height ``z``: ``t`` out from the
    frame's centre, ``inset`` in from the wing's edge as on the other side,
    and off the pipe - inboard of a straight pipe, outboard of a Follow Model
    one (the wing over it). None where there is no room, or where the gate's
    tube crosses the wing (just above the floor)."""
    if abs(z - geo["gate_z"]) < geo["tube_out"] + key_r + 0.5:
        return None
    edge = wing_edge(geo, z)
    if edge is None:
        return None
    t = edge - inset
    lo, hi = _axis_span(geo, z - key_r, z + key_r)
    if geo.get("hug"):
        return t if t - key_r - 0.3 >= hi + geo["tube_out"] else None
    return min(t, lo - geo["tube_out"] - key_r - 0.3)


def bore_channel(mold, geo, coll):
    """Drill the channel after the cavity is carved: the pipe from the gate up
    through the mouth, and the gate along the seam into the cavity."""
    fr = geo["frame"]
    r = geo["bore_r"]
    gz = geo["gate_z"]
    tp = geo["t_pipe"]                     # the pipe's axis at the gate
    bottom = (geo["floor_z"] - 2.0) if geo["open_below"] else gz
    if geo.get("path"):
        pts = [fr.point(tp, bottom)] + [fr.point(t, z) for z, t in geo["path"]
                                         if bottom < z < geo["throat"]]
        pts.append(fr.point(axis_at(geo, geo["throat"]), geo["throat"]))
    else:
        steps = max(int((geo["throat"] - bottom) / 4.0), 2)
        pts = [fr.point(tp, bottom + (geo["throat"] - bottom) * i / steps)
               for i in range(steps + 1)]
    top_pt = fr.point(axis_at(geo, geo["throat"]), geo["throat"])
    pts.append(Vector((top_pt.x, top_pt.y, geo["apex"] + 1.0)))
    cutters = [_tube("MF_chanbore", pts, r, coll) if geo.get("path")
               else _sweep("MF_chanbore", pts, r, coll)]
    # the gate: from the pipe's axis in along the seam, 2 mm into the cavity
    t_end = geo["t_cav"] - 2.0
    n = max(int((tp - t_end) / 2.0), 2)
    gpts = [fr.point(tp - (tp - t_end) * i / n, gz) for i in range(n + 1)]
    cutters.append(_sweep("MF_chanbore", gpts, r, coll))
    elbow = util.add_sphere("MF_chanbore", fr.point(tp, gz), r, coll, subdiv=3)
    cutters.append(elbow)
    cupb = util.add_cone("MF_chanbore",
                         Vector((top_pt.x, top_pt.y, (geo["throat"] + geo["apex"] + 0.5) * 0.5)),
                         r, geo["mouth_r"], geo["apex"] + 0.5 - geo["throat"], 'Z', coll,
                         segments=48)
    cutters.append(cupb)
    for c in cutters:
        if c is not None:
            util.boolean(mold, c, 'DIFFERENCE')
            util.remove_object(c)
