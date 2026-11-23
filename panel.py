"""Sidebar (N-panel) UI for MoldForge.

Three panels in the MoldForge tab, in the order the work happens:

``MoldForge``  the model you selected, the handful of choices that change from
              toy to toy, and the Generate button.
``Result``    appears after a build: what was made, the silicone and cast
              figures, Exploded Preview and Export.
``Advanced``  closed by default; every other setting, grouped by the part of the
              mold it shapes. Each group shows its current setting at the right of
              its header, so a closed group still tells you what it holds.

Labels are short on purpose: the sidebar is narrow and a label that does not fit
is cut off with an ellipsis, which is worse than a short word with a tooltip.
"""

import os

import bpy

from .core import constants as C
from .core import units
from .core import util as mf_util
from .properties import mold_caps

_VERSION = None


def _version():
    """The add-on version string, read once from the bundled manifest, so the panel
    can show exactly which build is loaded (Blender caches extensions, so a stale
    install otherwise looks identical to a fresh one)."""
    global _VERSION
    if _VERSION is None:
        try:
            import tomllib
            path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
            with open(path, "rb") as f:
                _VERSION = tomllib.load(f).get("version", "?")
        except Exception:
            _VERSION = "?"
    return _VERSION


def _mm_per_unit(context):
    """How many millimetres one Blender unit represents, for the volume estimates
    (unit-system aware: 1 mm with no unit system, else ``scale_length`` metres)."""
    return units.mm_per_unit(context.scene)


def _vol_row(layout, name, units_cubed, density=None, mpu=1.0):
    """One 'Name ........ 123.4 ml · 142 g' line. ``mpu`` = mm per Blender unit."""
    ml = units_cubed * (mpu ** 3) / 1000.0
    row = layout.row()
    row.label(text=name)
    sub = row.row()
    sub.alignment = 'RIGHT'
    if density:
        sub.label(text=f"{ml:,.1f} ml · {ml * density:,.0f} g")
    else:
        sub.label(text=f"{ml:,.1f} ml")


def _funnel_flags(props, caps):
    """The funnel that will actually be built: ``(neck_r, mouth_r, over, fit)``.

    ``over`` = an Oversized toggle exceeds what the mold can carry; ``fit`` = the
    typed value was auto-fitted down. Returns ``None`` without a measured mold."""
    if not caps:
        return None
    hm = caps["half_min"]
    # Oversized = fully manual: the typed value is built exactly.
    neck = (props.sprue_radius if props.big_throat
            else min(props.sprue_radius, hm * C.THROAT_CAP))
    mouth = (neck * props.sprue_flare if props.big_mouth
             else min(neck * props.sprue_flare, hm * C.MOUTH_CAP))
    mouth = max(mouth, neck)
    over = ((props.big_throat and neck > hm * C.THROAT_CAP + 1e-6)
            or (props.big_mouth and mouth > hm * C.MOUTH_CAP + 1e-6))
    fit = ((not props.big_throat and props.sprue_radius > hm * C.THROAT_CAP + 1e-6)
           or (not props.big_mouth
               and neck * props.sprue_flare > hm * C.MOUTH_CAP + 1e-6))
    return neck, mouth, over, fit


def _model_status(context, props):
    """What Generate will work on: ``(ok, text, icon)`` for the line at the top of
    the panel. The one thing a first-time user gets wrong is not having the model
    selected, so say so in words instead of a greyed-out button alone."""
    obj = context.active_object
    if props.box_style == 'TRAY' and getattr(props, "tray_mode", 'EMBED') == 'STAMP':
        if obj is not None and obj.type in ('CURVE', 'FONT'):
            return True, f"Design: {obj.name}", 'OUTLINER_OB_FONT'
        if props.stamp_svg:
            return True, f"Design: {os.path.basename(props.stamp_svg)}", 'FILE_IMAGE'
        return False, "Select a Text / Curve, or pick an SVG below", 'INFO'
    if obj is None or obj.type != 'MESH':
        from .operators import last_master
        lm = last_master(context) if obj is None else None
        if lm is not None:
            # just after Generate: the original is hidden, so the viewport has
            # no active object - offer to rebuild it rather than a dead button
            return False, f"Regenerate uses {lm.name}, or select a model", 'INFO'
        return False, "Select your model in the viewport", 'RESTRICT_SELECT_OFF'
    if obj.name.startswith("MF_"):
        from .operators import last_master
        lm = last_master(context)
        if lm is not None:
            return False, f"Mold part selected - Regenerate uses {lm.name}", 'INFO'
        return False, "That is a mold part - select your model", 'ERROR'
    mpu = _mm_per_unit(context)
    d = obj.dimensions
    if units.looks_like_metres(context.scene, obj):
        icon = 'ERROR'              # under 1 mm: say the number, not "0 x 0 x 0"
    else:
        icon = 'MESH_DATA'
    return (True,
            f"{obj.name}   {_mm(d.x * mpu)} × {_mm(d.y * mpu)} × {_mm(d.z * mpu)} mm",
            icon)


