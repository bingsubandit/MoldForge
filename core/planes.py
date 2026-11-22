"""Free split planes: cut the mold along planes the user places - any number,
at any position and angle - instead of the standard two-piece or radial split.

A split plane is an ordinary plane object (``MF_SplitPlane``) in the markers
collection: move and rotate it like anything else; regeneration keeps it.
With clamp wings on, every plane gets its own flange - the same rind of stock
just outside the mold wall the regular wings are cut from, clipped to a slab
along the plane - with bolt holes across it, so the pieces bolt together. A
direct mold's thick walls carry alignment keys on every cut face instead.
"""

import math
import string

import bpy
import bmesh
from mathutils import Matrix, Vector

from . import util

PREFIX = "MF_SplitPlane"


def plane_objects():
    """The user's split-plane objects (markers collection)."""
    coll = bpy.data.collections.get(util.MARKER_COLLECTION)
    if coll is None:
        return []
    return [o for o in coll.objects if o.name.startswith(PREFIX) and o.type == 'MESH']


def user_planes(home=None, scale=1.0):
    """``[(point, normal)]`` of the split planes, in build space (the build is
    centred on the origin: ``home`` is the model's centre in build space, and
    ``scale`` the millimetres per Blender unit the build runs at)."""
    out = []
    for o in plane_objects():
        mw = o.matrix_basis if o.parent is None else (
            o.parent.matrix_world @ o.matrix_parent_inverse @ o.matrix_basis)
        co = mw.translation.copy()
        n = (mw.to_3x3() @ Vector((0.0, 0.0, 1.0)))
        if n.length < 1e-9:
            continue
        co = co * scale
        if home is not None:
            co = co - home
        out.append((co, n.normalized()))
    return out


def _basis(n):
    u = n.orthogonal().normalized()
    return u, n.cross(u).normalized()


def _slab(co, n, thickness, size, coll, name="MF_pslab"):
    """A box ``thickness`` thick centred on the plane, ``size`` across."""
    u, v = _basis(n)
    rot = Matrix((u, v, n)).transposed().to_4x4()
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=(
        Matrix.Translation(co) @ rot @ Matrix.Diagonal((size, size, thickness, 1.0))))
    return util.new_mesh_object(name, bm, coll)


def _half_space(co, n, size, coll, name="MF_phalf"):
    """A box filling the +n side of the plane (``size`` across)."""
    u, v = _basis(n)
    rot = Matrix((u, v, n)).transposed().to_4x4()
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=(
        Matrix.Translation(co + n * (size * 0.5)) @ rot
        @ Matrix.Diagonal((size, size, size, 1.0))))
    return util.new_mesh_object(name, bm, coll)


def add_plane_flanges(mold, master, planes, props, coll, offset, width, thickness,
                      bolt_radius, funnels=None, under=None):
    """Weld a clamp flange along every plane onto the still-solid ``mold`` and
    drill bolt holes across it. Returns the number of bolt holes."""
    from . import build
    mn, mx = util.world_bbox(mold)
    big = (mx - mn).length * 3.0 + 20.0
    rind = build._wing_rind(master, offset, width, props, coll, funnels, under)
    try:
        for co, n in planes:
            slab = _slab(co, n, thickness, big, coll)
            wing = util.duplicate_object(rind, "MF_pwing", coll)
            util.boolean(wing, slab, 'INTERSECT')
            util.remove_object(slab)
            if wing.data.polygons:
                util.boolean(mold, wing, 'UNION')
            util.remove_object(wing)
        util.remove_small_islands(mold)
    finally:
        util.remove_object(rind)
    holes = 0
    count = build._effective_bolts(props)
    if count == 0 or width < 2.2 * bolt_radius:
        return 0
    far = (mx - mn).length + 20.0
    centre = (mn + mx) * 0.5
    for co, n in planes:
        c0 = centre - n * (centre - co).dot(n)          # the middle, on the plane
        u, v = _basis(n)
        pts = []
        for k in range(144):
            a = 2.0 * math.pi * k / 144
            d = u * math.cos(a) + v * math.sin(a)
            o = c0 + d * far
            hw, lw, _n1, _i1 = mold.ray_cast(o, -d)
            hm, lm, _n2, _i2 = master.ray_cast(o, -d)
            if not hw:
                pts.append(None)
                continue
            rw = (lw - c0).dot(d)
            rm = (lm - c0).dot(d) if hm else -far
            if rw - rm < offset + 0.6 * width:
                pts.append(None)                        # no flange standing out here
                continue
            pts.append(lw - d * (bolt_radius + width * 0.3))
        found = [q for q in pts if q is not None]
        if not found:
            continue
        perim = sum((pts[i] - pts[i - 1]).length for i in range(len(pts))
                    if pts[i] is not None and pts[i - 1] is not None)
        n_b = count if count else max(2, int(round(perim / 60.0)))
        spacing = max(perim / n_b, 4.0 * bolt_radius)
        placed, run, last = [], spacing, None
        for q in pts:
            if q is None:
                last = None
                continue
            if last is not None:
                run += (q - last).length
            last = q
            if run >= spacing and all((q - r).length >= spacing * 0.6 for r in placed):
                placed.append(q)
                run = 0.0
            if len(placed) >= n_b:
                break
        for q in placed:
            a_ = q - n * (thickness * 0.5 + 1.2)
            b_ = q + n * (thickness * 0.5 + 1.2)
            hole = util.add_tube("MF_pbolt", a_, b_, bolt_radius, coll)
            util.boolean(mold, hole, 'DIFFERENCE')
            util.remove_object(hole)
            holes += 1
    return holes


