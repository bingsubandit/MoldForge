"""Inner cores: removable pieces that form a hole, a blind hole, a pocket or a
hollow inside the cast - shapes the outer split alone cannot release.

You model the core as its own mesh (a cylinder in a blind hole, the shape of
an undercut pocket) and mark it (Mark as Core: it moves to the markers
collection as ``MF_Core``). Generate turns each into a printable core part:
the core itself, a square stem (it cannot turn) out along its pull direction
through the mold wall, and a handle outside. The pull direction is the axis
along which the stem crosses the least of the model - out through a hole's
opening - or the one chosen in Cores.

* Direct mold: the core's pocket and the stem's channel are cut out of the
  mold, opened by the fit clearance; the core slides in before the pour.
* Pour box: the printed positive carries the core and its stem, so the
  silicone forms the channel the core slides into (and no thin silicone pin
  that would tear), and the shell gets a hole for the stem.
"""

import math

import bpy
import bmesh
from mathutils import Matrix, Vector

from . import util

PREFIX = "MF_Core"

AXES = {
    '+Z': Vector((0.0, 0.0, 1.0)), '-Z': Vector((0.0, 0.0, -1.0)),
    '+X': Vector((1.0, 0.0, 0.0)), '-X': Vector((-1.0, 0.0, 0.0)),
    '+Y': Vector((0.0, 1.0, 0.0)), '-Y': Vector((0.0, -1.0, 0.0)),
}


def core_objects():
    """The user's core meshes (markers collection)."""
    coll = bpy.data.collections.get(util.MARKER_COLLECTION)
    if coll is None:
        return []
    return [o for o in coll.objects if o.name.startswith(PREFIX) and o.type == 'MESH']


def user_cores(coll, home=None, scale=1.0):
    """Copies of the core meshes in build space (the build is centred on the
    origin: ``home`` is the model's centre in build space, and ``scale`` the
    millimetres per Blender unit the build runs at)."""
    out = []
    for o in core_objects():
        dup = bpy.data.objects.new("MF_coresrc", o.data.copy())
        coll.objects.link(dup)
        mw = Matrix.Scale(scale, 4) @ o.matrix_world
        if home is not None:
            mw = Matrix.Translation(-home) @ mw
        dup.data.transform(mw)
        dup.data.update()
        if dup.data.polygons:
            out.append(dup)
        else:
            util.remove_object(dup)
    return out


def _inside(obj, p):
    ok, loc, nrm, _i = obj.closest_point_on_mesh(p)
    return ok and (loc - p).dot(nrm) > 0.0


def _material_along(model, c, d, far):
    """How much of the model a ray from ``c`` along ``d`` passes through."""
    inside = _inside(model, c)
    p, total = c.copy(), 0.0
    for _ in range(32):
        hit, loc, _n, _i = model.ray_cast(p + d * 1e-3, d)
        if not hit:
            break
        if inside:
            total += (loc - p).length
        inside = not inside
        p = loc
    if inside:
        total += far                       # never left the model
    return total


def pull_direction(core, model, choice='AUTO'):
    """The axis the core is pulled out along: the chosen one, or the one whose
    way out crosses the least of the model (ties: up first, down last)."""
    if choice in AXES:
        return AXES[choice].copy()
    mn, mx = util.world_bbox(core)
    c = (mn + mx) * 0.5
    far = (util.world_bbox(model)[1] - util.world_bbox(model)[0]).length + 20.0
    order = ('+Z', '+X', '-X', '+Y', '-Y', '-Z')
    best = min(order, key=lambda k: (round(_material_along(model, c, AXES[k], far), 1),
                                     order.index(k)))
    return AXES[best].copy()


def _bar(a, b, half, coll, name):
    """A square bar from ``a`` to ``b``, ``half`` its half-width."""
    d = (b - a)
    ln = max(d.length, 1e-4)
    z = d / ln
    u = z.orthogonal().normalized()
    v = z.cross(u)
    rot = Matrix((u, v, z)).transposed().to_4x4()
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=(
        Matrix.Translation((a + b) * 0.5) @ rot
        @ Matrix.Diagonal((2.0 * half, 2.0 * half, ln, 1.0))))
    return util.new_mesh_object(name, bm, coll)


