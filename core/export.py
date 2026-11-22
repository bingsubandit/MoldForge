"""Binary STL export, written directly so it works in any context/headless."""

import os
import struct

import bpy
from mathutils import Matrix

from . import util


def export_stl(obj, filepath, scale=1.0):
    """Write ``obj`` (with its world transform applied) as a binary STL, its
    coordinates times ``scale``: STL has no units and slicers read millimetres,
    so the caller passes the scene's millimetres per Blender unit.

    A plain mesh is first made exactly what the file will hold
    (``util.finish_for_export``, kept only when it leaves it cleaner), so
    corners that land on one position where the part now sits can't pinch the
    STL. Positions come from ``util.stl_positions``, the numbers that check
    reads, so a part that checks clean writes clean."""
    if obj.type == 'MESH' and not obj.modifiers:
        util.finish_for_export(obj, scale)
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    me = eval_obj.to_mesh()
    try:
        me.calc_loop_triangles()
        pos = util.stl_positions(eval_obj, me, scale)   # evaluated mesh, in mm
        tris = me.loop_triangles

        with open(filepath, 'wb') as f:
            f.write(b'\x00' * 80)                       # 80-byte header
            f.write(struct.pack('<I', len(tris)))       # triangle count
            for tri in tris:
                p = [[float(c) for c in pos[i]] for i in tri.vertices]
                e1 = [p[1][k] - p[0][k] for k in range(3)]
                e2 = [p[2][k] - p[0][k] for k in range(3)]
                n = [e1[1] * e2[2] - e1[2] * e2[1],
                     e1[2] * e2[0] - e1[0] * e2[2],
                     e1[0] * e2[1] - e1[1] * e2[0]]
                ln = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5
                if ln > 0.0:
                    n = [c / ln for c in n]
                f.write(struct.pack('<3f', *n))
                for v in p:
                    f.write(struct.pack('<3f', *v))
                f.write(struct.pack('<H', 0))           # attribute byte count
    finally:
        eval_obj.to_mesh_clear()
    return filepath


def _safe_name(name):
    """Filesystem-safe filename stem — object names can hold path-significant
    characters (``/``, ``:`` …) that would break os.path.join."""
    cleaned = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return cleaned.strip("._") or "part"


def export_objects(objects, directory, scale=1.0):
    os.makedirs(directory, exist_ok=True)
    written = []
    for obj in objects:
        path = os.path.join(directory, f"{_safe_name(obj.name)}.stl")
        export_stl(obj, path, scale)
        written.append(path)
    return written
