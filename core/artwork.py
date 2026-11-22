"""Artwork for the stamp maker and the label: an SVG file or Curve/Text objects
turned into one filled, extruded mesh solid."""

import math

import bpy
from mathutils import Matrix

from . import util, meshprep


def svg_curves(path):
    """Import an SVG and return its curve objects (best effort across bundled
    importer states)."""
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_curve.svg(filepath=path)
    except Exception:
        try:
            import addon_utils
            addon_utils.enable("io_curve_svg")
            bpy.ops.import_curve.svg(filepath=path)
        except Exception as exc:
            raise ValueError(f"Could not import the SVG: {exc}")
    new = [o for o in bpy.data.objects if o not in before and o.type == 'CURVE']
    if not new:
        raise ValueError("The SVG imported no curves - export the artwork with "
                         "FILLED paths (in Inkscape: select all, Path > "
                         "Object to Path, and Stroke to Path for outlines).")
    return new


def design_to_solid(sources, thickness, coll):
    """Fill + extrude Curve/Text objects into ONE mesh solid of ``thickness``
    (centred on z=0), consuming nothing (works on evaluated copies)."""
    deps = bpy.context.evaluated_depsgraph_get()
    solid = None
    half = thickness * 0.5
    for src in sources:
        if src.type not in ('CURVE', 'FONT'):
            continue
        dup = src.copy()
        dup.data = src.data.copy()
        coll.objects.link(dup)
        if src.type == 'CURVE':
            try:
                dup.data.dimensions = '2D'
                dup.data.fill_mode = 'BOTH'
            except Exception:
                pass
        dup.data.extrude = half
        dup.data.bevel_depth = 0.0
        deps = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(
            dup.evaluated_get(deps), preserve_all_data_layers=False, depsgraph=deps)
        util.remove_object(dup)
        if not me.polygons:
            bpy.data.meshes.remove(me)
            continue
        me.transform(src.matrix_world)      # bake the source transform in place -
        ob = bpy.data.objects.new("MF_StampRelief", me)   # NEVER recentre per
        coll.objects.link(ob)               # shape (that piles an SVG's shapes
        if solid is None:                   # on top of each other)
            solid = ob
            solid.name = "MF_StampRelief"
        else:
            util.join_meshes(solid, ob)
    if solid is None:
        raise ValueError("The design has no filled area to engrave - use FILLED "
                         "shapes (a Text object, or an SVG with filled paths).")
    # Curve-to-mesh leaves the extrusion CAPS as separate faces duplicating the
    # wall vertices (6 islands, hundreds of non-manifold edges on a 2-shape
    # SVG): weld the duplicates into one closed shell per shape.
    import bmesh as _bmesh
    bm = _bmesh.new()
    bm.from_mesh(solid.data)
    _bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    _bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(solid.data)
    bm.free()
    # SVG curves often import with reversed winding; an inside-out solid used as
    # a boolean cutter consumes the whole pan. Make every shell face outward.
    meshprep.ensure_outward_normals(solid)
    # Auto-flatten: an imported SVG often carries a baked -90 degree X rotation
    # (and wild scales), leaving the design standing VERTICALLY - the engrave
    # would be garbage. The extrusion axis is the one whose extent matches the
    # known cutter thickness; rotate it onto Z.
    fmn, fmx = util.world_bbox(solid)
    ext = (fmx.x - fmn.x, fmx.y - fmn.y, fmx.z - fmn.z)
    thin = min(range(3), key=lambda i: abs(ext[i] - thickness))
    if thin == 0:
        solid.data.transform(Matrix.Rotation(math.radians(90.0), 4, 'Y'))
    elif thin == 1:
        solid.data.transform(Matrix.Rotation(math.radians(90.0), 4, 'X'))
    return solid
