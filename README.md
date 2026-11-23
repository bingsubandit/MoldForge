# MoldForge

A Blender add-on that turns a 3D model into a **printable mold system** — a 2‑to‑4
piece mold with an auto‑oriented, self‑registering split, sprue + air vents, a
mounting base and silicone/cast/plastic volume **and weight** estimates, or a
one‑part open tray for flat & relief objects. Exports STL.

Three output types (**Mold Type** in the panel):

- **Silicone Pour Box** (default) — prints a thin-walled **jacket** that covers
  your master with a gap; you nest the master inside and pour liquid silicone
  into the gap — the silicone is the mold. Controls: **Silicone Gap** and
  **Printed Shell Wall**. An `MF_Skin` object always shows exactly the silicone
  you'll pour. Tick **Glove Skin Keys** for the glove / mother-mold workflow
  (set a thin gap, e.g. 3 mm): registration **bumps on the skin** seat into
  matching **pockets in the jacket** so the thin skin can't shift or slump.
- **Direct Printed Mold** — the printed pieces *are* the mold; cast
  resin/wax/plaster straight in. One control: **Wall Thickness**, plus a
  **Shape**: *Hugging* (pieces follow the model — least material) or *Block*
  (rectangular — easiest to clamp and stand).
- **Tray / Open Pour** — a one‑part open **pan** for FLAT or relief objects
  (text, logos, coins, medallions). The object is laid flat with its detailed
  face up and the top left open: **Embed** it into the floor and pour silicone
  over it for a flexible stamp/mold, or print a **Frame** to drop a real object
  in and pour around it. Pick a **Rectangular** or material‑saving **Hug
  (rounded)** outline. No split, wings or funnel.

> Original, GPL-licensed implementation built on Blender's public Python API
> (`bmesh`, modifiers, depsgraph). It does not contain or derive from any other
> mold tool's code.

Requires **Blender 5.1+** (`blender_version_min = 5.1.0`); built and tested against Blender 5.1.

## Install

1. In Blender: **Edit ▸ Preferences ▸ Get Extensions ▸ ⌄ ▸ Install from Disk…**
   (or **Add-ons ▸ Install from Disk…**) and pick the MoldForge zip.
2. Make sure **MoldForge** is enabled.
3. Open the 3D viewport sidebar (press **N**) → **MoldForge** tab.

The tab holds three panels, in the order the work happens:

- **MoldForge** - the model you selected (name and size in mm), the few
  choices that change from toy to toy (mold type, bottom, the sizes, the split,
  what to add), and **Generate Mold**.
- **Result** - appears after a build: what was made, the silicone and cast
  figures, **Exploded Preview** and **Export STL**.
- **Regenerate** - after a build the Result panel offers Regenerate: change a
  setting and rebuild from the same (hidden) model without unhiding or
  reselecting it; the eye button shows or hides the original.
- **Saved settings** - the preset icon at the top right of the MoldForge panel
  saves every setting under a name and loads it into any .blend in one click
  (plus Delete, Reset to Defaults and Open Settings Folder). Only what you
  save is there; the files live in the extension's user folder and survive
  updates.
- **Advanced** - closed by default; every other setting grouped by the part of
  the mold it shapes (Shell & Base, Parting, Clamp Wings, Funnel & Vents,
  Printer Fit, Mesh Prep, Materials & Export). Each group shows its current
  setting at the right of its header, so a closed group still tells you what it
  holds.

## Use

1. Select the mesh you want to mold (make it the active object).
2. Set your parameters in the panel.
3. Click **Generate Mold**.

The mold pieces (`MF_Mold_A`, `MF_Mold_B`, …) and the printable positive
(`MF_Positive`) land **on the model's location** in a `MoldForge` collection;
your original model is hidden (the positive takes its place on screen - unhide
the original from the outliner whenever you want it back).
Export with **Export Mold Parts**, or tick **Export after generate**. A heavy
build runs with a wait cursor and a progress note so it never looks frozen.

## Sizes are in millimetres

Every size field is in **millimetres** (e.g. a 3 mm silicone wall, a 2 mm printed
shell) and the build converts mm to Blender units using your **scene's unit scale**
— so it's correct in an Imperial scene, or a metric scene whose unit isn't
millimetres, not only the "1 unit = 1 mm" convention. Specifically:

