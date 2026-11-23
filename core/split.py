"""Split the mold into two halves.

Default is a *contoured* parting surface that follows the model's mid-profile
(self-registering, MoldBoxer-style), with a flat-plane fallback if the contoured
cut produces anything invalid. Flat splits also get conical alignment keys.
"""

import math
import types

import bpy
import bmesh
from mathutils import Matrix, Vector

from . import util


def split_parts(mold, master, axis, props, coll, wall, radial_center=None,
                wing_bolt_zs=None, parting=None, wing_offset=0.0, wing_chan=None):
    """Split the mold body into the requested number of printable pieces.

    Two pieces use the contoured/planar parting (with keys/teeth/wings). Three or
    more use a *radial* split into wedges around the vertical axis — each wedge pulls
    straight out, so a model with undercuts on every side (where no single two-part
    parting releases) can still come free. Returns a list of parts.

    ``radial_center`` is the centre the radial clamp wings were built around; when
    given, the wedge cuts use it so every seam falls exactly on its wing (the wings
    shift the mold's bounding box, so re-deriving the centre would miss them).
    ``wing_bolt_zs`` is the bolt heights the 2-part wings drilled (None = no wings) —
    the wing alignment keys are placed between them. ``wing_offset`` (the mold
    wall's offset from the model) steers the radial wing keys; ``wing_chan`` is
    the bottom-fill channel's geometry (``channel.build_channel``) when one runs
    up a seam: the keys on its side sit on the wing inboard of the pipe."""
    n = max(int(getattr(props, "parts_count", 2)), 2)
    if n <= 2:
        half_a, half_b = split(mold, master, axis, props, coll, wall,
                               wing_bolt_zs=wing_bolt_zs, parting=parting,
                               wing_chan=wing_chan, wing_offset=wing_offset)
        return [half_a, half_b]
    return _split_radial(mold, master, props, coll, wall, n, center=radial_center,
                         wing_offset=wing_offset, wing_chan=wing_chan)


def resolve_axis(props, obj):
    """The horizontal axis ('X' or 'Y') the halves separate along.

    For ``AUTO`` we pick the pull direction the model *releases* best along — the
    one trapping fewer undercuts — and only fall back to the wider footprint when the
    two are about equal (a convex shape releases either way, so wider = neater halves).
    An explicit X/Y is honoured as-is."""
    axis = props.split_axis
    if axis != 'AUTO':
        return axis
    mn, mx = util.world_bbox(obj)
    wider = 'X' if (mx.x - mn.x) >= (mx.y - mn.y) else 'Y'
    ux = util.undercut_fraction(obj, 'X')
    uy = util.undercut_fraction(obj, 'Y')
    if abs(ux - uy) <= 0.02:
        return wider
    return 'X' if ux < uy else 'Y'


def _valid(obj):
    return util.part_is_valid(obj)[0]


def split(mold, master, axis, props, coll, wall, wing_bolt_zs=None, parting=None,
          wing_chan=None, wing_offset=0.0):
    """``parting`` (from ``parting_surface``, built before the clamp wings) is the
    contoured surface the wings were cut along: the halves are split on exactly
    that surface, so each half keeps its half of every wing."""
    mn, mx = util.world_bbox(mold)
    ai = {'X': 0, 'Y': 1}[axis]
    # Parting plane position along the split axis (clamped so neither half vanishes).
    cap = (mx[ai] - mn[ai]) * 0.4
    off = max(min(getattr(props, "split_offset", 0.0), cap), -cap)
    if parting is not None:
        off = parting.off

    half_a = half_b = None
    contoured = getattr(props, "contoured", True) and not getattr(props, "block", False)
    if contoured:
        try:
            ca, cb = _split_contoured(mold, master, axis, coll, off,
                                      cutter=None if parting is None else parting.cutter,
                                      flat=_flat_for(props, off))
            util.remove_small_islands(ca)   # boolean slivers, not a reason to reject
            util.remove_small_islands(cb)
            if _valid(ca) and _valid(cb):
                half_a, half_b = ca, cb
            else:
                util.remove_object(ca)
                util.remove_object(cb)
        except Exception:
            for o in [x for x in list(coll.objects)
                      if x.name.startswith("MF_Mold_") or x.name.startswith("MF_part")]:
                util.remove_object(o)

    contoured_used = half_a is not None
    if parting is not None:
        parting.used = contoured_used
    if not contoured_used:
        half_a, half_b = _split_planar(mold, axis, coll, off)
        util.remove_small_islands(half_a)
        util.remove_small_islands(half_b)

    util.remove_object(mold)

    if not half_a.data.polygons or not half_b.data.polygons:
        raise RuntimeError("Splitting produced an empty half.")

    # A contoured parting self-registers, and clamp wings + their bolts already
    # align a flat parting — so only add (otherwise tiny, on a thin wall) registration
    # keys when neither is in play.
    if (props.key_count > 0 and not contoured_used
            and not getattr(props, "wings", False)):
        if getattr(props, "registration", 'KEYS') == 'TEETH':
            _add_teeth(half_a, half_b, props, axis, ai, mn, mx, wall, coll, off)
        else:
            _add_keys(half_a, half_b, props, axis, ai, mn, mx, wall, coll, off)

    # Wing Alignment: raised keys on half_a's wing faces that seat into matching
    # sockets in half_b (works for flat AND contoured partings — the parting is flat
    # across the wings either way). ``wing_bolt_zs is None`` means no wings were
    # built (off, or rolled back), so nothing to key onto.
    if (getattr(props, "wings", False) and wing_bolt_zs is not None
            and getattr(props, "wing_keys", 'NONE') not in ('NONE', 'GROOVE')):
        _record_wing_keys(props, _add_wing_keys(
            half_a, half_b, props, axis, ai, mn, mx, coll, off, wing_bolt_zs,
            parting=parting if contoured_used else None, chan=wing_chan))
    if (getattr(props, "wings", False) and wing_bolt_zs is not None
            and getattr(props, "wing_keys", 'NONE') == 'GROOVE'):
        _record_wing_grooves(props, _add_wing_grooves(
            half_a, half_b, master, props, ai, mn, mx, coll, off, wing_bolt_zs,
            wing_offset, parting=parting if contoured_used else None, chan=wing_chan))

    return half_a, half_b




def _split_planar(mold, axis, coll, off=0.0):
    mn, mx = util.world_bbox(mold)
    size = mx - mn
    center = (mn + mx) * 0.5
    ai = {'X': 0, 'Y': 1}[axis]
    big = max(size.x, size.y, size.z) * 2.0 + 10.0

    def side_cube(sign):
        c = center.copy()
        c[ai] = center[ai] + off + sign * (big * 0.5)
        return util.add_box("MF_cut", c, Vector((big, big, big)), coll)

    cube_neg = side_cube(-1.0)
    cube_pos = side_cube(+1.0)
    half_a = util.duplicate_object(mold, "MF_Mold_A", coll)
    util.boolean(half_a, cube_neg, 'DIFFERENCE')   # keep +side
    half_b = util.duplicate_object(mold, "MF_Mold_B", coll)
    util.boolean(half_b, cube_pos, 'DIFFERENCE')   # keep -side
    util.remove_object(cube_neg)
    util.remove_object(cube_pos)
    return half_a, half_b


