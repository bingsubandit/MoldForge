"""Scene units: convert MoldForge's millimetre size fields to Blender units.

Every size field in the panel is a length in **millimetres**. The geometry, however, is
built in Blender units, so the sizes have to be converted with the scene's actual unit
scale. Doing that (instead of assuming 1 Blender unit = 1 mm) is what makes the add-on
correct in an Imperial scene, or a metric scene whose unit isn't millimetres - not only
the "1 unit = 1 mm" convention.

``mm_per_unit`` is the single source of truth:

* No unit system (``system == 'NONE'``): the long-standing mold-maker convention, 1
  Blender unit = 1 mm.
* Metric or Imperial: a Blender unit is ``scale_length`` metres, i.e.
  ``scale_length * 1000`` mm. (Length is always metres internally; Imperial only changes
  how it's displayed, so the same formula holds.)
"""

import types


# Size fields that are lengths in millimetres. Everything else on the PropertyGroup
# (counts, ratios, flares, densities, the cached volumes) is NOT a length and is copied
# through untouched.
LENGTH_PROPS = frozenset({
    "wall_thickness", "shell_wall", "sprue_radius", "funnel_height", "vent_radius",
    "flange_width", "fit_clearance", "wing_width", "bolt_diameter",
    "wing_key_size", "wing_key_height", "wing_key_spacing", "cup_diameter", "cup_depth",
    "split_offset", "split_z_offset", "max_print_height", "support_clearance",
    "sprue_x", "sprue_y", "voxel_size",
    "lock_height", "lock_margin", "lock_tooth_depth", "lock_tolerance",
    "tray_wall", "tray_floor", "tray_margin", "tray_depth",
    "stamp_width", "stamp_relief", "core_wall",
    "screw_diameter", "screw_head_diameter", "screw_head_depth",
    "insert_diameter", "insert_depth",
    "channel_radius", "label_size", "label_depth",
    "wing_groove_width", "wing_groove_depth",
})


def mm_per_unit(scene):
    """Millimetres that one Blender unit represents in ``scene``.

    Most mold makers model with the "1 unit = 1 mm" convention, and Blender's untouched
    default scene is Metric / Unit Scale 1.0 / Meters - so that exact default is honoured
    as 1 unit = 1 mm (changing it would silently shrink everyone's molds 1000x). But once
    the scene is actually configured for real units - Imperial, a changed Unit Scale, or a
    specific metric Length unit (mm, cm, ...) - we take it at face value: a Blender unit is
    ``scale_length`` metres, i.e. ``scale_length * 1000`` mm (length is metres internally,
    so this holds for Imperial too). That's the bug fix: Imperial and non-mm metric scenes
    no longer pretend 1 unit = 1 mm.
    """
    us = getattr(scene, "unit_settings", None)
    if us is None or us.system == 'NONE':
        return 1.0
    s = us.scale_length
    if (us.system == 'METRIC' and abs(s - 1.0) < 1e-9
            and getattr(us, "length_unit", 'METERS') in ('METERS', 'ADAPTIVE')):
        return 1.0                          # untouched default metric scene -> convention
    return (s * 1000.0) if s > 0.0 else 1.0


def convention_mm(scene):
    """True when MoldForge reads 1 unit = 1 mm by convention (no unit system,
    or Blender's untouched default scene) rather than from units the user set."""
    us = getattr(scene, "unit_settings", None)
    if us is None or us.system == 'NONE':
        return True
    return (us.system == 'METRIC' and abs(us.scale_length - 1.0) < 1e-9
            and getattr(us, "length_unit", 'METERS') in ('METERS', 'ADAPTIVE'))


TINY_MM = 1.0     # a model under this by the convention was made in metres


def looks_like_metres(scene, obj):
    """True when ``obj`` would read as under a millimetre by the 1 unit = 1 mm
    convention: nobody molds that, so it was made in metres (a game asset, a
    scan, a model exported from a metre-based app). Blender itself already
    reads such a scene in metres - it shows the model as a few centimetres."""
    if obj is None or getattr(obj, "type", None) != 'MESH' or not obj.data.polygons:
        return False
    if not convention_mm(scene):
        return False
    big = world_size(obj)
    return 0.0 < big < TINY_MM


def world_size(obj):
    """``obj``'s largest world-space extent, from its CACHED bounding box (8
    corners). The panel asks on every redraw - on every mouse move over the
    sidebar - so it must never walk the mesh: a per-vertex scan here took
    0.3 s a redraw on a 160k-vertex model and made Blender crawl (0.46.5)."""
    from mathutils import Vector
    mw = obj.matrix_world
    pts = [mw @ Vector(c) for c in obj.bound_box]
    return max(max(q[i] for q in pts) - min(q[i] for q in pts) for i in range(3))


def read_as_metres(scene):
    """Set the scene to read 1 unit = 1 m, with lengths shown in millimetres
    (Metric, Unit Scale 1.0, Length Millimeters): Blender's own reading of a
    model made in metres, which MoldForge then follows."""
    us = scene.unit_settings
    us.system = 'METRIC'
    us.scale_length = 1.0
    us.length_unit = 'MILLIMETERS'


def units_per_mm(scene):
    """Blender units per millimetre (inverse of ``mm_per_unit``)."""
    mpu = mm_per_unit(scene)
    return (1.0 / mpu) if mpu > 0.0 else 1.0


def build_props(props, scene):
    """A plain snapshot of ``props`` for the build, with the sizes left in
    millimetres and ``build_scale`` set to the scene's millimetres per Blender
    unit. The build runs in millimetres - the panel's fields and the fixed
    clearances in the code alike - on copies scaled by ``build_scale``, and scales
    what it makes back to scene units (``pipeline.staged_build``). Converting only
    the fields to Blender units left those fixed sizes in metres in a
    1 unit = 1 m scene: a coaster's mold came out metres wide.

    Reads the field list from the PropertyGroup definition so it can't drift out of sync.
    """
    from .. import properties

    ns = types.SimpleNamespace()
    try:
        names = list(properties.MoldForgeProperties.__annotations__.keys())
    except Exception:
        names = list(LENGTH_PROPS)
    missing = object()
    for name in names:
        val = getattr(props, name, missing)
        if val is missing:
            continue            # absent -> let the build use its own getattr default
        setattr(ns, name, val)
    ns.build_scale = mm_per_unit(scene)
    ns.mm_per_unit = 1.0         # the build's volumes are mm3 (the label's ml/g)
    return ns


def to_ml(units_cubed, mpu):
    """Blender-unit volume -> millilitres, using ``mpu`` mm per unit."""
    return units_cubed * (mpu ** 3) / 1000.0