def _mm(v):
    """A size for the status line: whole millimetres, or enough digits to show
    a size under 10 mm as more than 0."""
    return f"{v:.0f}" if v >= 10.0 else f"{v:.2g}"


LABEL_SPLIT = 0.44    # label column share of a row: room for "Silicone thickness"
                      # on the left, "Direct Printed Mold" and Auto | X | Y on the right


def _field(layout, text):
    """A labelled row: right-aligned label on the left, the control on the right.
    Blender's own property split gives the label about 40 % of the row, which
    clips "Silicone thickness" and "Throat radius" at the sidebar's normal width
    with an ellipsis; a slightly wider label column fits the full words while the
    value side still shows the longest mold type and the three split buttons."""
    split = layout.split(factor=LABEL_SPLIT, align=True)
    lab = split.row()
    lab.alignment = 'RIGHT'
    lab.label(text=text)
    return split.row(align=True)


def _generated_parts():
    """The MoldForge collection's meshes, or an empty list."""
    mfc = bpy.data.collections.get(mf_util.COLLECTION_NAME)
    if mfc is None:
        return []
    return [o for o in mfc.objects if o.type == 'MESH']


def _parts_summary(objs, tray=False):
    """'2 shells · positive · core · skin' for the Result panel."""
    names = [o.name for o in objs]
    shells = sum(1 for n in names
                 if n.startswith("MF_Mold_") and not n.startswith(("MF_Mold_Plug",
                                                                    "MF_Mold_Base",
                                                                    "MF_Mold_Cup")))
    if tray:
        bits = ["tray pan"] if shells else []
    else:
        bits = [f"{shells} shell{'s' if shells != 1 else ''}"] if shells else []
    if any(n.startswith("MF_Positive") for n in names):
        bits.append("positive")
    if any(n.startswith("Core_Master") for n in names):
        bits.append("core")
    if any(n.startswith("MF_Mold_Base") for n in names):
        bits.append("base")
    if any(n.startswith("MF_Mold_Plug") for n in names):
        bits.append("plug")
    if any(n.startswith("MF_Mold_Cup") for n in names):
        bits.append("suction cup")
    if any(n.startswith("MF_Skin") for n in names):
        bits.append("skin")
    return " · ".join(bits) if bits else f"{len(objs)} parts"


# --- header summaries ------------------------------------------------------ #
# Pure functions of the property group, each <= ~24 characters, so a COLLAPSED
# section still says what it holds. They must stay cheap: headers redraw on
# every mouse move, so nothing here may touch mesh data or run mold_caps().

def summary_shell(props):
    if props.box_style == 'POUR_BOX' and props.skin_keys:
        skin = " · glove"
    else:
        skin = ""
    if props.base_style == 'FLAT':
        return ("flat +flange" if props.base_flange else "flat") + skin
    if props.base_style == 'OPEN':
        if props.base_plate:
            return ("open +plate +screw" if props.plate_screw else "open +plate") + skin
        return ("open +cup" if props.suction_cup else "open bottom") + skin
    if props.base_style == 'FOLLOW':
        return "follows model" + skin
    if props.box_style != 'POUR_BOX':
        return "not for this type"
    out = "locking base" + (" · united" if props.lock_unite else " · separate")
    if props.dual_density:
        out = "locking · dual core"
    return out


def _contoured_key(props):
    """The Contoured switch in force: a Locking Base has its own (off by
    default - a flat seam straight through), every other bottom the general one."""
    if props.base_style == 'LOCK' and props.box_style == 'POUR_BOX':
        return "lock_contoured"
    return "contoured"


def summary_parting(props):
    if getattr(props, "use_split_planes", False):
        return "my planes"
    if props.parts_count >= 3:
        out = f"{props.parts_count} wedges"
    else:
        out = "2 pieces · " + ("contoured" if getattr(props, _contoured_key(props))
                               else f"{props.key_count} keys")
    if props.split_horizontal:
        out += " · h-seam"
    return out


def summary_wings(props):
    if not props.wings:
        return "off"
    if props.wing_keys != 'NONE':
        return props.wing_keys.lower() + " keys"
    return f"{props.wing_width:g} mm"


def summary_pour(props):
    """Short: it sits beside the longest group title, "Funnel & Vents"."""
    if props.sprue:
        out = {'TOP': "top", 'XY': "centre", 'X': "centre x", 'Y': "centre y",
               'MANUAL': "manual"}.get(props.sprue_place, props.sprue_place.lower())
        if props.big_throat or props.big_mouth:
            out += " · big"
    else:
        out = "no funnel"
    if getattr(props, "pour_channel", False):
        out = ("channel · top" if props.sprue else "channel")
    if props.vent_place == 'MARKERS':
        return out + " · markers"
    if props.vent_count > 0:
        return out + f" · {props.vent_count} vents"
    return out


def summary_printer(props):
    if not props.printer_fit:
        return "off"
    if props.max_print_height <= 0:
        return "pick a printer"
    return f"max {props.max_print_height:.0f} mm"