def _inside(obj, p):
    ok, loc, nrm, _i = obj.closest_point_on_mesh(p)
    return ok and (loc - p).dot(nrm) > 0.0


def _add_cut_keys(pos, neg, co, n, key_r, clearance, coll, count=3):
    """Ball keys across a cut: a bump on ``pos``'s cut face, a socket a hair
    bigger in ``neg``'s, where there is wall all round. Returns how many."""
    mn, mx = util.world_bbox(pos)
    u, v = _basis(n)
    corners = [Vector((x, y, z)) for x in (mn.x, mx.x) for y in (mn.y, mx.y)
               for z in (mn.z, mx.z)]
    us = [(c - co).dot(u) for c in corners]
    vs = [(c - co).dot(v) for c in corners]
    step = max(key_r * 1.5, 1.5)
    ring = [u * math.cos(2 * math.pi * k / 8) + v * math.sin(2 * math.pi * k / 8)
            for k in range(8)]
    cands = []
    a = min(us)
    while a <= max(us):
        b = min(vs)
        while b <= max(vs):
            p = co + u * a + v * b
            q = p + n * 0.3                              # just inside pos's cut face
            if (_inside(pos, q) and all(_inside(pos, q + d * (key_r + 1.5)) for d in ring)):
                cands.append(p)
            b += step
        a += step
    if not cands:
        return 0
    chosen = [max(cands, key=lambda p: (p - co).length)]
    while len(chosen) < count:
        nxt = max(cands, key=lambda p: min((p - c).length for c in chosen))
        if min((nxt - c).length for c in chosen) < key_r * 6:
            break
        chosen.append(nxt)
    for p in chosen:
        bump = util.add_sphere("MF_pkey", p, key_r, coll, subdiv=2)
        util.boolean(pos, bump, 'UNION')
        util.remove_object(bump)
        sock = util.add_sphere("MF_pkey", p, key_r + clearance, coll, subdiv=2)
        util.boolean(neg, sock, 'DIFFERENCE')
        util.remove_object(sock)
    return len(chosen)


def cut_by_planes(mold, planes, props, coll, wall, keys=True):
    """Cut ``mold`` by every plane in turn - each plane cuts every piece it
    crosses. Pieces are named MF_Mold_A, B, ... Returns ``(pieces, keys)``."""
    mn, mx = util.world_bbox(mold)
    big = (mx - mn).length * 3.0 + 20.0
    pieces = [mold]
    keys_made = 0
    key_r = min(max(wall * 0.35, 0.8), 3.0)
    clearance = max(getattr(props, "fit_clearance", 0.2), 0.05)
    for co, n in planes:
        nxt = []
        for piece in pieces:
            pmn, pmx = util.world_bbox(piece)
            ds = [(Vector((x, y, z)) - co).dot(n) for x in (pmn.x, pmx.x)
                  for y in (pmn.y, pmx.y) for z in (pmn.z, pmx.z)]
            if min(ds) > -0.05 or max(ds) < 0.05:
                nxt.append(piece)                       # the plane misses it
                continue
            pos = util.duplicate_object(piece, "MF_ppos", coll)
            neg = util.duplicate_object(piece, "MF_pneg", coll)
            hs = _half_space(co, n, big, coll)
            util.boolean(pos, hs, 'INTERSECT')
            util.boolean(neg, hs, 'DIFFERENCE')
            util.remove_object(hs)
            util.remove_small_islands(pos)
            util.remove_small_islands(neg)
            if not pos.data.polygons or not neg.data.polygons:
                util.remove_object(pos)
                util.remove_object(neg)
                nxt.append(piece)
                continue
            if keys and wall >= 2.5:
                keys_made += _add_cut_keys(pos, neg, co, n, key_r, clearance, coll)
            util.remove_object(piece)
            nxt.extend([pos, neg])
        pieces = nxt
    for name, piece in zip(string.ascii_uppercase, pieces):
        piece.name = f"MF_Mold_{name}"
        piece.data.name = piece.name
    return pieces, keys_made