def _split_contoured(mold, master, axis, coll, off=0.0, cutter=None, flat=None):
    """Split with a parting surface that follows the master's mid-depth profile
    (carried outward past the silhouette). half_a = +axis side, half_b = -axis
    side. ``cutter`` is a prebuilt cutter (``parting_surface``); a copy is used."""
    mn, mx = util.world_bbox(mold)
    if cutter is not None:
        cutter = util.duplicate_object(cutter, "MF_part", coll)
    else:
        cutter = _contoured_cutter(master, axis, mn, mx, coll, off, flat=flat)
    half_a = util.duplicate_object(mold, "MF_Mold_A", coll)
    util.boolean(half_a, cutter, 'DIFFERENCE')   # remove -axis solid -> keep +axis
    half_b = util.duplicate_object(mold, "MF_Mold_B", coll)
    util.boolean(half_b, cutter, 'INTERSECT')    # keep overlap -> -axis side
    util.remove_object(cutter)
    return half_a, half_b


def parting_surface(mold, master, axis, props, coll, pad=0.0):
    """The contoured parting surface for a two-piece split, built ONCE before the
    clamp wings so the wings, their bolt holes and keys, and the split itself all
    use the same surface. Returns a namespace (``cutter``: the solid below the
    surface, ``off``, ``ai``, ``h``) or None for a flat parting.

    The wings used to be cut from a flat slab on the bounding-box centre plane
    while the split followed the model's mid-depth, carried outward past the
    silhouette. On a model that leans along the split axis the two are
    centimetres apart: each height's wing landed entirely in one half, and the
    other half had nothing to clamp against there - wings "disappearing in
    places". ``pad`` widens the cutter so it still covers the wings."""
    if not getattr(props, "contoured", True) or getattr(props, "block", False):
        return None
    if int(getattr(props, "parts_count", 2)) > 2:
        return None
    mn, mx = util.world_bbox(mold)
    ai = {'X': 0, 'Y': 1}[axis]
    cap = (mx[ai] - mn[ai]) * 0.4
    off = max(min(getattr(props, "split_offset", 0.0), cap), -cap)
    padv = Vector((pad, pad, pad))
    padv[ai] = 0.0
    try:
        cutter = _contoured_cutter(master, axis, mn - padv, mx + padv, coll, off,
                                   flat=_flat_for(props, off))
    except Exception:
        return None
    cutter.name = "MF_parting"
    h = next(i for i in range(3) if i != ai and i != 2)
    return types.SimpleNamespace(cutter=cutter, off=off, ai=ai, h=h, axis=axis,
                                 used=None)


def parting_at(parting, hv, z):
    """The surface's position along the split axis at horizontal coordinate
    ``hv`` (along the seam) and height ``z``, or None outside it."""
    cut = parting.cutter
    mn, mx = util.world_bbox(cut)
    o = Vector((0.0, 0.0, 0.0))
    o[parting.h] = hv
    o[2] = z
    o[parting.ai] = mx[parting.ai] + 10.0
    d = Vector((0.0, 0.0, 0.0))
    d[parting.ai] = -1.0
    hit, loc, _n, _i = cut.ray_cast(o, d)
    return loc[parting.ai] if hit else None


def wing_tip(obj, parting, center, z, sgn, reach, seam_flat, ai, h, bias=0.0,
             h0=None):
    """Where the clamp wing on side ``sgn`` (along the seam axis ``h``) ends at
    height z: ``(h_tip, seam)`` - the outermost point of ``obj`` and the parting
    surface's position there - found by alternating a ray in along the seam (at
    the surface + ``bias`` along the split axis ``ai``) with a look-up of the
    surface. ``parting`` None = a flat parting at ``seam_flat``. ``h0`` is where
    along the seam to read the surface first (default: well out past the
    mold); on a steep seam a first read far from the wing can aim the ray past
    it. None if the ray misses."""
    seam = seam_flat
    if parting is not None:
        s0 = parting_at(parting, center[h] + sgn * reach * 0.25 if h0 is None else h0, z)
        seam = s0 if s0 is not None else seam_flat
    tip = None
    for _ in range(4):
        o = center.copy(); o[ai] = seam + bias; o[2] = z; o[h] = center[h] + sgn * reach
        d = Vector((0.0, 0.0, 0.0)); d[h] = -sgn
        hit, loc, _n, _i = obj.ray_cast(o, d)
        if not hit:
            return None
        tip = loc[h]
        if parting is None:
            break
        s1 = parting_at(parting, tip - sgn * 1.0, z)
        if s1 is None or abs(s1 - seam) < 0.05:
            break
        seam = s1
    return tip, seam