def summary_export(props, mpu):
    if props.last_silicone_volume <= 0.0:
        return "generate first"
    ml = props.last_silicone_volume * (mpu ** 3) / 1000.0
    return f"{ml:,.0f} ml · {ml * props.silicone_density:,.0f} g"


class _MFPanel:
    """Shared boilerplate for every MoldForge panel."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MoldForge"


# --- 1. MoldForge: model, recipe, the per-toy choices, Generate --------------- #

class MOLDFORGE_PT_main(_MFPanel, bpy.types.Panel):
    bl_label = "MoldForge by PLESURO"
    bl_idname = "MOLDFORGE_PT_main"
    bl_order = 0

    def draw_header_preset(self, context):
        # Saved settings: load your own setup into a new file in one click.
        self.layout.menu("MOLDFORGE_MT_settings", text="", icon='PRESET')

    def draw(self, context):
        layout = self.layout
        props = context.scene.moldforge
        tray = props.box_style == 'TRAY'
        pour = props.box_style == 'POUR_BOX'
        lock = pour and props.base_style == 'LOCK'

        # What Generate will work on.
        ok, text, icon = _model_status(context, props)
        layout.label(text=text, icon=icon)
        if ok and units.looks_like_metres(context.scene, context.active_object):
            # a model made in metres reads as under a millimetre by the
            # 1 unit = 1 mm convention: the mold would swallow a speck
            warn = layout.column(align=True)
            warn.label(text="Under 1 mm? It was made in metres", icon='BLANK1')
            if context.scene.unit_settings.system != 'NONE':
                hint = warn.row()
                hint.active = False
                hint.label(text="Generate reads it in metres", icon='BLANK1')
            warn.operator("moldforge.read_as_metres", text="My model is in metres",
                          icon='DRIVER_DISTANCE')

        col = layout.column()
        _field(col, "Mold type").prop(props, "box_style", text="")
        if props.box_style == 'SOLID':
            _field(col, "Shape").prop(props, "solid_shape", expand=True)
            col.prop(props, "skin_core", text="Skin mold (printed core)")
            if props.skin_core:
                _field(col, "Skin").prop(props, "skin_thickness", text="")
        if tray:
            _field(col, "Mode").prop(props, "tray_mode", text="")
            self._tray(layout, props, context)
            self._generate(layout, context, ok)
            return

        if props.box_style == 'SOLID' and props.skin_core:
            _field(col, "Bottom").label(text="Open + key plate (skin)")
        else:
            _field(col, "Bottom").prop(props, "base_style", text="")
        if props.base_style == 'LOCK' and not pour:
            layout.label(text="Locking Base is for the Silicone Pour Box",
                         icon='ERROR')
        obj = context.active_object
        if (props.base_style in ('LOCK', 'OPEN') and obj is not None
                and obj.name.startswith("Core_Master")):
            layout.label(text="Core_Master has its " + (
                "cross" if props.base_style == 'LOCK' else "legs")
                + " - use Bottom: Flat", icon='INFO')

        # --- sizes ----------------------------------------------------- #
        head = layout.row()
        head.active = False
        mpu = _mm_per_unit(context)
        if abs(mpu - 1.0) < 1e-9:
            head.label(text="Sizes in mm")
        else:
            head.label(text=f"Sizes in mm  (1 unit = {mpu:g} mm)")
        col = layout.column(align=True)
        _field(col, "Silicone thickness" if pour else "Wall thickness").prop(
            props, "wall_thickness", text="")
        if pour:
            _field(col, "Shell wall").prop(props, "shell_wall", text="")
        if props.sprue:
            row = _field(col, "Throat radius")
            row.prop(props, "sprue_radius", text="")
            row.prop(props, "big_throat", text="", icon='FULLSCREEN_ENTER',
                     toggle=True)
        if props.use_split_planes:
            _field(col, "Split").label(text="my planes")
        elif props.parts_count == 2:
            # No text="" here: on an expanded enum that blanks the buttons.
            _field(col, "Split").prop(props, "split_axis", expand=True)
        else:
            _field(col, "Pieces").prop(props, "parts_count", text="")
        # Your own split planes: any number, anywhere (Parting has the details)
        from .core import planes as mf_planes
        prow = layout.row(align=True)
        prow.prop(props, "use_split_planes", text="Split with my planes")
        if props.use_split_planes:
            prow.operator("moldforge.add_split_plane", text="", icon='ADD')
            n_pl = len(mf_planes.plane_objects())
            hint = layout.row()
            hint.active = False
            hint.label(text=f"{n_pl} plane{'s' if n_pl != 1 else ''} - move & rotate them"
                       if n_pl else "Add a plane with +", icon='INFO')
        if props.sprue:
            flags = _funnel_flags(props, mold_caps(context))
            if flags and (flags[2] or flags[3]):
                # Two short lines: a long label is clipped in the middle with "...".
                neck, mouth, over, _fit = flags
                note = layout.column(align=True)
                note.label(text=f"Built: throat Ø{2 * neck:.0f}, mouth Ø{2 * mouth:.0f}",
                           icon='ERROR' if over else 'INFO')
                sub = note.row()
                sub.active = False
                sub.label(text="Oversized - check the shell" if over
                          else "Auto-fitted to this mold", icon='BLANK1')

        # --- what to add ----------------------------------------------- #
        head = layout.row()
        head.active = False
        head.label(text="Add")
        tog = layout.column(align=True)
        tog.prop(props, "wings", text="Clamp wings")
        tog.prop(props, "sprue", text="Pour funnel on top")
        tog.prop(props, "pour_channel", text="Fill from the base (channel)")
        if props.pour_channel:
            _field(layout.column(), "Channel radius").prop(props, "channel_radius",
                                                           text="")
            tog = layout.column(align=True)
        if lock or (props.base_style == 'OPEN' and props.box_style != 'TRAY'):
            tog.prop(props, "dual_density", text="Dual-density core (2-pour)")
            if props.dual_density:
                _field(layout.column(), "Soft Wall").prop(props, "core_wall", text="")
                tog = layout.column(align=True)
            tog.prop(props, "anchor_plug", text="Vac-U-Lock plug")
        if pour and props.base_style in ('OPEN', 'LOCK'):
            tog.prop(props, "stand_legs", text="Stand legs (for casting)")
        tog.prop(props, "label_on", text="Label on the case")
        if props.label_on and props.box_style != 'TRAY':
            lcol = layout.column(align=True)
            _field(lcol, "Label").prop(props, "label_text", text="")
            _field(lcol, "Logo").prop(props, "label_logo_obj", text="")
            if props.label_logo_obj is None:
                _field(lcol, "Logo SVG").prop(props, "label_logo", text="")
            tog = layout.column(align=True)
        if props.box_style != 'TRAY':
            # Inner cores: mark a modelled core mesh (Parting has pull & stem)
            from .core import cores as mf_cores
            n_cores = len(mf_cores.core_objects())
            crow = layout.row(align=True)
            crow.operator("moldforge.mark_core", text="Mark selected as inner core",
                          icon='MESH_CYLINDER')
            if n_cores:
                cinfo = layout.row()
                cinfo.active = False
                cinfo.label(text=f"{n_cores} inner core{'s' if n_cores != 1 else ''} "
                                 f"- pull & stem in Advanced > Parting")
            tog = layout.column(align=True)
        tog.prop(props, "printer_fit", text="Cut to fit my printer")
        if props.printer_fit:
            # stays put once a printer is picked (it used to hide itself as soon
            # as the height was filled in); a preset's height shows greyed
            pcol = layout.column(align=True)
            _field(pcol, "Printer").prop(props, "printer_preset", text="")
            hrow = _field(pcol, "Max height")
            hrow.enabled = props.printer_preset == 'CUSTOM'
            hrow.prop(props, "max_print_height", text="")
            _field(pcol, "Supports").prop(props, "support_clearance", text="")
            if pour:
                pcol.prop(props, "fit_positive", text="Cut positive too")
            if props.max_print_height <= 0:
                hint = layout.row()
                hint.active = False
                hint.label(text="Pick a printer or type its height", icon='INFO')

        self._generate(layout, context, ok)

    @staticmethod
    def _tray(layout, props, context):
        """The tray / stamp settings, inline: the whole mold is this one section."""
        col = layout.column(align=True)
        if props.tray_mode == 'STAMP':
            obj = context.active_object
            if obj is None or obj.type not in ('CURVE', 'FONT'):
                _field(col, "SVG file").prop(props, "stamp_svg", text="")
            _field(col, "Stamp width").prop(props, "stamp_width", text="")
            _field(col, "Relief depth").prop(props, "stamp_relief", text="")
            _field(col, "Border").prop(props, "tray_margin", text="")
            _field(col, "Slab").prop(props, "tray_depth", text="")
            _field(col, "Pan wall").prop(props, "tray_wall", text="")
            _field(col, "Pan floor").prop(props, "tray_floor", text="")
            layout.prop(props, "stamp_mirror", text="Mirror the design")
        else:
            _field(col, "Detail side").prop(props, "tray_up", text="")
            _field(col, "Outline").prop(props, "tray_outline", text="")
            _field(col, "Border").prop(props, "tray_margin", text="")
            _field(col, "Pour depth").prop(props, "tray_depth", text="")
            _field(col, "Pan wall").prop(props, "tray_wall", text="")
            _field(col, "Pan floor").prop(props, "tray_floor", text="")
            layout.prop(props, "tray_removable", text="Lift-off walls")

    @staticmethod
    def _generate(layout, context, ok):
        layout.separator()
        btn = layout.column()
        btn.scale_y = 1.5
        obj = context.active_object
        if (not ok and (obj is None or obj.name.startswith("MF_"))
                and context.scene.moldforge.box_style != 'TRAY'):
            from .operators import last_master
            lm = last_master(context)
            if lm is not None:
                # A part of the last mold is selected: rebuild from its model.
                btn.operator("moldforge.regenerate", text=f"Regenerate from {lm.name}",
                             icon='FILE_REFRESH')
                return MOLDFORGE_PT_main._version_row(layout)
        btn.enabled = ok
        btn.operator("moldforge.generate", icon='MOD_FLUIDSIM')
        MOLDFORGE_PT_main._version_row(layout)

    @staticmethod
    def _version_row(layout):
        foot = layout.row()
        foot.active = False
        foot.alignment = 'RIGHT'
        foot.label(text=f"v{_version()}")


# --- 2. Result: after a build ----------------------------------------------- #

class MOLDFORGE_PT_result(_MFPanel, bpy.types.Panel):
    bl_label = "Result"
    bl_idname = "MOLDFORGE_PT_result"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        return bool(_generated_parts())

    def draw(self, context):
        layout = self.layout
        props = context.scene.moldforge
        tray = props.box_style == 'TRAY'
        mpu = _mm_per_unit(context)
        objs = _generated_parts()

        layout.label(text=_parts_summary(objs, tray), icon='OUTLINER_COLLECTION')

        col = layout.column(align=True)
        if tray:
            _vol_row(col, "Silicone to pour", props.last_silicone_volume,
                     props.silicone_density, mpu)
            _vol_row(col, "Pan plastic", props.last_plastic_volume,
                     props.plastic_density, mpu)
            if props.tray_mode != 'FRAME':    # cast volume unknown for a real object
                _vol_row(col, "Cast material", props.last_cavity_volume,
                         props.cast_density, mpu)
        elif props.box_style == 'POUR_BOX':
            _vol_row(col, "Silicone skin" if props.skin_keys else "Silicone to pour",
                     props.last_silicone_volume, props.silicone_density, mpu)
            _vol_row(col, "Box plastic", props.last_plastic_volume,
                     props.plastic_density, mpu)
            _vol_row(col, "Cast material", props.last_cavity_volume,
                     props.cast_density, mpu)
        else:
            _vol_row(col, "Mold material", props.last_silicone_volume,
                     props.silicone_density, mpu)
            _vol_row(col, "Cast material", props.last_cavity_volume,
                     props.cast_density, mpu)

        from .operators import last_master
        lm = last_master(context)
        if lm is not None:
            # Tweak a setting, then rebuild in place: the model stays hidden.
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("moldforge.regenerate", text="Regenerate", icon='FILE_REFRESH')
            row.operator("moldforge.toggle_master", text="",
                         icon='HIDE_ON' if lm.hide_get() else 'HIDE_OFF')
        exploded = any("mf_explode" in o for o in objs)
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("moldforge.explode",
                     text="Reassemble" if exploded else "Exploded Preview",
                     icon='STICKY_UVS_DISABLE' if exploded else 'MOD_EXPLODE')
        row.operator("moldforge.export", text="Export STL...", icon='FILE_TICK')


# --- 3. Advanced: everything else, by part of the mold ----------------------- #

class MOLDFORGE_PT_advanced(_MFPanel, bpy.types.Panel):
    bl_label = "Advanced"
    bl_idname = "MOLDFORGE_PT_advanced"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 10

    def draw(self, context):
        row = self.layout.row()
        row.active = False
        row.label(text="Fine-tune each part of the mold", icon='PREFERENCES')


class _MFSub(_MFPanel):
    """Shared boilerplate for every Advanced sub-panel."""
    bl_parent_id = "MOLDFORGE_PT_advanced"
    bl_options = {'DEFAULT_CLOSED'}

    @staticmethod
    def _summary(layout, text):
        """The current setting, dimmed, at the right end of the header."""
        if text:
            sub = layout.row()
            sub.alignment = 'RIGHT'
            sub.active = False          # dimmed: state, not a control
            sub.label(text=text)

    def _body(self):
        """Label/value columns, one setting per row: labels never get clipped."""
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        return layout


class MOLDFORGE_PT_shell(_MFSub, bpy.types.Panel):
    bl_label = "Shell & Base"
    bl_idname = "MOLDFORGE_PT_shell"
    bl_order = 10

    @classmethod
    def poll(cls, context):
        return context.scene.moldforge.box_style != 'TRAY'

    def draw_header_preset(self, context):
        self._summary(self.layout, summary_shell(context.scene.moldforge))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge

        if props.box_style == 'POUR_BOX':
            layout.prop(props, "skin_keys", text="Glove skin keys")

        if props.base_style == 'FLAT':
            layout.prop(props, "base_flange", text="Mounting flange")
            if props.base_flange:
                layout.prop(props, "flange_width", text="Flange width")
        elif props.base_style == 'OPEN':
            layout.prop(props, "base_plate", text="Key plate")
            if props.base_plate:
                layout.prop(props, "fit_clearance", text="Clearance")
                layout.prop(props, "plate_unite", text="Unite with model")
                if not props.plate_unite:
                    layout.prop(props, "plate_screw", text="Screw master")
                if props.plate_screw and not props.plate_unite:
                    col = layout.column(align=True)
                    col.prop(props, "screw_diameter", text="Screw hole Ø")
                    col.prop(props, "screw_countersink", text="Head recess")
                    sub = col.column(align=True)
                    sub.active = props.screw_countersink
                    sub.prop(props, "screw_head_type", text="")
                    sub.prop(props, "screw_head_diameter", text="Head Ø")
                    if props.screw_head_type == 'COUNTERBORE':
                        sub.prop(props, "screw_head_depth", text="Head depth")
                    col = layout.column(align=True)
                    col.prop(props, "insert_diameter", text="Insert hole Ø")
                    col.prop(props, "insert_depth", text="Insert depth")
            self._cup(layout, props)
            if props.anchor_plug and not props.suction_cup:
                layout.prop(props, "cup_lock", text="Fasten plug")
            if props.dual_density:
                box = layout.box()
                box.label(text="Two-pour workflow:", icon='INFO')
                box.label(text="1. Core_Master + Generate = core mold")
                box.label(text="2. Cast the core in FIRM silicone")
                box.label(text="3. Flip this mold, fill with SOFT")
                box.label(text="4. Seat the core's legs on the rim")
            if props.box_style == 'POUR_BOX':
                self._legs(layout, props)
        elif props.base_style == 'LOCK' and props.box_style == 'POUR_BOX':
            col = layout.column(align=True)
            col.prop(props, "lock_height", text="Base height")
            col.prop(props, "lock_margin", text="Margin")
            col.prop(props, "lock_teeth", text="Teeth")
            col.prop(props, "lock_tooth_depth", text="Tooth depth")
            col.prop(props, "lock_tolerance", text="Tolerance")
            layout.prop(props, "lock_unite", text="Unite with model")
            if not props.lock_unite:
                layout.label(text="Base comes out as MF_Mold_Base", icon='INFO')
            self._cup(layout, props)
            if props.dual_density:
                box = layout.box()
                box.label(text="Two-pour workflow:", icon='INFO')
                box.label(text="1. Core_Master + Generate = core mold")
                box.label(text="2. Cast the core in FIRM silicone")
                box.label(text="3. Flip this mold, fill with SOFT")
                box.label(text="4. Press the core in - it locks")
            self._legs(layout, props)

    @staticmethod
    def _legs(layout, props):
        layout.prop(props, "stand_legs", text="Stand legs")
        if props.stand_legs:
            layout.prop(props, "stand_tilt", text="Tilt")
            layout.label(text="Cured: turn over onto the legs, pour", icon='INFO')

    @staticmethod
    def _cup(layout, props):
        layout.prop(props, "suction_cup", text="Suction cup")
        if props.suction_cup:
            layout.prop(props, "cup_diameter", text="Cup Ø")
            layout.prop(props, "cup_depth", text="Cup depth")
            layout.prop(props, "cup_lock", text="Fasten")
            layout.label(text="Fill inverted, press the former in", icon='INFO')


class MOLDFORGE_PT_parting(_MFSub, bpy.types.Panel):
    bl_label = "Parting"
    bl_idname = "MOLDFORGE_PT_parting"
    bl_order = 20

    @classmethod
    def poll(cls, context):
        return context.scene.moldforge.box_style != 'TRAY'

    def draw_header_preset(self, context):
        self._summary(self.layout, summary_parting(context.scene.moldforge))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge
        is_block = (props.box_style == 'SOLID' and props.solid_shape == 'BLOCK')

        from .core import cores as mf_cores
        n_cores = len(mf_cores.core_objects())
        row = layout.row(align=True)
        row.operator("moldforge.mark_core", icon='MESH_CYLINDER')
        if n_cores:
            sub = layout.column(align=True)
            sub.prop(props, "core_pull", text="Core pull")
            sub.prop(props, "core_stem", text="Core stem")
            info = layout.column(align=True)
            info.active = False
            info.label(text=f"{n_cores} inner core{'s' if n_cores != 1 else ''} marked")
        layout.separator()
        layout.prop(props, "use_split_planes", text="Split with my planes")
        if props.use_split_planes:
            from .core import planes as mf_planes
            n_pl = len(mf_planes.plane_objects())
            layout.operator("moldforge.add_split_plane", icon='MESH_PLANE')
            sub = layout.column(align=True)
            sub.active = False
            sub.label(text=f"{n_pl} plane{'s' if n_pl != 1 else ''} - move & rotate them"
                      if n_pl else "No planes yet - add one")
            layout.prop(props, "split_horizontal", text="Horizontal split")
            if props.split_horizontal:
                layout.prop(props, "split_z_offset", text="Seam height")
            return
        layout.prop(props, "parts_count", text="Pieces")
        if props.parts_count >= 3:
            if is_block or not props.wings:
                layout.prop(props, "key_count", text="Seam pins")
        else:
            layout.prop(props, "split_offset", text="Offset")
            ckey = _contoured_key(props)
            layout.prop(props, ckey, text="Contoured")
            if not getattr(props, ckey):
                layout.prop(props, "key_count", text="Keys")
                if props.key_count > 0 and not props.wings:
                    layout.prop(props, "registration", text="Key type")
        layout.prop(props, "split_horizontal", text="Horizontal split")
        if props.split_horizontal:
            layout.prop(props, "split_z_offset", text="Seam height")


class MOLDFORGE_PT_wings(_MFSub, bpy.types.Panel):
    bl_label = "Clamp Wings"
    bl_idname = "MOLDFORGE_PT_wings"
    bl_order = 30

    @classmethod
    def poll(cls, context):
        props = context.scene.moldforge
        if props.box_style == 'TRAY':
            return False
        is_block = (props.box_style == 'SOLID' and props.solid_shape == 'BLOCK')
        return not (is_block and props.parts_count >= 3)

    def draw_header(self, context):
        self.layout.prop(context.scene.moldforge, "wings", text="")

    def draw_header_preset(self, context):
        self._summary(self.layout, summary_wings(context.scene.moldforge))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge
        layout.active = props.wings
        layout.prop(props, "wing_width", text="Width")
        layout.prop(props, "wing_keys", text="Alignment")
        if props.wing_keys != 'NONE':
            col = layout.column(align=True)
            col.prop(props, "wing_key_size", text="Key size")
            col.prop(props, "wing_key_height", text="Key height")
            col.prop(props, "wing_key_spacing", text="Key spacing")
            layout.prop(props, "fit_clearance", text="Clearance")
        layout.prop(props, "wing_band_notches", text="Band notches")
        layout.prop(props, "bolt_diameter", text="Bolt Ø")
        layout.prop(props, "bolt_auto", text="Auto bolts")
        sub = layout.column()
        sub.active = not props.bolt_auto
        sub.prop(props, "bolt_count", text="Bolts / side")


class MOLDFORGE_PT_pour(_MFSub, bpy.types.Panel):
    bl_label = "Funnel & Vents"
    bl_idname = "MOLDFORGE_PT_pour"
    bl_order = 40

    @classmethod
    def poll(cls, context):
        return context.scene.moldforge.box_style != 'TRAY'

    def draw_header(self, context):
        self.layout.prop(context.scene.moldforge, "sprue", text="")

    def draw_header_preset(self, context):
        self._summary(self.layout, summary_pour(context.scene.moldforge))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge
        caps = mold_caps(context)

        col = layout.column()
        col.active = props.sprue
        col.prop(props, "sprue_radius", text="Throat radius")
        col.prop(props, "funnel_height", text="Height")
        row = col.row(align=True)
        row.prop(props, "sprue_flare", text="Mouth flare")
        row.prop(props, "big_mouth", text="", icon='FULLSCREEN_ENTER', toggle=True)
        col.prop(props, "sprue_place", text="Placement")
        if props.sprue_place == 'MANUAL':
            col.prop(props, "sprue_x", text="X")
            col.prop(props, "sprue_y", text="Y")
        npm = len(mf_util.marker_points("MF_PourMark"))
        row = col.row(align=True)
        sub = row.row(align=True)
        sub.enabled = npm == 0
        sub.prop(props, "sprue_count", text="Pour points")
        row.operator("moldforge.add_pour_marker", text="", icon='ADD')
        if npm:
            col.label(text=f"{npm} marker(s) add extra spouts",
                      icon='EMPTY_SINGLE_ARROW')
        # The truth rows: the funnel that will actually be built.
        flags = _funnel_flags(props, caps)
        if flags:
            neck, mouth, over, fit = flags
            note = col.column(align=True)
            note.label(text=f"Built: throat Ø{2 * neck:.0f}, mouth Ø{2 * mouth:.0f}",
                       icon='ERROR' if (over or fit) else 'INFO')
            if over or fit:
                sub = note.row()
                sub.active = False
                sub.label(text="Oversized - check the shell" if over
                          else "Auto-fitted to this mold", icon='BLANK1')

        layout.separator()
        layout.prop(props, "pour_channel", text="Bottom-fill channel")
        if props.pour_channel:
            col = layout.column(align=True)
            col.prop(props, "channel_radius", text="Channel radius")
            col.prop(props, "channel_hug", text="Follow model")
            if props.channel_hug:
                col.prop(props, "channel_smooth", text="Smoothing")
            col.prop(props, "channel_flip", text="Other side")
            layout.label(text="Pour beside the model, fills from the base",
                         icon='INFO')
        layout.separator()
        layout.prop(props, "vent_place", text="Vents")
        if props.vent_place == 'MARKERS':
            layout.operator("moldforge.add_vent_marker", icon='ADD')
            layout.prop(props, "vent_radius", text="Vent radius")
            nvm = len(mf_util.marker_points("MF_VentMark"))
            layout.label(
                text=(f"{nvm} marker(s) - one vent each" if nvm
                      else "Shift+RClick the model, then add"),
                icon='EMPTY_DATA' if nvm else 'INFO')
        else:
            layout.prop(props, "vent_count", text="Air vents")
            if props.vent_count > 0:
                layout.prop(props, "vent_radius", text="Vent radius")
                if caps and props.vent_radius > caps["vent_r"] + 1e-6:
                    layout.label(text=f"Vents auto-fitted to Ø{2 * caps['vent_r']:.1f}",
                                 icon='ERROR')


class MOLDFORGE_PT_printer(_MFSub, bpy.types.Panel):
    bl_label = "Printer Fit"
    bl_idname = "MOLDFORGE_PT_printer"
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return context.scene.moldforge.box_style != 'TRAY'

    def draw_header(self, context):
        self.layout.prop(context.scene.moldforge, "printer_fit", text="")

    def draw_header_preset(self, context):
        self._summary(self.layout, summary_printer(context.scene.moldforge))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge
        layout.active = props.printer_fit
        layout.prop(props, "printer_preset", text="Printer")
        sub = layout.column()
        sub.enabled = props.printer_preset == 'CUSTOM'
        sub.prop(props, "max_print_height", text="Max height")
        layout.prop(props, "support_clearance", text="Supports")
        layout.prop(props, "fit_positive", text="Cut positive too")
        if props.max_print_height <= 0:
            layout.label(text="Pick a printer or type its height", icon='INFO')
        elif props.max_print_height < 60.0:
            layout.label(text=f"{props.max_print_height:.0f} mm?! A Photon is 165",
                         icon='ERROR')
        else:
            layout.label(text="Tall parts get split to fit", icon='CON_SIZELIMIT')


class MOLDFORGE_PT_mesh(_MFSub, bpy.types.Panel):
    bl_label = "Mesh Prep"
    bl_idname = "MOLDFORGE_PT_mesh"
    bl_order = 60

    def draw_header_preset(self, context):
        props = context.scene.moldforge
        bits = []
        if props.decimate:
            bits.append(f"reduce to {props.decimate_ratio:g}")
        if props.voxel_safe:
            bits.append(f"rebuild {props.voxel_size:g}")
        if props.mold_detail != 1.0:
            bits.append(f"detail {props.mold_detail:g}x")
        self._summary(self.layout, " · ".join(bits))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge
        layout.prop(props, "heal", text="Clean up model")
        sub = layout.column()
        sub.active = props.heal
        sub.label(text="Welds, fills small holes, drops stray bits", icon='INFO')
        layout.prop(props, "fix_bottom", text="Fix flat bottom")
        layout.operator("moldforge.clean_model", text="Clean Up Model Now",
                        icon='BRUSH_DATA')
        layout.separator()
        layout.prop(props, "decimate", text="Reduce polygons")
        if props.decimate:
            layout.prop(props, "decimate_ratio", text="Keep")
        layout.prop(props, "voxel_safe", text="Rebuild as solid (remesh)")
        if props.voxel_safe:
            layout.prop(props, "voxel_size", text="Voxel size")
            layout.label(text="Softens detail finer than the voxel", icon='INFO')
        layout.prop(props, "mold_detail", text="Mold detail")


class MOLDFORGE_PT_export(_MFSub, bpy.types.Panel):
    bl_label = "Materials & Export"
    bl_idname = "MOLDFORGE_PT_export"
    bl_order = 70

    def draw_header(self, context):
        self.layout.prop(context.scene.moldforge, "export_after", text="")

    def draw_header_preset(self, context):
        props = context.scene.moldforge
        self._summary(self.layout, summary_export(props, _mm_per_unit(context)))

    def draw(self, context):
        layout = self._body()
        props = context.scene.moldforge

        layout.prop(props, "export_dir", text="Folder")
        layout.label(text="Header tick = export after Generate", icon='INFO')
        layout.separator()
        layout.prop(props, "label_on", text="Label")
        if props.label_on:
            layout.prop(props, "label_text", text="Text")
            layout.prop(props, "label_logo_obj", text="Logo")
            if props.label_logo_obj is None:
                layout.prop(props, "label_logo", text="Logo SVG")
            if props.label_logo_obj is not None or props.label_logo:
                layout.prop(props, "label_logo_size", text="Logo height")
            layout.prop(props, "label_style", text="Style")
            col = layout.column(align=True)
            col.prop(props, "label_size", text="Letter height")
            col.prop(props, "label_depth", text="Depth")
            sub = layout.column(align=True)
            sub.active = False
            sub.label(text="{silicone_g} {silicone_ml} {cast_g}")
            sub.label(text="{cast_ml} {name} {date}   | = new line")
        layout.separator()
        layout.prop(props, "silicone_preset", text="Silicone")
        layout.prop(props, "silicone_density", text="Density")
        layout.prop(props, "cast_preset", text="Cast")
        layout.prop(props, "cast_density", text="Density")
        layout.prop(props, "plastic_density", text="Print resin")


# Registration order matters: a child listed before its parent breaks the add-on.
PANEL_CLASSES = (
    MOLDFORGE_PT_main,
    MOLDFORGE_PT_result,
    MOLDFORGE_PT_advanced,
    MOLDFORGE_PT_shell,
    MOLDFORGE_PT_parting,
    MOLDFORGE_PT_wings,
    MOLDFORGE_PT_pour,
    MOLDFORGE_PT_printer,
    MOLDFORGE_PT_mesh,
    MOLDFORGE_PT_export,
)
