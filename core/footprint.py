"""An object's footprint seen from above, as a 2D distance field.

The tray's hugging outlines (its outer wall, the cavity, the lift-off frame's
walls, tongue and groove) are all outlines at some distance out from where
the object stands. They come from one field here, so they are parallel and
never cross. The footprint is everything straight below any part of the
object, found by casting rays straight down over a fine grid, so a part that
bulges out above or below the middle is always inside the walls.
"""

import math

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import util


def _edt(target):
    """Distance (in cells) from every cell to the nearest ``target`` cell: an
    exact Euclidean distance transform, columns first, then rows."""
    h, w = target.shape
    big = float(h + w + 1)
    g = np.where(target, 0.0, big)
    for i in range(1, h):
        np.minimum(g[i], g[i - 1] + 1.0, out=g[i])
    for i in range(h - 2, -1, -1):
        np.minimum(g[i], g[i + 1] + 1.0, out=g[i])
    g2 = g * g
    js = np.arange(w, dtype=np.float64)
    dj2 = (js[:, None] - js[None, :]) ** 2
    out = np.empty((h, w))
    for i in range(h):
        out[i] = np.min(dj2 + g2[i][None, :], axis=1)
    return np.sqrt(out)


def _blur(f, sigma):
    """A Gaussian blur of ``f``, ``sigma`` in cells (edges held)."""
    r = int(math.ceil(3.0 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    g = np.pad(f, r, mode='edge')
    g = sum(k[t] * g[t:t + f.shape[0], :] for t in range(2 * r + 1))
    return sum(k[t] * g[:, t:t + f.shape[1]] for t in range(2 * r + 1))


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _contains(p, q):
    """Is point ``q`` inside polygon ``p`` (even-odd rule)?"""
    x, y = q
    xs, ys = p[:, 0], p[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    cross = (ys > y) != (yn > y)
    with np.errstate(divide='ignore', invalid='ignore'):
        xi = xs + (y - ys) * (xn - xs) / (yn - ys)
    return bool(np.count_nonzero(cross & (x < xi)) % 2)


class Footprint:
    """The footprint of ``obj`` (world space) on a grid fine enough for outlines
    up to ``reach`` out from it."""

    def __init__(self, obj, reach, max_cells=480, min_cell=0.25):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        if not bm.verts:
            bm.free()
            raise ValueError("the object is empty")
        co = np.array([v.co[:] for v in bm.verts])
        tree = BVHTree.FromBMesh(bm)
        mn, mx = co.min(axis=0), co.max(axis=0)
        ext = max(mx[0] - mn[0], mx[1] - mn[1])
        cell = max(min_cell, (ext + 2.0 * reach) / (max_cells - 8))
        pad = reach + 4.0 * cell
        self.cell = cell
        self.x0, self.y0 = mn[0] - pad, mn[1] - pad
        w = int(math.ceil((mx[0] - mn[0] + 2.0 * pad) / cell)) + 1
        h = int(math.ceil((mx[1] - mn[1] + 2.0 * pad) / cell)) + 1
        inside = np.zeros((h, w), dtype=bool)
        # every grid point with any of the object straight below it
        top, depth = mx[2] + 1.0, mx[2] - mn[2] + 2.0
        down = Vector((0.0, 0.0, -1.0))
        j0 = max(int((mn[0] - self.x0) / cell) - 1, 0)
        j1 = min(int((mx[0] - self.x0) / cell) + 2, w)
        i0 = max(int((mn[1] - self.y0) / cell) - 1, 0)
        i1 = min(int((mx[1] - self.y0) / cell) + 2, h)
        cast = tree.ray_cast
        o = Vector((0.0, 0.0, top))
        for i in range(i0, i1):
            o.y = self.y0 + i * cell
            row = inside[i]
            for j in range(j0, j1):
                o.x = self.x0 + j * cell
                if cast(o, down, depth)[0] is not None:
                    row[j] = True
        # and every vertex, so a spike thinner than a cell is not missed
        jj = np.clip(np.rint((co[:, 0] - self.x0) / cell).astype(int), 0, w - 1)
        ii = np.clip(np.rint((co[:, 1] - self.y0) / cell).astype(int), 0, h - 1)
        inside[ii, jj] = True
        bm.free()
        if not inside.any():
            raise ValueError("the object has no footprint")
        # signed distance (mm) from the footprint's edge, which runs midway
        # between the grid points inside and out: negative inside
        d_out = _edt(inside)
        d_in = _edt(~inside)
        # a light blur irons out the faint kinks an offset of a stair-stepped
        # pixel edge has (it moves the outlines by well under a tenth of a mm)
        self.f = _blur(np.where(inside, 0.5 - d_in, d_out - 0.5) * cell, 2.0)
        self.shape = (h, w)

    # -- outlines ----------------------------------------------------------

    def _point(self, key, level):
        f, cell = self.f, self.cell
        kind, i, j = key
        a = f[i, j]
        b = f[i, j + 1] if kind == 'h' else f[i + 1, j]
        t = 0.5 if b == a else min(max((level - a) / (b - a), 0.0), 1.0)
        x = self.x0 + (j + (t if kind == 'h' else 0.0)) * cell
        y = self.y0 + (i + (t if kind == 'v' else 0.0)) * cell
        return x, y

    def loops(self, offset):
        """The outlines ``offset`` mm out from the footprint (negative: in),
        counter-clockwise, outermost only (holes and islands inside them
        dropped), each an (n, 2) array."""
        f = self.f
        ins = f < offset
        a, b, c, d = ins[:-1, :-1], ins[:-1, 1:], ins[1:, 1:], ins[1:, :-1]
        mixed = (a | b | c | d) & ~(a & b & c & d)
        nxt = {}
        for i, j in zip(*np.nonzero(mixed)):
            i, j = int(i), int(j)
            corners = ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))   # CCW
            keys = (('h', i, j), ('v', i, j + 1), ('h', i + 1, j), ('v', i, j))
            inn = [bool(ins[p]) for p in corners]
            leave = [k for k in range(4) if inn[k] and not inn[(k + 1) % 4]]
            enter = [k for k in range(4) if not inn[k] and inn[(k + 1) % 4]]
            if len(leave) == 1:
                nxt[keys[leave[0]]] = keys[enter[0]]
            else:                                        # saddle: ask the middle
                centre = sum(f[p] for p in corners) * 0.25 < offset
                for k in leave:
                    nxt[keys[k]] = keys[(k + 1) % 4 if centre else (k + 3) % 4]
        loops = []
        seen = set()
        for start in nxt:
            if start in seen:
                continue
            ring, k = [], start
            while k not in seen and k in nxt:
                seen.add(k)
                ring.append(self._point(k, offset))
                k = nxt[k]
            if len(ring) >= 3:
                loops.append(self._tidy(np.array(ring)))
        outer = [p for p in loops if len(p) >= 3 and _area(p) > (2.0 * self.cell) ** 2]
        outer.sort(key=_area, reverse=True)
        kept = []
        for p in outer:
            if not any(_contains(q, p[0]) for q in kept):
                kept.append(p)
        return kept

    def _tidy(self, p):
        """Ease the grid's stair-steps out of an outline and drop points that
        crowd each other."""
        # even spacing first, so the smoothing acts the same all the way round
        seg = np.hypot(*(np.roll(p, -1, axis=0) - p).T)
        s = np.concatenate(([0.0], np.cumsum(seg)))
        total = s[-1]
        step = max(self.cell, 0.4)
        n = max(int(total / step), 8)
        t = np.linspace(0.0, total, n, endpoint=False)
        closed = np.vstack((p, p[:1]))
        p = np.column_stack((np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])))
        for _ in range(12):                    # Taubin: smooths without shrinking
            for lam in (0.5, -0.53):
                p = p + lam * (0.5 * (np.roll(p, 1, axis=0) + np.roll(p, -1, axis=0)) - p)
        return p

    def prism(self, offset, z0, z1, coll, name, single=False):
        """A solid with vertical walls along the outline ``offset`` mm out from
        the footprint, from z0 to z1. Returns ``(object, area)``; with
        ``single`` it must be one outline (or ValueError)."""
        loops = self.loops(offset)
        if not loops:
            raise ValueError("no outline")
        if single and len(loops) > 1:
            raise ValueError("the footprint is in pieces")
        bm = bmesh.new()
        for p in loops:
            bot = [bm.verts.new((x, y, z0)) for x, y in p]
            top = [bm.verts.new((x, y, z1)) for x, y in p]
            n = len(p)
            for k in range(n):
                m = (k + 1) % n
                bm.faces.new((bot[k], bot[m], top[m], top[k]))
            bm.faces.new(list(reversed(bot)))
            bm.faces.new(top)
        return util.new_mesh_object(name, bm, coll), sum(_area(p) for p in loops)