- **No unit system** (Scene ▸ Units ▸ None) — the classic mold‑maker convention,
  **1 Blender unit = 1 mm**.
- **Blender's untouched default** (Metric · Unit Scale 1.0 · Meters) is also taken
  as 1 unit = 1 mm, so existing files aren't disturbed - unless the model would
  then be under 1 mm. Such a model was made in metres (a game asset, a scan, an
  export from a metre-based app; Blender shows it as a few centimetres): the panel
  says so with a **My model is in metres** button, and Generate sets Scene Units >
  Length to Millimeters itself, so 1 unit reads as 1 metre and the mold fits.
- **Imperial, or metric once you configure it** (a Unit Scale ≠ 1, or a specific
  Length unit like mm/cm) — a Blender unit is taken at face value (`scale_length`
  metres), so a 3 mm wall is genuinely 3 mm. The panel shows the basis it's using
  (e.g. *1 unit = 25.4 mm*).

Whatever the unit set-up, the build itself runs in millimetres - your sizes and
the add-on's own clearances alike - on copies scaled to mm, and the finished
parts are scaled back to your scene. **Export** writes the STL files in
millimetres, which is what slicers expect, and **Fix Model's Flat Bottom** works
in millimetres too.

The defaults suit print‑scale models (~20–200 mm); the sprue/vents are auto‑capped
so they can't blow out a small mold — and the **Oversized Throat / Oversized Mouth**
toggles switch the funnel to **fully manual** (exactly the typed sizes, no cap at
all) when the auto fit isn't what you want.

## Parameters