def _grown(obj, by, coll, name):
    """``obj`` grown outward by ``by`` (a clearance), as a new object."""
    from . import build
    import types
    props = types.SimpleNamespace(detail_voxel=max(by * 0.5, 0.15), voxel_safe=False)
    try:
        return build._dilate_solid(obj, by, name, props, coll)
    except Exception:
        dup = util.duplicate_object(obj, name, coll)
        return dup


def build_core(core, model, mold, props, coll, index, pour_box, positive=None):
    """Make the core part for one marked core and fit it to the mold.

    ``model`` is the model the mold was built around, ``mold`` the solid mold
    (direct: the mold itself; pour box: the jacket), ``positive`` the printed
    positive (pour box only). Returns ``(part or None, note)``."""
    clearance = max(getattr(props, "fit_clearance", 0.2), 0.05)
    d = pull_direction(core, model, getattr(props, "core_pull", 'AUTO'))
    cmn, cmx = util.world_bbox(core)
    c = (cmn + cmx) * 0.5
    ext = cmx - cmn
    across = sorted(abs(ext.dot(Vector(ax))) for ax in ((1, 0, 0), (0, 1, 0), (0, 0, 1))
                    if abs(Vector(ax).dot(d)) < 0.5)
    half = getattr(props, "core_stem", 0.0) * 0.5
    if half <= 0.0:
        half = min(max(min(across) * 0.3, 1.5), 5.0)
    # out through the mold's outside along d
    mmn, mmx = util.world_bbox(mold)
    far = (mmx - mmn).length + 20.0
    hit, loc, _n, _i = mold.ray_cast(c + d * far, -d)
    if not hit:
        return None, f"core {index}: the mold is not out along {_name(d)}"
    exit_t = (loc - c).dot(d)
    tip = c + d * (exit_t + 6.0)
    stem = _bar(c, tip, half, coll, "MF_corestem")
    handle = _bar(c + d * (exit_t + 1.0), c + d * (exit_t + 4.0), half + 4.0, coll,
                  "MF_corestem")
    part = util.duplicate_object(core, f"MF_Core_{index}", coll)
    try:
        util.boolean(part, stem, 'UNION')
        util.boolean(part, handle, 'UNION')
        ok, reason = util.part_is_valid(part)
        if not ok:
            raise RuntimeError(f"the core {reason}")
        if pour_box:
            # the positive carries the core and its stem (the silicone forms the
            # channel), the jacket gets a hole for the stem
            if positive is not None:
                carrier = util.duplicate_object(core, "MF_corecarrier", coll)
                st2 = _bar(c, c + d * (exit_t + 2.0), half, coll, "MF_corestem")
                util.boolean(carrier, st2, 'UNION')
                util.remove_object(st2)
                util.boolean(positive, carrier, 'UNION')
                util.remove_object(carrier)
            hole = _bar(c, tip + d * 2.0, half + clearance, coll, "MF_corestem")
            util.boolean(mold, hole, 'DIFFERENCE')
            util.remove_object(hole)
        else:
            pocket = _grown(core, clearance, coll, "MF_corepocket")
            chan = _bar(c, tip + d * 2.0, half + clearance, coll, "MF_corestem")
            util.boolean(pocket, chan, 'UNION')
            util.remove_object(chan)
            util.boolean(mold, pocket, 'DIFFERENCE')
            util.remove_object(pocket)
    except Exception as exc:
        util.remove_object(part)
        return None, f"core {index} skipped - {exc}"
    finally:
        util.remove_object(stem)
        util.remove_object(handle)
    part.name = f"MF_Core_{index}"
    return part, f"core {index}: pulled out along {_name(d)}"


def _name(d):
    for k, v in AXES.items():
        if (v - d).length < 1e-6:
            return k
    return "its axis"
