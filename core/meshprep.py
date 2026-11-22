"""Mesh preparation: heal, decimate, voxel remesh, and centering."""

import math

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils import geometry as mgeo
from mathutils.kdtree import KDTree

from . import constants as C
from . import util


def heal(obj):
    """Merge doubles, drop loose geometry, and make normals consistent/outward."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def ensure_outward_normals(obj):
    """Make face normals consistent and outward — Solidify grows along normals,
    so this guarantees the shell goes outward even when Heal is disabled."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def decimate(obj, ratio):
    mod = obj.modifiers.new("mf_decimate", 'DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = ratio
    util.apply_all_modifiers(obj)


def voxel_remesh(obj, voxel_size):
    # Safety net: never voxel a mesh so finely relative to its bounding box that the
    # grid explodes and exhausts memory. A degenerate input (e.g. a Solidify spike
    # flung millions of units out) would otherwise OOM the whole process here. Legit
    # fine molds (a few hundred voxels across) stay far under the cap.
    mn, mx = util.world_bbox(obj)
    longest = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z, 1e-4)
    if not math.isfinite(longest):
        longest = 1e9
    voxel_size = max(voxel_size, longest / C.REMESH_MAX_SPAN_VOXELS)
    mod = obj.modifiers.new("mf_remesh", 'REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = voxel_size
    util.apply_all_modifiers(obj)


def center_object(obj):
    """Move the object so its bounding-box center sits at the world origin,
    baking the transform into the mesh data."""
    mn, mx = util.world_bbox(obj)
    center = (mn + mx) * 0.5
    obj.matrix_world = Matrix.Translation(-center) @ obj.matrix_world
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    obj.data.update()


def _aspect(face):
    """How needle-like a face is: longest edge squared over area (about 2.3
    for an even triangle, in the hundreds for a sliver)."""
    area = face.calc_area()
    longest = max(e.calc_length() for e in face.edges)
    return longest * longest / max(area, 1e-12)


def _loops(edges):
    """Order boundary edges into closed loops of vertices, or None."""
    nxt = {}
    for e in edges:
        a, b = e.verts
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in nxt.values()):
        return None                       # a pinch: not a clean outline
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            a, b = nxt[cur]
            nx = b if a is prev else a
            if nx is start:
                break
            if nx in seen:
                return None
            loop.append(nx)
            seen.add(nx)
            prev, cur = cur, nx
        loops.append(loop)
    return loops


def _inside(pt, polys):
    """Even-odd test of a 2D point against several closed outlines."""
    x, y = pt
    inside = False
    for poly in polys:
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


def _fill(bm, loops, z):
    """Fill the closed outlines ``loops`` (lists of BMVerts, all at height z)
    with an even mesh of triangles facing down: a constrained Delaunay
    triangulation over the outline points plus a staggered grid of points
    inside it, clear of the edge. Holes (an outline inside another) stay
    open. Returns the number of triangles made."""
    pts2 = [[(v.co.x, v.co.y) for v in lp] for lp in loops]
    area = max(abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                       - poly[(i + 1) % len(poly)][0] * poly[i][1]
                       for i in range(len(poly)))) * 0.5 for poly in pts2)
    step = min(max(math.sqrt(max(area, 1.0) / 900.0), 0.6), 5.0)
    xs = [p[0] for lp in pts2 for p in lp]
    ys = [p[1] for lp in pts2 for p in lp]
    bverts = [v for lp in loops for v in lp]
    kd = KDTree(len(bverts))
    for i, v in enumerate(bverts):
        kd.insert(Vector((v.co.x, v.co.y, 0.0)), i)
    kd.balance()
    interior = []
    y, row = min(ys) + step * 0.5, 0
    while y < max(ys):
        x = min(xs) + step * (0.5 + 0.5 * (row % 2))
        while x < max(xs):
            if _inside((x, y), pts2) and kd.find(Vector((x, y, 0.0)))[2] > 0.6 * step:
                interior.append((x, y))
            x += step
        y += step * 0.866
        row += 1
    coords = [Vector(p) for lp in pts2 for p in lp] + [Vector(p) for p in interior]
    edges, base = [], 0
    for lp in loops:
        n = len(lp)
        edges += [(base + i, base + (i + 1) % n) for i in range(n)]
        base += n
    vout, _eout, fout, orig_v = mgeo.delaunay_2d_cdt(coords, edges, [], 0, 1e-7)[:4]
    nb = len(bverts)
    vmap = {}
    for k, origs in enumerate(orig_v):
        if len(origs) > 1:
            raise RuntimeError("outline points merged")
        if origs and origs[0] < nb:
            vmap[k] = bverts[origs[0]]
    made = 0
    for tri in fout:
        c = sum((vout[i] for i in tri), Vector((0.0, 0.0))) / len(tri)
        if not _inside((c.x, c.y), pts2):
            continue
        for i in tri:
            if i not in vmap:
                co = vout[i]
                vmap[i] = bm.verts.new((co.x, co.y, z))
        vs = [vmap[i] for i in tri]
        if len(set(vs)) < 3:
            continue
        bm.faces.new(list(reversed(vs)))      # counter-clockwise from above: face down
        made += 1
    return made