| Group | Option | What it does |
| --- | --- | --- |
| Mold | **Mold Type** | `Silicone Pour Box` (print a jacket, pour silicone), `Direct Printed Mold` (the print is the mold), or `Tray / Open Pour` (one‑part open pan for flat objects) |
| Mold | **Shape** | *(Direct mold)* `Hugging` (least material) or `Block` (easiest to clamp) |
| Tray | **Tray Mode** | *(Tray)* `Embed` (fuse the object in, pour silicone over it for a stamp), `Frame` (print the open box, drop a real object in), or `Stamp from SVG / Text` (below) |
| Tray | **Stamp from SVG / Text** | Make a real silicone INK STAMP: select a **Text/Curve object** or set an **SVG File** (filled paths), and the design is scaled to **Stamp Width** and **engraved Relief-Depth deep into the pan floor** — the printed mold is the negative. Pour silicone **Slab** deep, cure, peel: the slab carries the design raised and mirrored, so imprints read correctly; glue it to an acrylic block. **Mirror Design** flips it for face-reading stamps; the floor auto-thickens so the engraving can't pierce it |
| Tray | **Capture Face** + **Outline** | *(Tray)* which face points up (`Auto`/Z/X/Y) and a `Rectangular` or material‑saving `Hug (rounded)` pan outline |
| Tray | **Pan Wall / Pan Floor / Border / Pour Depth** | *(Tray)* printed wall & floor thickness, the silicone border around the object, and how much silicone stands above it |
| Tray | **Lift-off Walls** | *(Tray)* print the tray as a floor (with the embedded object) and a separate frame that lifts straight off the cured silicone; a tongue under the frame seats in a groove round the floor so nothing leaks |
| Sprue/Vents | **Vent Placement** + markers | `Auto (high points)` as before, or `Manual (markers)`: snap the 3D cursor onto the model (Shift+Right‑Click), press **Add Vent Marker**, and Generate drills ONE vent per marker — move/duplicate/delete the little sphere empties freely (they live in a "MoldForge Markers" collection and survive regeneration). The marker's full 3D position counts, so a mid‑height side pocket can be vented |
| Sprue/Vents | **Add Pour Marker** | Each cone marker adds an EXTRA pour spout at its X/Y (dropped onto the surface); the first spout keeps the **Placement** setting. Markers replace the automatic extra Pour Points while they exist |
| Mold | **Silicone / Wall Thickness** | Silicone thickness (pour gap / glove skin, or the direct mold's wall), in mm |
| Mold | **Printed Shell Wall** | *(Pour Box)* printed jacket wall |
| Mold | **Glove Skin Keys** | *(Pour Box)* glove/mother-mold workflow: bumps on the silicone skin seat into pockets in the jacket |
| Mold | **Skin Mold** + **Skin Thickness** | *(Direct Printed Mold)* for casting a thin flexible skin (latex, silicone - a mask, a sleeve): a printed core, the model shrunk inward by the skin thickness, stands on the key plate inside the mold (`MF_SkinCore`); pour into the gap. The skin comes out open at the bottom, where the core is pulled out. Uses an Open Bottom with the key plate |
| Mold | **Inner Cores** (**Mark as Core**, **Core Pull**, **Core Stem**) | Model a core as its own mesh (a cylinder in a blind hole, the shape of an undercut pocket or a hollow), select it and Mark as Core. Generate makes a removable core part (`MF_Core_N`): the core, a square stem out through the mold wall along its pull direction (Auto: out through the hole's opening) and a handle. A direct mold gets the core's pocket and the stem channel cut, with the fit clearance; a pour box's positive carries the core and stem, so the silicone forms the channel the core slides into |
| Mold | **Bottom** | `Flat (closed)` (+ optional **Mounting Flange** with bolt holes) · `Open Bottom` (+ optional **Detachable Key Plate**: a pocket registers the model; a ring tongue on the shell drops into a groove around the plate's chin collar; **Unite Plate with Model** fuses the plate into the positive so master + plate print as one piece; or **Screw Master to Plate** fixes the master with one screw instead of glue - a hole through the plate, recessed from below for the head (countersunk for flat heads, or a counterbore of set diameter and depth for pan / socket heads), and a heat-set insert hole in the master's underside, in the middle of the base or the nearest spot with 2 mm of master around the insert) · `Follow Model` · `Locking Base` |
| Mold | **Locking Base** *(Pour Box)* | A sawtooth plinth is united into the high‑poly positive; the shells get a matching socket that hugs it with **Lock Tolerance** (≈0.2 mm) so they lock on and can't slip, and the bottom prints open. Controls: **Base Height / Base Margin / Sawtooth Teeth / Tooth Depth / Lock Tolerance**. Untick **Unite Base with Model** to keep the base as a separate `MF_Mold_Base` part (exported with the shells) and leave your model untouched. Pre‑flatten the model's base so uniting the plinth loses no detail. The seam is one flat plane straight through by default; tick **Contoured** (Split; a Locking Base has its own switch, off by default) and it follows a curved model, but stays a flat plane through the plinth and its socket, through the middle of the base, so each half's share of the socket pulls straight off the teeth. Clamp wings (if on) hug the model only |
| Mold | **Suction Cup Former** *(Open Bottom, with or without the key plate / Locking Base)* | Also prints `MF_Mold_Cup`: a smooth **high‑poly** dome (**Cup Diameter** × **Cup Depth**, diameter 0 = auto ≈70% of the opening) on a plate with four diagonal legs that seat over the open bottom, legs that **fasten** (the pour floats the former - buoyancy): **Pin-Lock** (default, resin-safe - slide ~2 mm pins through the hook channels into shell grooves, zero flex), **Snap-Lock** (printed beads click in - flexible filaments), or **Band Cleats** (rubber bands, no shell cuts). Hollow underside saves filament. The opening and bottom height are measured off the mold itself, so a Locking Base's lower, wider sawtooth socket fits automatically. Cast with the mold inverted: fill, press the former in, and the material cures around the dome — the cast's base comes out as a **suction‑cup bell**. Pop the former out after cure |
| Split | **Mold Pieces** | 2–4. Two = a normal split; 3–4 splits into radial wedges around the vertical axis so undercuts on every side can release (each wedge pulls straight out) |
| Split | **Split with My Planes** + **Add Split Plane** | Your own split planes instead: add as many as you like and move or rotate each one anywhere. Every plane cuts every piece it crosses. With Clamp Wings, each plane gets a bolted flange; a direct mold gets alignment keys on every cut |
| Split | **Horizontal Split** + **Seam Height** | Also split the shell horizontally (XL molds print shorter pieces). The seam gets a profile‑hugging bolted flange ring — size the vertical holes for threaded inserts via **Bolt Diameter** (inserts in the lower lip, screws from the top) |
| Split | **Printer Fit** + **Printer** / **Max Print Height** / **Support Height** | Tick **Printer Fit**, then pick your printer (Anycubic Photon M7 / M7 Pro / M7 Max, M5s, M3, Mono X; Elegoo Mars, Saturn, Jupiter; Phrozen Sonic Mini, Mighty, Mega; Creality Halot; UniFormation GKtwo / GK3; Formlabs Form 4; Peopoly Phenom Forge; Ender‑3, Prusa, Bambu …) or type the height (0 = off). Any shell taller than the limit is cut into equal **stacked levels** — `MF_Mold_A_S1` (bottom) upward — with the bolted mating ring at **every** seam, so each piece fits the plate and the stack bolts back rigid. **Support Height** (default 5 mm) is reserved out of the limit so every level fits **with** its supports/raft. A too‑tall **positive** is cut as well — into glue‑up sections (`MF_Positive_S1` …) that self‑align: **pegs printed on each section's face** (Bolt Diameter, tapered tips) seat into clearance sockets in the next — stack, glue, done, no loose hardware. Nothing touches the cast surface, and seams stay above a Locking Base plinth; untick **Cut Positive Too** to keep it whole. Respects a manual Horizontal Split seam; warns if a piece still exceeds the limit (tall funnel, messy mesh) |
| Split | **Split Axis** | `Auto` picks the axis the model **releases best** along (fewest undercuts), falling back to the wider footprint when equal · or force `X` / `Y` |
| Split | **Parting Offset** | Slide the parting plane off‑centre along the split axis (auto‑clamped so neither half vanishes) |
| Split | **Contoured Parting** | Parting surface follows the model's mid‑profile and self‑registers (falls back to a flat plane). A Locking Base has its own switch (off by default: a flat seam); on, it blends into a flat plane through the plinth and its socket |
| Split | **Alignment Keys** + **Registration** | 0–4 keys on a flat parting: `Cone Keys` (pins into sockets) or `Interlocking Teeth` (a castellated row). For 3+ pieces this becomes **Seam Pins** between wedges |
| Output | **Label** + **Logo** / **Style** / **Letter Height** / **Depth** | Text on one shell, on a thin plaque with rounded corners that follows the shell's curve like a label on a bottle (on a ridged or knobbly shell it rests on the bumps' tops and bridges them), framed by a fine line, its rim chamfered into the shell. The text runs across the shell and reads straight from the front; **Style** cuts the letters in (default) or raises them. By default the silicone and cast weights; fields {silicone_g} {silicone_ml} {cast_g} {cast_ml} {name} {date}, \| for a new line. A **Logo** (a Curve/Text object or an SVG file) sits above the text like a badge, or on its own. Shrinks to fit (down to 3 mm letters; up the shell only when across will not fit) or is skipped with a reason |
| Mold | **Stand Legs** + **Tilt** | *(Pour Box, Open Bottom or Locking Base)* Cast in the pour box itself: when the silicone has cured, take out the positive, turn the mold over onto the pour funnel's mouth and pour the cast into the open base. The funnel carries the weight; short, thin legs from the top of the shell end in feet level with its mouth (one cut planes both) and keep it from tipping. They reach out only as far as the mold's centre of gravity needs (it must tip 10° before it would fall), two per half, off the seam. Tilt cuts the feet and the mouth at an angle so the mold stands tilted and air rises out of one side; it leans to the side that needs the least leg. A few cm³ of plastic |
| Output | **Exploded Preview** | One button under Generate slides every generated part apart to show how the kit assembles; press again to snap back exactly. Display only — Export reassembles first automatically |
| Mold | **Vac‑U‑Lock Plug** | *(Locking Base, or Open Bottom)* prints **`MF_Mold_Plug`** from the bundled **combined Vac‑U‑Lock + suction‑bell former** (`VUL-PLUG.stl`, **always at its original 91.8 mm size — no scaling, nothing to type**) standing on its own socket cross where the toy is thickest (it slides along the cross to the spot where a vertical column stays inside the toy for its full height, the base centre on a symmetric toy) — the sawtooth lips clamp into the shells' grooves. Cast inverted (fill the base, click it in — the bell traps an air cushion that keeps silicone out); demold and the toy's base carries the attachment channel **inside a working suction cup**. A mold too small for the real plug, or a toy with no spot that keeps the column inside, skips it with a note saying why. On an **Open Bottom** the plug rides a ring hub (the bell's hollow stays open underneath) with four legs resting on the shells' rim, hooks up the outer wall, fastened like the suction-cup former |
| Mold | **Dual Density (2‑pour)** + **Soft Wall** | *(Locking Base, or Open Bottom: the core hangs from four legs resting on the shells' rim instead of a socket cross)* firm‑core / soft‑shell kit: **`Core_Master`** = the model **eroded inward by Soft Wall (mm)** — a true offset, so the soft layer is the same thickness on the inside of a bend, the outside, the top and the flanks — riding a bare **+ socket cross carved from the same sawtooth plinth as the positive** — the lips ARE the teeth. Select it and Generate again for its own core mold (that run keeps your main mold as `Kept_*`, Bottom: Flat), cast it in FIRM silicone, then pour **INVERTED**: fill the open base with SOFT and **click the core in — the lips clamp into the grooves and excess burps out the open quadrants**; the layers bond as they cure. Its ridges are rounded to a third of the wall (1 to 3 mm), so no scale edge or vein becomes a sharp blade on the core. Features thinner than twice the wall simply get no core |
| Clamp | **Clamp Wings** + **Wing Width** | Full‑height flanges down each side of the parting line (hugging the model's profile, running up the funnel) to clamp the halves together. With a contoured parting they follow the same curved parting surface as the split, so each half always gets its half of the wing; if a half ends up without a wing along part of the seam, Generate says so |
| Clamp | **Band Notches** | Notches across the wing edges every 30 mm so rubber bands stay put, clear of the bolt holes. On a radial (3-4 piece) mold, a row up every seam's flange |
| Clamp | **Wing Alignment** + **Key Size / Height / Spacing** | `None` · `Cone` (default) · `Half Sphere` · `Half Cone` alignment keys on the wing mating faces of every seam, 2-piece or radial 3–4-piece: a raised key on one piece seats into a matching socket in the other (grown by **Fit Clearance**), so the bolted pieces can't shear. On radial molds a key goes only where the flange stands clear of the mold wall. **Key Size** sets their diameter; **Key Height** how far they stand out (0 = auto, capped by the wing lip — taller punches the socket through the wing as a hole, which still aligns; Half Sphere caps at a hemisphere); **Key Spacing** spreads them along the seam at that pitch (default every 40 mm), dodging the bolt holes |
| Clamp | **Bolt Diameter** + **Auto Bolts** / **Bolts / Side** | Size of the clamp/flange bolt holes. Off by default (no holes: clamp with clips or bands). Tick **Auto Bolts** to place holes by flange height, or set an exact count per side/seam |
| Sprue | **Sprue** + **Throat Radius** + **Funnel Height** + **Mouth Flare** | A real raised pour **funnel** that opens into the cavity. **Throat Radius** is the narrow bottom (the hole into the mold); the mouth is throat × **Mouth Flare** (1.0 = straight tube, up to 4× = wide catch funnel); **Funnel Height** is how far it stands proud. Sizes auto‑fit the mold; tick **Oversized Throat / Oversized Mouth** for **fully manual** funnels (exactly the typed sizes, no cap — you own the result). The panel shows the exact throat Ø / mouth Ø being built |
| Sprue | **Bottom‑Fill Channel** + **Channel Radius** / **Follow Model** + **Smoothing** / **Other Side** | Pour BESIDE the model: a straight pipe on the parting seam outside the case, joined by a fin, with a gate into the cavity just above its floor. The silicone enters at the base and rises evenly (nothing drapes over the master; the top funnel becomes the riser). **Follow Model** runs the pipe along the case, just outside it at every height, instead of straight down at the mold's widest point, so under an overhang (a mushroom's cap) the wing on its side is no wider than it needs to be; the clamp wing carries on over the pipe there, so it is still clamped, keyed and bolted. **Smoothing** (0 to 1, default 0.5) caps how sharply that pipe bends: it leans at most 80° from vertical at 0, 45° at 0.5 and 15° at 1, and smoothing only ever moves the pipe out from the case, never closer. Its radius is its own setting; each half carries half the channel, so the cured sprue lifts out |
| Sprue | **Pour Points** + **Center Sprue** | 1–4 funnels (more helps fill tall figures); centre them on the seam instead of the model's high point |
| Sprue | **Air Vents** + **Vent Radius** | 0–8 thin channels from the cavity's high points to the outside |
| Prep | **Clean Up Model** + **Clean Up Model Now** button | Repairs the model before the build, on Generate's working copy: welds doubled vertices (an unwelded seam), deletes zero-area, duplicate and loose faces and edges, drops tiny stray fragments (under 2% of the model's size), fills small holes (up to 12 edges, or anything under 10% of the model's size; a big opening such as a hollow underside stays open) and points every face outward. It runs before the build checks the model is watertight, so a model it repairs builds at full detail instead of being auto-remeshed, and the positive comes out clean. The button does the same, plus Fix Flat Bottom, to your model itself (with undo) |
| Prep | **Reduce Polygons** + **Keep** | Decimates the model to that fraction of its polygons before the build, to speed up a heavy sculpt. Repairs nothing |
| Prep | **Rebuild as Solid (remesh)** + **Voxel Size** | Voxel-remeshes the whole model into a fresh watertight solid: for a mesh Clean Up can't repair (self-intersecting, many pieces). Softens detail finer than the voxel. Without it, a model still not watertight after Clean Up is remeshed automatically for the mold (the positive keeps full detail) |
| Prep | **Fix Flat Bottom** + **Fix Model's Flat Bottom** button | A boolean cut leaves the model's flat bottom as one face that, once triangulated, is a fan of needle-thin triangles; later booleans (the plinth, the plate, the shell) struggle with it. With **Fix Flat Bottom** on (default) Generate rebuilds such a bottom on its working copy as an even triangle mesh, levelled within 0.3 mm (holes and a hollow underside stay open); if the bottom's outline is broken, or there are open edges within 2 mm of it, the copy is sliced flat just above them and filled. The button does the same to the selected model itself (with undo). A clean single-polygon bottom is left alone |
| Prep | **Mold Detail** | Polygon density of the mold body and clamp wings where they're rebuilt on a voxel grid (messy or heavy models): 2 (default) is twice as fine as the original 1, up to 8. The positive always keeps full detail |
| Material | **Silicone / Cast / Print density** | g/ml, used for the weight estimate (RTV silicone ≈ 1.1–1.2, resin ≈ 1.1, PLA ≈ 1.24) |

The panel reports the **silicone** (the pour amount, or the thin skin for a glove
mold), the **printed plastic**, and the **cast material** volume — in millilitres
**and grams** (using the densities above, in your scene's units).

## How it works

1. **Prep** — duplicate the model, optionally heal/decimate, and center it. A
   non‑manifold or very heavy mesh is voxel‑remeshed into a clean watertight solid.
2. **Shell**
   - *Pour Box*: `dilate(model, gap + shell) − dilate(model, gap)` (two `Solidify`
     passes + a boolean) gives a hollow jacket whose cavity is the model plus a
     uniform silicone gap; the `inner − model` solid is kept as the `MF_Skin`
     preview. With **Glove Skin Keys**, registration bumps are raised on the
     silicone (matching pockets end up in the jacket).
   - *Direct mold, Hugging*: one `Solidify` wraps the model in a uniform shell
     whose enclosed void is the casting cavity.
   - *Direct mold, Block*: a bounding box minus the model.
   - *Tray*: an open box around the object's footprint (rectangular, or a rounded
     hug of the outline: the whole footprint seen from above, grown by the
     Border, so every part of the object stays inside); the object is laid flat, unioned into the floor (Embed)
     or left out (Frame), and the top is left open — no split, wings or funnel.
3. **Sprue & vents** — the solid funnel spout(s) are unioned on first (so wings can
   run up them), then bored through into the cavity *after* the wings, so the bore
   is always clear. Vents are cut from the cavity's high points, kept clear of the
   funnel mouths.
4. **Bottom** — `Flat` cuts a Z‑plane keeping a closed floor (the **Mounting
   Flange** adds a bolted skirt); `Open` cuts at the master's base so the cavity
   is open — its **Detachable Key Plate** instead emits a separate `MF_Mold_Base`
   whose pocket registers the model (and seals the pour) while a ring tongue on
   every shell piece's rim drops into a groove around the plate's chin collar; `Follow` leaves the bottom
   shaped to the model; `Locking Base` (pour box) builds a sawtooth **plinth** from
   the model's footprint, unites it into the high‑poly positive, and gives the
   shells a matching **tolerance socket** (smooth outside, toothed inside, sealed
   rim) with an open bottom so the master locks onto the base and can't slip.
5. **Split**
   - *2 pieces*: pick the pull axis (Auto = least undercut), then either a
     ray‑cast **contoured** mid‑profile parting (self‑registering) or a flat plane
     with cone keys / interlocking teeth, plus optional clamp wings.
   - *3–4 pieces*: intersect the mold with **radial pie‑slice prisms** to get
     wedges that each pull straight out, with a best‑effort vertical seam pin
     (ridge + groove) registering neighbours.
6. **Undercut check** — rays along the pull axis flag trapped pockets; you get a
   warning (with the % and axis) if the model may not release cleanly.
7. **Volume & weight** — `bmesh.calc_volume` on the silicone, the printed parts,
   and the model, scaled by your material densities.
8. **Export** — a small binary‑STL writer (works in any context, incl. headless).

## Test

```bash
blender --background --python moldforge/tests/test_headless.py
```

Builds molds across every mold type, piece count, base, and split mode; checks the
parts are watertight single solids with sane proportions at 2/20/200‑unit scales;
verifies the glove skin uses far less silicone than a thick pour and that radial
wedges tile the same mold; exercises auto‑orientation and the undercut metric; and
round‑trips STL export. Exits non‑zero on failure.

## Robustness

MoldForge validates its result (finite, watertight, single connected solid) and
never writes a broken STL. So:

- **Detailed / thin‑feature models** (fine surface texture, fins) make the offset
  shell shatter. MoldForge detects this and **auto‑remeshes once and retries** —
  Generate just works, with a warning that fine detail was smoothed.
- **Messy / heavy meshes**: a non‑manifold mesh makes the fast boolean solver bail,
  and a million‑poly mesh is painfully slow — so MoldForge voxel‑remeshes the model
  into a clean, light, watertight solid first. A 1M‑poly non‑manifold scan molds in
  ~30 s instead of failing.
- **Deep undercuts**: `Auto` already orients the split to release best; if a half
  still won't separate, MoldForge retries the other axis (and a coarse remesh)
  before giving up, and as a last resort trims a *minor* severed fragment to keep
  each piece one solid. For undercuts on every side, raise **Mold Pieces** to 3–4
  for a radial split. If it genuinely can't make a clean mold, the error reports how
  the piece broke up (e.g. "3 pieces: 88%, 7%, 5%") and suggests what to change.
- **Deeply concave models** (a hook, horseshoe, C‑shape) shed a few tiny slivers
  along the concavity; MoldForge strips those few‑face artifacts so the parts come
  out as clean single solids.
- **Clamp wings and seam pins** are best‑effort: each is welded only where it
  actually overlaps the body and rolled back if it would ever leave a piece broken,
  so registration features can never wreck an otherwise‑good mold.
- **Separate‑piece, NaN, and degenerate** models are rejected up front or caught at
  the output stage with a clear message and no leftover objects.
- Regenerating only ever clears MoldForge's own `MF_*` objects — your own objects
  are never deleted, even if they live in a "MoldForge" collection.

## Limitations

- Contoured 2‑part parting works best on convex‑ish, centered models; for trickier
  shapes use `Auto` orientation, interlocking teeth, or 3–4 pieces.
- Very thin walls relative to model size limit how large alignment keys can be
  (keys are auto‑clamped to the wall thickness).
- Sprue/vents are placed at the model's highest vertices; complex tops may want
  manual touch‑up.
- Radial multi‑part registration is a light seam pin plus the shared flange — band
  or clamp the wedges together when casting.

## License

GPL-3.0-or-later.