def seam_band(parting, thickness, z_lo, z_hi, coll):
    """A slab ``thickness`` thick (along the split axis) centred on the parting
    surface, between heights z_lo and z_hi: what a clamp wing is cut from."""
    up = util.duplicate_object(parting.cutter, "MF_wband", coll)
    lo = util.duplicate_object(parting.cutter, "MF_wbandlo", coll)
    sh = Vector((0.0, 0.0, 0.0))
    sh[parting.ai] = thickness * 0.5
    up.data.transform(Matrix.Translation(sh))
    lo.data.transform(Matrix.Translation(-sh))
    util.boolean(up, lo, 'DIFFERENCE')
    util.remove_object(lo)
    mn, mx = util.world_bbox(up)
    big = (mx - mn).length * 2.0 + 10.0
    box = util.add_box("MF_wbandz", Vector(((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5,
                                            (z_lo + z_hi) * 0.5)),
                       Vector((big, big, z_hi - z_lo)), coll)
    util.boolean(up, box, 'INTERSECT')
    util.remove_object(box)
    return up


def flat_zone(mold, axis, z_lo, z_hi, z_top):
    """Locking Base: the seam must stay a flat plane through the sawtooth plinth
    and its socket, up to the socket's shoulder at ``z_top``, so each half's
    share of the socket pulls straight off the plinth's teeth. Returns
    ``(z_top, at)``: where along the split axis the plane sits - the middle of
    the base across the plinth's own heights ``z_lo``..``z_hi`` (above them a
    curved model's body already leans off to one side) - or None."""
    ai = {'X': 0, 'Y': 1}[axis]
    mw = mold.matrix_world
    vals = [p[ai] for p in (mw @ v.co for v in mold.data.vertices)
            if z_lo - 1e-3 <= p.z <= z_hi + 1e-3]
    if not vals:
        return None
    return z_top, (min(vals) + max(vals)) * 0.5


def _flat_for(props, off):
    """The flat zone for the cutter (``(z_top, at, blend)``), or None."""
    fz = getattr(props, "parting_flat", None)
    if not fz:
        return None
    return fz[0], fz[1] + off, max(getattr(props, "parting_blend", 12.0), 1.0)


def _contoured_cutter(master, axis, mn, mx, coll, off=0.0, res=48, flat=None):
    """A closed solid bounded above (in +axis) by the master's mid-depth surface
    and extending far into -axis. Subtracting it keeps the +axis half. ``off`` slides
    the whole parting surface along the split axis. ``flat`` = ``(z_top, at,
    blend)``: the surface is the flat plane ``at`` up to ``z_top`` and blends
    into the contoured one over ``blend`` above it (a Locking Base's plinth)."""
    ai = {'X': 0, 'Y': 1}[axis]
    u, v = [i for i in range(3) if i != ai]
    size = mx - mn
    big = size.length * 2.0 + 10.0
    cen = (mn[ai] + mx[ai]) * 0.5 + off
    near = cen - big
    far = cen + big
    margin = max(size[u], size[v]) * 0.2 + 1.0
    umin, umax = mn[u] - margin, mx[u] + margin
    vmin, vmax = mn[v] - margin, mx[v] + margin

    def mid_height(uu, vv):
        o1 = Vector((0.0, 0.0, 0.0)); o1[u] = uu; o1[v] = vv; o1[ai] = far
        d1 = Vector((0.0, 0.0, 0.0)); d1[ai] = -1.0
        hit1, loc1, _n1, _i1 = master.ray_cast(o1, d1)
        o2 = Vector((0.0, 0.0, 0.0)); o2[u] = uu; o2[v] = vv; o2[ai] = near
        d2 = Vector((0.0, 0.0, 0.0)); d2[ai] = 1.0
        hit2, loc2, _n2, _i2 = master.ray_cast(o2, d2)
        if hit1 and hit2:
            return (loc1[ai] + loc2[ai]) * 0.5 + off
        return None      # outside the silhouette

    n = res + 1
    coords = [[(umin + (umax - umin) * i / res, vmin + (vmax - vmin) * j / res)
               for j in range(n)] for i in range(n)]
    H = [[mid_height(*coords[i][j]) for j in range(n)] for i in range(n)]

    # Outside the silhouette - below the base, beyond the sides, above the top -
    # the rays miss. Snapping those cells to the bbox centre put a STEP in the
    # parting surface wherever the model's mid-depth is not that centre: on a
    # leaning or curved sculpt that is a multi-millimetre ledge along the seam
    # at the base plane (the user's "uncut line at the bottom of the shell") and
    # along the silhouette edge, and it cut the funnel column off-centre.
    # Extend the nearest in-model value outward instead, so the surface is
    # continuous everywhere and only a model with no silhouette at all is flat.
    if not any(h is not None for row in H for h in row):
        H = [[cen] * n for _ in range(n)]
    else:
        for _ in range(2 * n):
            todo = [(i, j) for i in range(n) for j in range(n) if H[i][j] is None]
            if not todo:
                break
            grown = {}
            for i, j in todo:
                vals = [H[a][b] for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1))
                        if 0 <= a < n and 0 <= b < n and H[a][b] is not None]
                if vals:
                    grown[(i, j)] = sum(vals) / len(vals)
            if not grown:
                break
            for (i, j), val in grown.items():
                H[i][j] = val
        for i in range(n):
            for j in range(n):
                if H[i][j] is None:
                    H[i][j] = cen

    # Smooth the height field so the parting is a clean wave, not a staircase.
    for _ in range(8):
        S = [row[:] for row in H]
        for i in range(1, n - 1):
            for j in range(1, n - 1):
                S[i][j] = (H[i][j] + H[i - 1][j] + H[i + 1][j]
                           + H[i][j - 1] + H[i][j + 1]) / 5.0
        H = S

    if flat is not None:
        # Flat through the plinth: every grid row up to the first one above
        # z_top is exactly ``at`` (so the faces between them are flat too),
        # then a smoothstep into the contoured surface.
        z_top, at, blend = flat
        dzg = (vmax - vmin) / res
        for i in range(n):
            for j in range(n):
                t = (coords[i][j][1] - (z_top + dzg)) / blend
                if t <= 0.0:
                    H[i][j] = at
                elif t < 1.0:
                    s3 = t * t * (3.0 - 2.0 * t)
                    H[i][j] = at + (H[i][j] - at) * s3

    bm = bmesh.new()
    top = {}
    bot = {}
    for i in range(n):
        for j in range(n):
            uu, vv = coords[i][j]
            ct = Vector((0.0, 0.0, 0.0)); ct[u] = uu; ct[v] = vv; ct[ai] = H[i][j]
            cb = Vector((0.0, 0.0, 0.0)); cb[u] = uu; cb[v] = vv; cb[ai] = near
            top[(i, j)] = bm.verts.new(ct)
            bot[(i, j)] = bm.verts.new(cb)
    for i in range(res):
        for j in range(res):
            bm.faces.new((top[(i, j)], top[(i, j + 1)], top[(i + 1, j + 1)], top[(i + 1, j)]))
            bm.faces.new((bot[(i, j)], bot[(i + 1, j)], bot[(i + 1, j + 1)], bot[(i, j + 1)]))
    for i in range(res):
        bm.faces.new((top[(i, 0)], top[(i + 1, 0)], bot[(i + 1, 0)], bot[(i, 0)]))
        bm.faces.new((top[(i, res)], bot[(i, res)], bot[(i + 1, res)], top[(i + 1, res)]))
    for j in range(res):
        bm.faces.new((top[(0, j)], bot[(0, j)], bot[(0, j + 1)], top[(0, j + 1)]))
        bm.faces.new((top[(res, j)], top[(res, j + 1)], bot[(res, j + 1)], bot[(res, j)]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return util.new_mesh_object("MF_part", bm, coll)


def _add_teeth(half_a, half_b, props, axis, ai, mn, mx, wall, coll, off=0.0):
    """Interlocking castellation along the seam: a row of square teeth raised on
    half_a that seat into matching pockets in half_b — stronger anti-slip than round
    pins. Each tooth is kept only where it actually overlaps the wall, so none float."""
    center = (mn + mx) * 0.5
    h = next(i for i in range(3) if i != ai and i != 2)
    seam = center[ai] + off
    tooth = max(wall * 0.8, 0.6)
    depth = max(wall * 0.5, 0.4)
    n = max(props.key_count * 2, 4)
    for k in range(n):
        if k % 2 == 0:                        # castellate: tooth on every other slot
            continue
        hh = mn[h] + (mx[h] - mn[h]) * (k + 0.5) / n
        c = center.copy(); c[ai] = seam; c[h] = hh; c[2] = center.z
        size = Vector((0.0, 0.0, 0.0))
        size[ai] = depth * 2.0; size[h] = tooth; size[2] = tooth * 2.0
        box = util.add_box("MF_tooth", c, size, coll)
        probe = util.duplicate_object(box, "MF_ttest", coll)
        util.boolean(probe, half_a, 'INTERSECT')
        inside = bool(probe.data.polygons)
        util.remove_object(probe)
        if inside:
            socket = util.duplicate_object(box, "MF_tsock", coll)
            util.boolean(half_a, box, 'UNION')        # raise the tooth on A
            util.boolean(half_b, socket, 'DIFFERENCE')  # matching pocket in B
            util.remove_object(socket)
        util.remove_object(box)


def _add_keys(half_a, half_b, props, axis, ai, mn, mx, wall, coll, off=0.0):
    """Conical pins on half_a's parting face that seat into sockets in half_b.

    For each candidate position we ray-cast half_a to find where the wall
    actually is and seat the key half a wall-thickness inside it. Positions with
    no wall are skipped, so a key never ends up floating as a disconnected island.
    """
    center = (mn + mx) * 0.5
    half_z = (mx.z - mn.z) * 0.5
    h = next(i for i in range(3) if i != ai and i != 2)
    reach = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) + 10.0

    key_r = min(props.key_radius, max(wall * 0.45, 0.2))
    seat = props.key_depth * 0.5
    depth = props.key_depth + seat
    center_ai = center[ai] + off + (-props.key_depth + seat) * 0.5
    probe_ai = center[ai] + off + min(seat * 0.5, half_z * 0.5)

    layouts = {
        1: [(1.0, 0.0)],
        2: [(1.0, 0.0), (-1.0, 0.0)],
        3: [(1.0, 0.4), (1.0, -0.4), (-1.0, 0.0)],
        4: [(1.0, 0.4), (1.0, -0.4), (-1.0, 0.4), (-1.0, -0.4)],
    }
    plan = layouts.get(min(props.key_count, 4), layouts[4])

    placed = 0
    for h_sign, z_frac in plan:
        z = center.z + z_frac * half_z
        origin = center.copy()
        origin[ai] = probe_ai
        origin[2] = z
        origin[h] = center[h] + h_sign * reach
        direction = Vector((0.0, 0.0, 0.0))
        direction[h] = -h_sign

        hit, loc, _normal, _idx = half_a.ray_cast(origin, direction)
        if not hit:
            continue

        c = center.copy()
        c[ai] = center_ai
        c[2] = z
        c[h] = loc[h] - h_sign * wall * 0.5

        pin = util.add_cone(f"MF_key_{placed}", c, key_r * 0.45, key_r, depth, axis, coll)
        socket = util.duplicate_object(pin, f"MF_key_socket_{placed}", coll)
        util.boolean(half_a, pin, 'UNION')
        util.remove_object(pin)
        util.boolean(half_b, socket, 'DIFFERENCE')
        util.remove_object(socket)
        placed += 1


def _wing_key_dims(props):
    """Shared Wing Alignment sizing for the 2-part and radial wings, or None when
    keys are off or the wing lip is too thin for a useful key.

    Each piece keeps half the wing's thickness at the seam, so with automatic
    height a key never protrudes deeper than that lip minus the fit clearance minus
    a socket floor - a socket can never punch through the mating wing."""
    style = getattr(props, "wing_keys", 'NONE')
    if style in ('NONE', 'GROOVE'):
        return None
    width = max(getattr(props, "wing_width", 8.0), 2.0)
    thickness = max(getattr(props, "wing_thickness", 4.0), 2.0)
    clear = max(getattr(props, "fit_clearance", 0.2), 0.0)
    prot_cap = thickness * 0.5 - clear - 0.5  # leave a floor under the socket
    if prot_cap < 0.4:
        return None                           # wing lip too thin for a useful key
    R = max(min(getattr(props, "wing_key_size", 6.0) * 0.5, width * 0.45), 0.5)
    height = max(getattr(props, "wing_key_height", 0.0), 0.0)
    if height > 0.0:
        # Explicit Key Height: the user chose how far the keys stand out — past the
        # wing lip the socket punches through the mating wing as a hole (documented;
        # still aligns). A Half Sphere is capped at a full hemisphere: any taller
        # would bulge wider than its socket mouth and could never assemble.
        prot = min(height, R) if style == 'DOME' else height
    else:
        # Auto: proportional to the key size, capped by the lip so the socket
        # never pierces the wing.
        want = {'CONE': R * 1.2, 'DOME': R, 'FRUSTUM': R * 0.7}.get(style, R)
        prot = min(want, prot_cap)
    return types.SimpleNamespace(
        style=style, width=width, thickness=thickness, clear=clear, R=R, prot=prot,
        spacing=max(getattr(props, "wing_key_spacing", 40.0), 4.0),
        embed=min(thickness * 0.25, 1.0),     # root sunk into the lip for a solid weld
        bias=min(thickness * 0.25, 0.8))      # probe this far inside the keyed lip


def _wing_key_heights(z_lo, z_hi, R, spacing, bolt_zs, props):
    """Key heights between ``z_lo`` and ``z_hi``: evenly at the Key Spacing pitch,
    nudged off (or dropped from) any bolt hole in ``bolt_zs``."""
    zpad = max(R + 1.0, 2.0)
    z0, z1 = z_lo + zpad, z_hi - zpad
    if z1 <= z0:
        return []
    span = z1 - z0
    n = max(1, int(round(span / spacing)))
    guard = max(getattr(props, "bolt_radius", 1.5), 0.5) + R + 1.0
    picks = []
    for k in range(n):
        z = z0 + span * (k + 0.5) / n
        zb = min(bolt_zs, key=lambda b: abs(b - z), default=None) if bolt_zs else None
        if zb is not None and abs(zb - z) < guard:
            for alt in (zb + guard, zb - guard):
                if z0 <= alt <= z1 and all(abs(alt - b) >= guard for b in bolt_zs):
                    z = alt
                    break
            else:
                continue                       # no safe spot near this bolt: skip it
        if all(abs(z - pz) >= 2.0 * R + 1.0 for pz in picks):
            picks.append(z)
    return picks


def _wing_key_solid(name, dims, center, ai, h, axis, hc, z, seam, grow, deeper, coll):
    """One key (``grow`` = ``deeper`` = 0) or its socket (both = the clearance), in
    world space. The keyed piece keeps the +``axis`` side of the seam, so the key
    protrudes toward -``axis``; ``hc`` is its position along axis ``h``."""
    R, style, embed = dims.R, dims.style, dims.embed
    c = center.copy(); c[h] = hc; c[2] = z
    r_face = R + grow
    depth_out = dims.prot + deeper
    if style == 'DOME':
        # Spherical cap: footprint r_face on the seam, poking depth_out past it —
        # a full hemisphere when the lip allows, a wider shallow cap when not. The
        # sphere's buried bulk is clipped flush inside the lip so the male can never
        # bulge out of the wing's back face (and the socket cuts only its cap depth).
        rs = (r_face * r_face + depth_out * depth_out) / (2.0 * depth_out)
        c[ai] = seam + (rs - depth_out)
        ball = util.add_sphere(name, c, rs, coll, subdiv=3)
        sb = center.copy(); sb[ai] = seam + (embed - depth_out - 1.0) * 0.5
        size = Vector((0.0, 0.0, 0.0))
        size[ai] = depth_out + 1.0 + embed
        size[h] = size[2] = 4.0 * rs + 4.0
        sb[2] = z; sb[h] = hc
        box = util.add_box(name + "_clip", sb, size, coll)
        util.boolean(ball, box, 'INTERSECT')
        util.remove_object(box)
        return ball
    r_tip = r_face * (0.06 if style == 'CONE' else 0.55)
    # tip at r1, the -axis end
    c[ai] = seam + (embed - depth_out) * 0.5
    return util.add_cone(name, c, r_tip, r_face, depth_out + embed, axis, coll)


def _seat_wing_key(keyed, mating, male, socket, coll):
    """Union ``male`` into ``keyed`` and cut ``socket`` from ``mating``, if the key
    really sits on ``keyed``'s lip and both pieces stay valid; otherwise roll both
    back. Removes ``male`` and ``socket`` either way. Returns True when placed."""
    try:
        probe = util.duplicate_object(male, "MF_wktest", coll)
        util.boolean(probe, keyed, 'INTERSECT')
        seated = bool(probe.data.polygons)
        util.remove_object(probe)
        if not seated:
            return False
        a_bak, b_bak = keyed.data.copy(), mating.data.copy()
        try:
            util.boolean(keyed, male, 'UNION')
            util.boolean(mating, socket, 'DIFFERENCE')
            if not (util.part_is_valid(keyed)[0] and util.part_is_valid(mating)[0]):
                raise RuntimeError("wing key would break a piece")
        except Exception:                     # roll back; a key never breaks a piece
            for obj, bak in ((keyed, a_bak), (mating, b_bak)):
                cur = obj.data
                obj.data = bak
                if cur.users == 0:
                    bpy.data.meshes.remove(cur)
            return False
        for bak in (a_bak, b_bak):
            if bak.users == 0:
                bpy.data.meshes.remove(bak)
        return True
    finally:
        util.remove_object(male)
        util.remove_object(socket)


def _add_wing_keys(half_a, half_b, props, axis, ai, mn, mx, coll, off, bolt_zs,
                   parting=None, chan=None):
    """Wing Alignment keys: a raised key on half_a's clamp-wing mating face seats into
    a matching socket in half_b, so the bolted halves can't shear sideways. Three
    shapes (the Wing Alignment option): CONE — a pointed pin, self-centering; DOME — a
    half sphere, smooth engage/release; FRUSTUM — a half (truncated) cone pad, sturdy.

    The key DIAMETER is the user's Key Size (a bigger size grows the footprint; the
    dome becomes a wide spherical cap when the lip is shallow); its height comes from
    ``_wing_key_dims``. Keys are spread along the seam at the Key Spacing pitch,
    dodging the drilled bolt holes (``bolt_zs``); the socket is the same shape grown
    by the Fit Clearance so printed parts actually seat. ``chan`` is the bottom-fill
    channel when its pipe runs up one side of the wing: the outermost point there is
    the pipe, so that side's keys are placed from the wing's own edge (measured
    before the pipe went on) and kept off the pipe and its gate. Best-effort with
    rollback: a key that would leave either half invalid is skipped, never breaking
    a good mold."""
    dims = _wing_key_dims(props)
    if dims is None:
        return 0
    h = next(i for i in range(3) if i != ai and i != 2)
    center = (mn + mx) * 0.5
    seam = center[ai] + off
    reach = (mx - mn).length + 10.0
    picks = _wing_key_heights(mn.z, mx.z, dims.R, dims.spacing, bolt_zs, props)

    from . import channel as _channel
    inset = max(dims.width * 0.45, dims.R + 1.2)
    fr = chan["frame"] if chan is not None and not chan["frame"].multipart else None
    chan_sign = None if fr is None else (1.0 if fr.d[h] > 0 else -1.0)

    placed = 0
    for h_sign in (1.0, -1.0):
        for z in picks:
            if h_sign == chan_sign:
                # the pipe is the outermost point here: key off the wing's own edge
                t_key = _channel.key_spot(chan, z, dims.R + dims.clear, inset)
                if t_key is None:
                    continue
                hc = fr.center[h] + h_sign * t_key
                seam_here = seam
                if parting is not None:
                    s_ = parting_at(parting, hc, z)
                    seam_here = s_ if s_ is not None else seam
            else:
                # probe inside A's wing lip, on the parting surface (contoured or flat)
                found = wing_tip(half_a, parting, center, z, h_sign, reach, seam, ai, h,
                                 bias=dims.bias)
                if found is None:
                    continue
                tip, seam_here = found
                hc = tip - h_sign * inset
            if parting is not None:
                s_key = parting_at(parting, hc, z)
                seam_here = s_key if s_key is not None else seam_here

            male = _wing_key_solid(f"MF_wkey_{placed}", dims, center, ai, h, axis,
                                   hc, z, seam_here, 0.0, 0.0, coll)
            socket = _wing_key_solid(f"MF_wsock_{placed}", dims, center, ai, h, axis,
                                     hc, z, seam_here, dims.clear, dims.clear, coll)
            if _seat_wing_key(half_a, half_b, male, socket, coll):
                placed += 1
    return placed


def _add_radial_wing_keys(parts, center, mn, mx, props, coll, n, master, bolt_zs,
                          offset, chan=None):
    """Wing Alignment keys for a radial split: up each seam's clamp flange, a key on
    one wedge's lip seats into a socket in its neighbour's, so bolted wedges can't
    shear along the seam. Same shapes, sizing, pitch and bolt dodging as the
    two-part keys (``_add_wing_keys``).

    Seam ``k`` runs out from ``center`` along angle 2 pi k / n, between wedge ``k``
    (which takes the key) and wedge ``k - 1`` (the socket). A key is placed only
    where the flange stands clear of the mold wall (the model, ``master``, grown by
    ``offset``), so a socket never reaches into the cavity. ``chan`` is the
    bottom-fill channel, which runs up the first seam: there the keys are placed
    from the flange's own edge, off the pipe and its gate. Each key is built in a seam-aligned
    frame - local X out along the seam, +Y into wedge k - then turned into place.
    Best-effort with rollback. Returns the number of keys placed."""
    dims = _wing_key_dims(props)
    if dims is None:
        return 0
    far = (mx - mn).length + 10.0
    picks = _wing_key_heights(mn.z, mx.z, dims.R, dims.spacing, bolt_zs, props)
    zero = Vector((0.0, 0.0, 0.0))
    inset = max(dims.width * 0.45, dims.R + 1.2)

    from . import channel as _channel
    on_chan = chan is not None and chan["frame"].multipart
    placed = 0
    for k in range(n):
        theta = 2.0 * math.pi * k / n
        d = Vector((math.cos(theta), math.sin(theta), 0.0))
        nrm = Vector((-math.sin(theta), math.cos(theta), 0.0))   # into wedge k
        keyed, mating = parts[k], parts[(k - 1) % n]
        place = (Matrix.Translation(Vector((center.x, center.y, 0.0)))
                 @ Matrix.Rotation(theta, 4, 'Z'))
        for z in picks:
            axis_o = Vector((center.x, center.y, z)) + d * far
            hit, loc, _n1, _i1 = keyed.ray_cast(axis_o + nrm * dims.bias, -d)
            hm, lm, _n2, _i2 = master.ray_cast(axis_o, -d)
            if not (hit and hm):
                continue
            tip = (loc - Vector((center.x, center.y, loc.z))).dot(d)
            tipm = (lm - Vector((center.x, center.y, lm.z))).dot(d)
            r = tip - inset
            if k == 0 and on_chan:
                # the pipe is the outermost point: key off the flange's own edge
                fc = chan["frame"].center
                shift = (Vector((fc.x, fc.y, 0.0)) - Vector((center.x, center.y, 0.0))).dot(d)
                t_edge = _channel.wing_edge(chan, z)
                t_key = _channel.key_spot(chan, z, dims.R + dims.clear, inset)
                if t_edge is None or t_key is None:
                    continue
                tip = t_edge + shift
                r = t_key + shift
            if (tip - tipm < offset + 0.6 * dims.width
                    or r - dims.R - dims.clear < tipm + offset):
                continue                       # no flange standing clear of the wall
            male = _wing_key_solid(f"MF_rwkey_{placed}", dims, zero, 1, 0, 'Y',
                                   r, z, 0.0, 0.0, 0.0, coll)
            socket = _wing_key_solid(f"MF_rwsock_{placed}", dims, zero, 1, 0, 'Y',
                                     r, z, 0.0, dims.clear, dims.clear, coll)
            male.data.transform(place)
            socket.data.transform(place)
            if _seat_wing_key(keyed, mating, male, socket, coll):
                placed += 1
    return placed


# --- Tongue & Groove up the wing ------------------------------------------------ #

def _groove_dims(props):
    """Tongue & Groove sizing, or None when the wing lip is too thin for one.
    Each piece keeps half the wing's thickness at the seam, so the groove (the
    tongue's height plus the clearance) never goes deeper than that lip less a
    0.5 mm floor."""
    thickness = max(getattr(props, "wing_thickness", 4.0), 2.0)
    clear = max(getattr(props, "fit_clearance", 0.2), 0.0)
    cap = thickness * 0.5 - clear - 0.5
    if cap < 0.4:
        return None
    want = getattr(props, "wing_groove_depth", 0.0)
    depth = min(want if want > 0.0 else 2.0, cap)
    width = max(getattr(props, "wing_groove_width", 2.0), 0.6)
    return types.SimpleNamespace(depth=depth, width=width, clear=clear,
                                 gw=width + 2.0 * clear,
                                 bolt_r=getattr(props, "bolt_radius", 1.5))


def _model_bvh(master):
    """A BVH of ``master`` in world space, for distances to the model."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(master.data)
    bm.transform(master.matrix_world)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def _iso_lines(grid, us, zs, level):
    """Marching squares: the polylines (lists of (u, z)) where the sampled
    field ``grid[i][j]`` (at ``us[i]``, ``zs[j]``; None = unknown) crosses
    ``level``. Closed loops come back with their first point repeated."""
    def lerp(a, b, fa, fb):
        f = (level - fa) / (fb - fa)
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
    segs = []
    for i in range(len(us) - 1):
        for j in range(len(zs) - 1):
            c = [((i, j), (us[i], zs[j])), ((i + 1, j), (us[i + 1], zs[j])),
                 ((i + 1, j + 1), (us[i + 1], zs[j + 1])), ((i, j + 1), (us[i], zs[j + 1]))]
            v = [grid[a][b] for (a, b), _p in c]
            if any(x is None for x in v):
                continue
            cross = []
            for k in range(4):
                (ka, pa), (kb, pb) = c[k], c[(k + 1) % 4]
                fa, fb = v[k], v[(k + 1) % 4]
                if (fa < level) != (fb < level):
                    key = tuple(sorted((ka, kb)))
                    cross.append((key, lerp(pa, pb, fa, fb)))
            if len(cross) == 2:
                segs.append(cross)
            elif len(cross) == 4:                 # a saddle: pair by the centre value
                mid = sum(v) * 0.25
                if (mid < level) == (v[0] < level):
                    segs += [[cross[0], cross[3]], [cross[1], cross[2]]]
                else:
                    segs += [[cross[0], cross[1]], [cross[2], cross[3]]]
    # chain the segments end to end through their shared grid edges
    ends = {}
    for k, ((ea, _pa), (eb, _pb)) in enumerate(segs):
        ends.setdefault(ea, []).append(k)
        ends.setdefault(eb, []).append(k)
    used = [False] * len(segs)
    lines = []
    for k0 in range(len(segs)):
        if used[k0]:
            continue
        used[k0] = True
        (ea, pa), (eb, pb) = segs[k0]
        line = [(ea, pa), (eb, pb)]
        for forward in (True, False):
            while True:
                tip_key = line[-1][0] if forward else line[0][0]
                nxt = [k for k in ends.get(tip_key, ()) if not used[k]]
                if not nxt:
                    break
                k = nxt[0]
                used[k] = True
                (xa, qa), (xb, qb) = segs[k]
                far = (xb, qb) if xa == tip_key else (xa, qa)
                if forward:
                    line.append(far)
                else:
                    line.insert(0, far)
        lines.append([p for _k, p in line])
    return lines


def _ribbon(name, pts, nrms, half_w, a, b, point, n_mate, coll, closed=False,
            extend=0.0):
    """A solid strip along the polyline ``pts`` on the seam surface (points as
    (u, z), mapped by ``point``): ``half_w`` either side of the line in the
    surface (along ``nrms``), from ``a`` to ``b`` across it along ``n_mate``.
    ``extend`` lengthens an open strip at both ends."""
    pts = list(pts)
    nrms = list(nrms)
    if extend > 0.0 and not closed and len(pts) >= 2:
        def push(p, q):
            d = (p[0] - q[0], p[1] - q[1])
            ln = math.hypot(*d) or 1.0
            return (p[0] + d[0] / ln * extend, p[1] + d[1] / ln * extend)
        pts = [push(pts[0], pts[1])] + pts + [push(pts[-1], pts[-2])]
        nrms = [nrms[0]] + nrms + [nrms[-1]]
    bm = bmesh.new()
    rings = []
    for (u, z), (nu, nz) in zip(pts, nrms):
        l = point(u + nu * half_w, z + nz * half_w)
        r = point(u - nu * half_w, z - nz * half_w)
        rings.append([bm.verts.new(l + n_mate * a), bm.verts.new(r + n_mate * a),
                      bm.verts.new(r + n_mate * b), bm.verts.new(l + n_mate * b)])
    m = len(rings)
    for i in range(m if closed else m - 1):
        ra, rb = rings[i], rings[(i + 1) % m]
        for k in range(4):
            kn = (k + 1) % 4
            bm.faces.new((ra[k], ra[kn], rb[kn], rb[k]))
    if not closed:
        bm.faces.new(rings[0])
        bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return util.new_mesh_object(name, bm, coll)


def _groove_seam(keyed, mating, bvh, dims, point, n_mate, u_range, z_range, level,
                 chan_axis, coll, name):
    """Tongue & Groove along one seam's wing. The wing is the band between
    ``offset`` and ``offset + width`` from the model, so its middle is the line
    on the seam surface at distance ``level`` from it: traced as a contour of
    the distance (points ``point(u, z)``, a 1 mm grid over ``u_range`` x
    ``z_range``), it runs wherever the wing does - up the sides, over the top,
    round a cap. It is kept only where both pieces have wing on either side of
    the groove (so it stops where the wing stops: the base, a funnel, a bolt
    hole) and clear of ``chan_axis`` (the bottom-fill channel's centre line,
    with its radius); cut into runs at sharp turns, each run is seated on its
    own. Returns how many runs were cut."""
    from . import build as _build
    dg = bpy.context.evaluated_depsgraph_get()
    step = 1.0
    nu = max(int((u_range[1] - u_range[0]) / step), 2)
    nz = max(int((z_range[1] - z_range[0]) / step), 2)
    us = [u_range[0] + (u_range[1] - u_range[0]) * i / nu for i in range(nu + 1)]
    zs = [z_range[0] + (z_range[1] - z_range[0]) * j / nz for j in range(nz + 1)]
    grid = []
    for u in us:
        col = []
        for z in zs:
            p = point(u, z)
            hit = bvh.find_nearest(p) if p is not None else None
            col.append(hit[3] if hit and hit[0] is not None else None)
        grid.append(col)
    lines = _iso_lines(grid, us, zs, level)

    reach = dims.gw * 0.5 + 1.0                    # wing kept round the groove

    def ok(uv, nrm):
        if point(*uv) is None:
            return False
        if chan_axis is not None:
            q = point(*uv)
            for a_, b_, rad in chan_axis:
                ab = b_ - a_
                f = max(0.0, min(1.0, (q - a_).dot(ab) / max(ab.length_squared, 1e-12)))
                if (q - (a_ + ab * f)).length < rad + reach:
                    return False
        def wing_at(du, dz):
            p = point(uv[0] + du, uv[1] + dz)
            return p is not None and (
                _build._inside_solid(keyed, p - n_mate * 0.3, dg)
                and _build._inside_solid(mating, p + n_mate * 0.3, dg))
        for s in (-reach, -dims.gw * 0.5, 0.0, dims.gw * 0.5, reach):
            if not wing_at(nrm[0] * s, nrm[1] * s):
                return False
        # Ahead and behind along the line: a gap with wing again past it is a
        # hole (a bolt) to stop short of; no wing past it is the wing's own end,
        # which the tongue runs right up to.
        tu, tz = nrm[1], -nrm[0]
        for s in (-reach, reach):
            for c in (-dims.gw * 0.5, 0.0, dims.gw * 0.5):
                if wing_at(tu * s + nrm[0] * c, tz * s + nrm[1] * c):
                    continue
                past = s + math.copysign(6.0, s)
                if wing_at(tu * past + nrm[0] * c, tz * past + nrm[1] * c):
                    return False
        return True

    runs = []
    for line in lines:
        closed = len(line) > 3 and math.dist(line[0], line[-1]) < 1e-6
        if closed:
            line = line[:-1]
        if len(line) < 3:
            continue
        nrms = []
        for k in range(len(line)):
            a_ = line[(k - 1) % len(line)] if (closed or k > 0) else line[k]
            b_ = line[(k + 1) % len(line)] if (closed or k < len(line) - 1) else line[k]
            tu, tz = b_[0] - a_[0], b_[1] - a_[1]
            ln = math.hypot(tu, tz) or 1.0
            nrms.append((-tz / ln, tu / ln))
        good = [ok(p, n) for p, n in zip(line, nrms)]
        if closed and all(good):
            runs.append((line, nrms, True))
            continue
        # open runs of good points; a closed loop is unrolled at a bad point
        order = list(range(len(line)))
        if closed:
            first_bad = good.index(False)
            order = order[first_bad:] + order[:first_bad]
        cur = []
        for k in order:
            if good[k]:
                cur.append(k)
            else:
                if len(cur) >= 3:
                    runs.append(([line[i] for i in cur], [nrms[i] for i in cur], False))
                cur = []
        if len(cur) >= 3:
            runs.append(([line[i] for i in cur], [nrms[i] for i in cur], False))

    # split at sharp turns: a strip folds over itself on the inside of one
    pieces = []
    for pts, nrms, closed in runs:
        cut_at = [k for k in range(1, len(pts) - 1)
                  if nrms[k - 1][0] * nrms[k + 1][0] + nrms[k - 1][1] * nrms[k + 1][1]
                  < math.cos(math.radians(35.0))]
        if not cut_at:
            pieces.append((pts, nrms, closed))
            continue
        bounds = [0] + cut_at + [len(pts) - 1]
        for a_, b_ in zip(bounds, bounds[1:]):
            if b_ - a_ >= 2:
                pieces.append((pts[a_:b_ + 1], nrms[a_:b_ + 1], False))

    done = 0
    for k, (pts, nrms, closed) in enumerate(pieces):
        if sum(math.dist(p, q) for p, q in zip(pts, pts[1:])) < 3.0:
            continue
        tongue = _ribbon(f"{name}t{k}", pts, nrms, dims.width * 0.5, -0.3,
                         dims.depth, point, n_mate, coll, closed)
        groove = _ribbon(f"{name}g{k}", pts, nrms, dims.gw * 0.5, -0.05,
                         dims.depth + dims.clear, point, n_mate, coll, closed,
                         extend=dims.clear)
        if _seat_wing_key(keyed, mating, tongue, groove, coll):
            done += 1
    return done


def _chan_axis(chan):
    """The bottom-fill channel as segments ``(a, b, radius)`` to keep a groove
    off: the gate, the pipe (its tube's radius) and the mouth (its cup's
    rim), or None."""
    if chan is None:
        return None
    from . import channel as _channel
    fr = chan["frame"]
    tube = chan["tube_out"]
    zs = [chan["z0"] + (chan["throat"] - chan["z0"]) * i / 60 for i in range(61)]
    pts = [fr.point(_channel.axis_at(chan, z), z) for z in zs]
    segs = [(a, b, tube) for a, b in zip(pts, pts[1:])]
    gate = [fr.point(chan["t_pipe"] - (chan["t_pipe"] - chan["t_cav"]) * i / 6,
                     chan["gate_z"]) for i in range(7)]
    segs += [(a, b, tube) for a, b in zip(gate, gate[1:])]
    top = pts[-1]
    rim = chan.get("mouth_r", tube) + (tube - chan["bore_r"])
    segs.append((top, Vector((top.x, top.y, chan["apex"] + 1.0)), rim))
    return segs


def _add_wing_grooves(half_a, half_b, master, props, ai, mn, mx, coll, off, bolt_zs,
                      offset, parting=None, chan=None):
    """Tongue & Groove along a 2-piece mold's wing: the tongue on half_a's face,
    the groove in half_b (the keyed piece keeps the +axis side of the seam, as
    with the keys); one contour round the whole wing, following a contoured
    parting. Returns how many runs were cut."""
    dims = _groove_dims(props)
    if dims is None:
        return 0
    h = next(i for i in range(3) if i != ai and i != 2)
    center = (mn + mx) * 0.5
    seam_flat = center[ai] + off
    n_mate = Vector((0.0, 0.0, 0.0)); n_mate[ai] = -1.0
    width = max(getattr(props, "wing_width", 8.0), 2.0)
    cut = parting.cutter if parting is not None else None
    cut_top = util.world_bbox(cut)[1][ai] + 10.0 if cut is not None else 0.0
    down = Vector((0.0, 0.0, 0.0)); down[ai] = -1.0

    def point(u, z):
        p = center.copy()
        p[h] = u
        p.z = z
        p[ai] = seam_flat
        if cut is not None:                     # parting_at, with the bbox read once
            o = p.copy(); o[ai] = cut_top
            hit, loc, _n, _i = cut.ray_cast(o, down)
            if hit:
                p[ai] = loc[ai]
        return p
    return _groove_seam(half_a, half_b, _model_bvh(master), dims, point, n_mate,
                        (mn[h] - 2.0, mx[h] + 2.0), (mn.z - 2.0, mx.z + 2.0),
                        offset + width * 0.5, _chan_axis(chan), coll, "MF_wgr")


def _add_radial_wing_grooves(parts, center, mn, mx, props, coll, n, master, bolt_zs,
                             offset, chan=None):
    """Tongue & Groove along each radial seam's flange: the tongue on wedge k,
    the groove in wedge k - 1 (as with the radial keys). Returns how many runs
    were cut."""
    dims = _groove_dims(props)
    if dims is None:
        return 0
    width = max(getattr(props, "wing_width", 8.0), 2.0)
    bvh = _model_bvh(master)
    far = max(mx.x - mn.x, mx.y - mn.y) + 5.0
    axis = _chan_axis(chan) if chan is not None and chan["frame"].multipart else None
    done = 0
    for k in range(n):
        theta = 2.0 * math.pi * k / n
        d = Vector((math.cos(theta), math.sin(theta), 0.0))
        nrm = Vector((-math.sin(theta), math.cos(theta), 0.0))   # into wedge k

        def point(u, z, d=d):
            return Vector((center.x, center.y, z)) + d * u
        done += _groove_seam(parts[k], parts[(k - 1) % n], bvh, dims, point, -nrm,
                             (0.0, far), (mn.z - 2.0, mx.z + 2.0), offset + width * 0.5,
                             axis if k == 0 else None, coll, f"MF_rwgr{k}_")
    return done


def _record_wing_grooves(props, done):
    """Keep the Tongue & Groove count for the build result, and tell the user
    when the wing had no room for one."""
    try:
        props.wing_grooves_cut = done
    except Exception:
        pass
    if done == 0:
        from . import build
        build.wing_note(props, "the wings had no room for a tongue and groove "
                               "(too thin or too narrow) - none was cut")


def cut_horizontal(parts, coll, hz):
    """Back-compat: single horizontal seam (Top/Bottom stack)."""
    return cut_stack(parts, coll, [hz])


def cut_stack(parts, coll, seam_zs):
    """Cut every piece at each seam height into stacked LEVELS, each printing
    shorter (the XL-mold / Printer Fit workflow). The bolted flange rings welded
    on before the vertical split provide the mating lip on both sides of every
    seam. Seams outside a piece's z-range are skipped for that piece; a piece
    with no seam inside it is kept as-is.

    Naming: one seam keeps the classic ``_Bot``/``_Top``; more levels are
    numbered ``_S1`` (bottom) up to ``_Sn`` (top), so files sort in stack order."""
    zs = sorted(seam_zs)
    out = []
    for part in parts:
        mn, mx = util.world_bbox(part)
        cuts = [z for z in zs if mn.z + 0.2 < z < mx.z - 0.2]
        if not cuts:
            out.append(part)
            continue
        base = part.name
        size = mx - mn
        big = max(size.x, size.y, size.z) * 2.0 + 10.0
        cen = (mn + mx) * 0.5
        bounds = [mn.z - 5.0] + cuts + [mx.z + 5.0]
        levels = []
        for i in range(len(bounds) - 1):
            z0, z1 = bounds[i], bounds[i + 1]
            seg = util.duplicate_object(part, "MF_seg", coll)
            slab = util.add_box("MF_hcut",
                                Vector((cen.x, cen.y, (z0 + z1) * 0.5)),
                                Vector((big, big, z1 - z0)), coll)
            util.boolean(seg, slab, 'INTERSECT')
            util.remove_object(slab)
            util.remove_small_islands(seg)
            levels.append(seg)
        util.remove_object(part)
        if len(levels) == 2:
            levels[0].name, levels[1].name = base + "_Bot", base + "_Top"
        else:
            for i, seg in enumerate(levels):
                seg.name = f"{base}_S{i + 1}"
        out.extend(levels)
    return out


# --- Radial multi-part split (3-4 wedges around the vertical axis) ---------- #

def _split_radial(mold, master, props, coll, wall, n, center=None, wing_offset=0.0,
                  wing_chan=None):
    """Carve the mold into ``n`` equal wedges around the vertical axis through its
    centre. Each wedge is the mold intersected with a pie-slice prism; intersecting
    two watertight solids keeps each wedge watertight. Adjacent wedges then get a
    best-effort registration pin straddling their shared seam.

    ``center`` defaults to the (winged) mold's bbox centre, but the caller passes the
    clamp wings' centre so the seams cut exactly through the wings."""
    mn, mx = util.world_bbox(mold)
    if center is None:
        center = (mn + mx) * 0.5
    big = max(mx.x - mn.x, mx.y - mn.y) * 2.0 + 10.0
    z0, z1 = mn.z - 1.0, mx.z + 1.0
    labels = "ABCDEFGH"

    parts = []
    for k in range(n):
        a0 = 2.0 * math.pi * k / n
        a1 = 2.0 * math.pi * (k + 1) / n
        cutter = _pie_prism(center, big, z0, z1, a0, a1, coll)
        part = util.duplicate_object(mold, f"MF_Mold_{labels[k]}", coll)
        util.boolean(part, cutter, 'INTERSECT')
        util.remove_object(cutter)
        util.remove_small_islands(part)
        parts.append(part)
    util.remove_object(mold)

    for part in parts:
        if not part.data.polygons:
            raise RuntimeError("Radial split produced an empty wedge.")

    # Winged seams register via the bolted flange lips, so pins are only needed
    # when wings are off (mirrors the two-part rule).
    if props.key_count > 0 and not getattr(props, "wings", False):
        _add_radial_keys(parts, center, mn, mx, props, wall, coll, n)
    # Wing Alignment up each seam's flange. ``radial_bolt_zs`` stays None when the
    # wings were not built (off, or rolled back), so there is nothing to key onto.
    bolt_zs = getattr(props, "radial_bolt_zs", None)
    if (getattr(props, "wings", False) and bolt_zs is not None
            and getattr(props, "wing_keys", 'NONE') not in ('NONE', 'GROOVE')):
        _record_wing_keys(props, _add_radial_wing_keys(
            parts, center, mn, mx, props, coll, n, master, bolt_zs, wing_offset,
            chan=wing_chan))
    if (getattr(props, "wings", False) and bolt_zs is not None
            and getattr(props, "wing_keys", 'NONE') == 'GROOVE'):
        _record_wing_grooves(props, _add_radial_wing_grooves(
            parts, center, mn, mx, props, coll, n, master, bolt_zs, wing_offset,
            chan=wing_chan))
    return parts


def _record_wing_keys(props, placed):
    """Keep the wing key count for the build result, and tell the user when keys
    were asked for but none fit."""
    try:
        props.wing_keys_placed = placed
    except AttributeError:
        pass
    if not placed:
        from . import build
        build.wing_note(props, "no wing alignment keys fit on these clamp wings "
                               "(the wing lip is too thin or too narrow) - the "
                               "bolts alone align the pieces")


def _pie_prism(center, big, z0, z1, a0, a1, coll):
    """A triangular vertical prism spanning the angular sector [a0, a1] around the
    vertical axis through ``center``. The sector is < 180 deg (n >= 3), so a triangle
    from the axis out to two far points (radius ``big`` >> mold) covers every mold
    point in that wedge; the straight chord falls well outside the mold."""
    cx, cy = center.x, center.y
    p0 = (cx + big * math.cos(a0), cy + big * math.sin(a0))
    p1 = (cx + big * math.cos(a1), cy + big * math.sin(a1))
    bm = bmesh.new()
    ab = bm.verts.new((cx, cy, z0))
    ab0 = bm.verts.new((p0[0], p0[1], z0))
    ab1 = bm.verts.new((p1[0], p1[1], z0))
    at = bm.verts.new((cx, cy, z1))
    at0 = bm.verts.new((p0[0], p0[1], z1))
    at1 = bm.verts.new((p1[0], p1[1], z1))
    bm.faces.new((ab, ab1, ab0))          # bottom
    bm.faces.new((at, at0, at1))          # top
    bm.faces.new((ab, ab0, at0, at))      # side along a0
    bm.faces.new((ab0, ab1, at1, at0))    # outer arc chord
    bm.faces.new((ab1, ab, at, at1))      # side along a1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return util.new_mesh_object("MF_pie", bm, coll)


def _add_radial_keys(parts, center, mn, mx, props, wall, coll, n):
    """A vertical registration pin straddling each radial seam: a ridge on one wedge
    seating into a groove on its neighbour, so banded-together wedges can't shift
    sideways. Best-effort — a pin that can't be seated in the wall is skipped (the
    overlap probe), so it never floats. The mold is at the origin here, so ray casts
    and placements use world coordinates directly (matrix_world is identity)."""
    zc = (mn.z + mx.z) * 0.5
    half_z = (mx.z - mn.z) * 0.5
    key_r = min(props.key_radius, max(wall * 0.45, 0.2))
    reach = max(mx.x - mn.x, mx.y - mn.y) + 10.0
    eps = math.radians(4.0)
    depth = min(half_z * 1.4, max(wall * 3.0, 3.0))

    for k in range(n):
        theta = 2.0 * math.pi * k / n            # seam shared by wedge k and k-1
        a = parts[k]
        b = parts[(k - 1) % n]
        # Probe just *inside* wedge a (angle + eps) to find its outer wall radius.
        ca, sa = math.cos(theta + eps), math.sin(theta + eps)
        origin = Vector((center.x + ca * reach, center.y + sa * reach, zc))
        hit, loc, _nrm, _idx = a.ray_cast(origin, Vector((-ca, -sa, 0.0)))
        if not hit:
            continue
        r_hit = math.hypot(loc.x - center.x, loc.y - center.y)
        r = max(r_hit - wall * 0.9, r_hit * 0.5)
        # The pin sits ON the seam plane (angle theta), inside the wall, mid-height.
        c = Vector((center.x + math.cos(theta) * r,
                    center.y + math.sin(theta) * r, zc))
        pin = util.add_cone("MF_rkey", c, key_r, key_r, depth, 'Z', coll)

        probe = util.duplicate_object(pin, "MF_rtest", coll)
        util.boolean(probe, a, 'INTERSECT')
        seated = bool(probe.data.polygons)
        util.remove_object(probe)
        if not seated:
            util.remove_object(pin)
            continue

        socket = util.duplicate_object(pin, "MF_rsock", coll)
        a_bak, b_bak = a.data.copy(), b.data.copy()
        try:
            util.boolean(a, pin, 'UNION')          # ridge on wedge a
            util.boolean(b, socket, 'DIFFERENCE')  # groove in neighbour b
            if not (util.part_is_valid(a)[0] and util.part_is_valid(b)[0]):
                raise RuntimeError("registration pin would break a wedge")
            for bak in (a_bak, b_bak):
                if bak.users == 0:
                    bpy.data.meshes.remove(bak)
        except Exception:                          # roll back; a key never breaks a wedge
            for obj, bak in ((a, a_bak), (b, b_bak)):
                cur = obj.data
                obj.data = bak
                if cur.users == 0:
                    bpy.data.meshes.remove(cur)
        finally:
            util.remove_object(pin)
            util.remove_object(socket)