def fix_flat_bottom(obj, tol=0.3, only_if_bad=False, scale=1.0):
    """Rebuild a model's flat bottom as an even triangle mesh.

    A boolean cut leaves the cut face as one big polygon, often stored as long
    needle-thin triangles that fan across it: every later boolean on it (the
    Locking Base's plinth, the base plate, the shell) has to slice those
    slivers, and can fail. The bottom - the faces facing down within ``tol``
    of the lowest point - is levelled to that lowest height and refilled with
    an even mesh inside the same outline (holes in it, a hollow underside,
    stay open). If that outline is not clean, or there are open or doubled
    edges within 2 mm of the bottom, the model is sliced flat just above them
    instead - the walls there give a clean outline - and that is filled.

    With ``only_if_bad`` nothing is touched unless the bottom is stored as
    needle triangles, its outline is broken, or it has open edges near it. Returns ``(changed, note)``; the mesh is left as it was
    if the result is not at least as watertight as before. Its sizes are in
    millimetres: ``scale`` is the millimetres per Blender unit (the scene's, for
    the user's own model; the build's working copy is already in mm)."""
    mw = Matrix.Scale(scale, 4) @ obj.matrix_world
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        bm.transform(mw)
        bm.normal_update()
        if not bm.verts:
            return False, ""
        zmin = min(v.co.z for v in bm.verts)
        cand = {f for f in bm.faces
                if f.normal.z < -0.95 and all(v.co.z <= zmin + tol for v in f.verts)}
        if not cand:
            return False, ""
        # connected regions of bottom faces
        regions, seen = [], set()
        for f in cand:
            if f in seen:
                continue
            stack, reg = [f], []
            seen.add(f)
            while stack:
                cf = stack.pop()
                reg.append(cf)
                for e in cf.edges:
                    for lf in e.link_faces:
                        if lf in cand and lf not in seen:
                            seen.add(lf)
                            stack.append(lf)
            regions.append(reg)
        total = sum(f.calc_area() for reg in regions for f in reg)
        regions = [r for r in regions
                   if sum(f.calc_area() for f in r) >= max(1.0, 0.05 * total)]
        if not regions:
            return False, ""
        # badly meshed: much of it stored as needle triangles - what a boolean
        # cut becomes once triangulated (an STL round trip). One clean polygon
        # for the whole bottom is left alone: booleans handle it well.
        bad_area = 0.0
        n_small = n_bad = 0
        for f in (f for r in regions for f in r):
            if len(f.verts) > 4:
                continue
            n_small += 1
            if _aspect(f) > 50.0:
                bad_area += f.calc_area()
                n_bad += 1
        outlines = []
        for reg in regions:
            regset = set(reg)
            border = {e for f in reg for e in f.edges
                      if sum(1 for lf in e.link_faces if lf in regset) == 1}
            outlines.append(_loops(border))
        # open or doubled edges just above the bottom (within 2 mm - what a
        # Locking Base's plinth covers anyway): slice above them too
        low_defects = [max(v.co.z for v in e.verts) for e in bm.edges
                       if not e.is_manifold and max(v.co.z for v in e.verts) <= zmin + 2.0]
        broken = low_defects or any(lp is None for lp in outlines)
        if only_if_bad and not broken and (n_bad == 0 or (bad_area < 0.15 * total
                                                          and n_bad < 0.3 * n_small)):
            return False, ""
        nm0 = sum(1 for e in bm.edges if not e.is_manifold)
        before = sum(len(r) for r in regions)
        lift, cut, made = 0.0, 0.0, 0
        if all(lp is not None for lp in outlines) and not low_defects:
            for reg, loops in zip(regions, outlines):
                on_loop = {v for lp in loops for v in lp}
                verts = {v for f in reg for v in f.verts}
                for v in verts:
                    lift = max(lift, v.co.z - zmin)
                    v.co.z = zmin
                bmesh.ops.delete(bm, geom=list(reg), context='FACES_ONLY')
                stale = [v for v in verts - on_loop if v.is_valid and not v.link_faces]
                if stale:
                    bmesh.ops.delete(bm, geom=stale, context='VERTS')
                loose = [e for e in bm.edges if e.is_valid and not e.link_faces]
                if loose:
                    bmesh.ops.delete(bm, geom=loose, context='EDGES')
                made += _fill(bm, loops, zmin)
        else:
            # The outline has dead ends or touches itself: slice the model flat
            # just above the bottom faces, where the walls are clean, and fill
            # that outline.
            ztop = max(v.co.z for r in regions for f in r for v in f.verts)
            zc = min(ztop + 0.02, zmin + tol + 0.05)
            if low_defects:
                zc = max(zc, max(low_defects) + 0.05)
            res = bmesh.ops.bisect_plane(
                bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                plane_co=(0.0, 0.0, zc), plane_no=(0.0, 0.0, 1.0), clear_inner=True)
            cut_edges = {g for g in res["geom_cut"] if isinstance(g, bmesh.types.BMEdge)
                         and len(g.link_faces) == 1}
            loops = _loops(cut_edges)
            if not loops:
                raise RuntimeError("the bottom's outline is not one clean loop even "
                                   "when sliced - heal or remesh the model first")
            loose = [e for e in bm.edges if not e.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context='EDGES')
            lv = [v for v in bm.verts if not v.link_edges]
            if lv:
                bmesh.ops.delete(bm, geom=lv, context='VERTS')
            made = _fill(bm, loops, zc)
            cut = zc - zmin
        if not made:
            return False, ""
        bm.normal_update()
        nm1 = sum(1 for e in bm.edges if not e.is_manifold)
        if nm1 > nm0:
            raise RuntimeError("the rebuilt bottom does not close")
        bm.transform(mw.inverted())
        bm.to_mesh(obj.data)
        obj.data.update()
    except Exception as exc:
        return False, f"the flat bottom could not be rebuilt ({exc})"
    finally:
        bm.free()
    if cut > 0.0:
        how = f", sliced {cut:.2f} mm up where its outline was broken"
    elif lift > 0.005:
        how = f", levelled by up to {lift:.2f} mm"
    else:
        how = ""
    return True, (f"rebuilt the model's flat bottom: {before} faces became {made} even "
                  f"triangles{how}")


def _islands(bm):
    """The face-connected pieces of ``bm``, as lists of faces."""
    seen, out = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        seen.add(f)
        stack, faces = [f], []
        while stack:
            g = stack.pop()
            faces.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        out.append(faces)
    return out


def _span(verts):
    """Bounding-box diagonal of some vertices."""
    xs, ys, zs = zip(*(v.co[:] for v in verts))
    return math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def fill_small_holes(obj, hole_span=0.1):
    """Fill the small holes in ``obj``: open outlines of at most 12 edges, or
    larger ones smaller than ``hole_span`` of the model's size. A big opening
    (a hollow underside, an open cup) is left open. Returns how many were
    filled."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        if not bm.faces:
            return 0
        size = _span(bm.verts)
        open_edges = {e for e in bm.edges if len(e.link_faces) == 1}
        small = []
        while open_edges:                       # one outline at a time
            e = open_edges.pop()
            outline, stack = [e], [e]
            while stack:
                for v in stack.pop().verts:
                    for x in v.link_edges:
                        if x in open_edges:
                            open_edges.discard(x)
                            outline.append(x)
                            stack.append(x)
            if (len(outline) <= 12
                    or _span({v for x in outline for v in x.verts}) < hole_span * size):
                small.append(outline)
        filled = 0
        for outline in small:
            if bmesh.ops.holes_fill(bm, edges=outline, sides=0)["faces"]:
                filled += 1
        if filled:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            bm.to_mesh(obj.data)
            obj.data.update()
        return filled
    finally:
        bm.free()


def clean_model(obj, scale=1.0, fill_holes=True, hole_span=0.1, fragment_span=0.02):
    """Repair the faults that keep a model from being one clean solid, in place,
    and say what was done. ``scale`` is millimetres per unit (tolerances are mm).

    - weld vertices that sit on the same spot (an STL stores every triangle's
      corners separately; a seam that was never joined stays open),
    - delete zero-area faces, faces that duplicate another one exactly, and
      loose edges and vertices,
    - drop stray fragments: pieces under ``fragment_span`` of the model's size
      (specks, single triangles left floating by an export or a boolean),
    - fill small holes: open outlines of at most 12 edges, or larger ones
      smaller than ``hole_span`` of the model (a big opening such as a hollow
      underside is left open),
    - make the face normals consistent and pointing out.

    Returns ``(counts, note)``: a dict of what changed, and a short sentence
    for the build notes ("" when the model was already clean)."""
    import collections
    tol = 1e-4 / max(scale, 1e-12)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    counts = dict(welded=0, degenerate=0, duplicates=0, loose=0, fragments=0, holes=0)
    try:
        n = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=tol)
        counts["welded"] = n - len(bm.verts)

        n = len(bm.faces)
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=tol * 0.1)
        bm.faces.ensure_lookup_table()
        counts["degenerate"] = max(n - len(bm.faces), 0)

        groups = collections.defaultdict(list)
        for f in bm.faces:
            groups[frozenset(f.verts)].append(f)
        dup = [f for fs in groups.values() if len(fs) > 1 for f in fs[1:]]
        if dup:
            bmesh.ops.delete(bm, geom=dup, context='FACES_ONLY')
            counts["duplicates"] = len(dup)

        loose_e = [e for e in bm.edges if not e.link_faces]
        if loose_e:
            bmesh.ops.delete(bm, geom=loose_e, context='EDGES')
        loose_v = [v for v in bm.verts if not v.link_faces]
        if loose_v:
            bmesh.ops.delete(bm, geom=loose_v, context='VERTS')
        counts["loose"] = len(loose_e) + len(loose_v)

        if bm.faces:
            pieces = _islands(bm)
            size = _span(bm.verts)
            biggest = max(len(fs) for fs in pieces)
            stray = [fs for fs in pieces if len(fs) < biggest
                     and _span({v for f in fs for v in f.verts}) < fragment_span * size]
            if stray:
                faces = [f for fs in stray for f in fs]
                verts = {v for f in faces for v in f.verts}
                bmesh.ops.delete(bm, geom=list(verts), context='VERTS')
                counts["fragments"] = len(stray)

        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()
    if fill_holes:
        counts["holes"] = fill_small_holes(obj, hole_span)

    words = []
    if counts["fragments"]:
        words.append(f"dropped {counts['fragments']} stray fragment(s)")
    if counts["holes"]:
        words.append(f"filled {counts['holes']} hole(s)")
    if counts["welded"]:
        words.append(f"welded {counts['welded']} doubled vertices")
    bad = counts["degenerate"] + counts["duplicates"]
    if bad:
        words.append(f"deleted {bad} zero-area or duplicate face(s)")
    if counts["loose"]:
        words.append(f"removed {counts['loose']} loose edge(s)/vertices")
    note = ("cleaned up the model: " + ", ".join(words)) if words else ""
    return counts, note


def close_small_holes(obj, sides=12):
    """Close the tiny holes a sculpt or a scan leaves (open outlines of at
    most ``sides`` edges) - each keeps a boolean from making the model one
    clean solid. Returns how many were closed."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        open_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if not open_edges:
            return 0
        made = bmesh.ops.holes_fill(bm, edges=open_edges, sides=sides)["faces"]
        if not made:
            return 0
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        obj.data.update()
        return len(made)
    finally:
        bm.free()
