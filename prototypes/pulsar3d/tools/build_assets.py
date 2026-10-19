"""Builds PULSAR's 3D models in Blender and exports them as one GLB.

Run headless:  uv run --python 3.11 --with bpy==4.2.0 python tools/build_assets.py [--preview DIR]

Every object uses two materials: "Body" (dark metal, tinted per entity at runtime)
and "Glow" (emissive trim, coloured per entity at runtime). Object names are the
contract with the game: Player, Drifter, Chaser, Splitter, Dasher, Warden (+WardenRing), Quiet (+QuietRing).
"""
import math
import os
import sys

import bpy  # must come first: it registers bmesh/mathutils
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "pulsar.glb")


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color, emit=0.0, metal=0.0, rough=0.5):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Metallic"].default_value = metal
    p.inputs["Roughness"].default_value = rough
    if emit:
        p.inputs["Emission Color"].default_value = (*color, 1)
        p.inputs["Emission Strength"].default_value = emit
    return m


def mesh_obj(name, bm, mats):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    for m in mats:
        me.materials.append(m)
    return ob


def loft(bm, sections, mat=0):
    """sections: list of (y, half_w, half_h, z) → hexagonal hull, capped."""
    rings = []
    for y, w, h, z in sections:
        prof = [(0, h), (w * 0.85, h * 0.45), (w, -h * 0.25), (0, -h), (-w, -h * 0.25), (-w * 0.85, h * 0.45)]
        rings.append([bm.verts.new((x, y, z + zz)) for x, zz in prof])
    for a, b in zip(rings, rings[1:]):
        for i in range(6):
            f = bm.faces.new((a[i], a[(i + 1) % 6], b[(i + 1) % 6], b[i]))
            f.material_index = mat
    for r, rev in ((rings[0], True), (rings[-1], False)):
        f = bm.faces.new(list(reversed(r)) if rev else r)
        f.material_index = mat
    return rings


def prism(bm, pts2d, z0, z1, mat=0):
    """Extrude a 2D polygon (x, y) between heights z0..z1."""
    lo = [bm.verts.new((x, y, z0)) for x, y in pts2d]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts2d]
    n = len(pts2d)
    faces = [bm.faces.new(list(reversed(lo))), bm.faces.new(hi)]
    for i in range(n):
        faces.append(bm.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i])))
    for f in faces:
        f.material_index = mat
    return faces


def seams(bm, faces, frame=0.08, seam=0.035, depth=0.05):
    """Body frame → thin glowing seam → sunken body panel, on every given face."""
    outer = bmesh.ops.inset_individual(bm, faces=faces, thickness=frame, depth=0)
    for f in outer["faces"]:
        f.material_index = 0
    mid = bmesh.ops.inset_individual(bm, faces=faces, thickness=seam, depth=-depth)
    for f in mid["faces"]:
        f.material_index = 1
    for f in faces:
        f.material_index = 0


def finish(ob, bevel=0.025, segments=1):
    """Bevel for catch-lights, flat shading for the faceted neon-sculpture look."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-4)  # zero-area faces export NaN normals
    bm.to_mesh(ob.data)
    bm.free()
    if bevel:
        mod = ob.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(35)
        mod.harden_normals = True
    for p in ob.data.polygons:
        p.use_smooth = False
    return ob


# --------------------------------------------------------------------- player
def ring_verts(bm, r, z, n=12, off=0.0):
    return [bm.verts.new((math.cos(off + i * 2 * math.pi / n) * r, math.sin(off + i * 2 * math.pi / n) * r, z)) for i in range(n)]


def band(bm, a, b, mat):
    faces = []
    for i in range(len(a)):
        f = bm.faces.new((a[i], a[(i + 1) % len(a)], b[(i + 1) % len(b)], b[i]))
        f.material_index = mat
        faces.append(f)
    return faces


def build_player(body, glow, glass):
    """A lens-shaped star shard with a forward beam blade: round, so it never reads as a Dasher arrowhead."""
    bm = bmesh.new()
    n = 12
    top, eq, bot = ring_verts(bm, 0.28, 0.14, n), ring_verts(bm, 0.62, 0.0, n), ring_verts(bm, 0.28, -0.14, n)
    upper = band(bm, top, eq, 0)
    band(bm, eq, bot, 0)
    bm.faces.new(top).material_index = 0
    bm.faces.new(list(reversed(bot))).material_index = 0
    seams(bm, upper, frame=0.05, seam=0.025, depth=0.03)
    # equator light band
    bmesh.ops.create_cone(bm, cap_ends=False, segments=n, radius1=0.655, radius2=0.655, depth=0.05)
    for f in bm.faces:
        if f.material_index == 0 and all(abs(math.hypot(v.co.x, v.co.y) - 0.655) < 1e-3 for v in f.verts):
            f.material_index = 1
    # beam blades (rolled 12 deg, a nod to the pulsar's tilted axis)
    roll = Matrix.Rotation(math.radians(12), 4, "Y")
    for pts, glo, z in (([(-0.16, 0.5), (0.16, 0.5), (0.02, 1.35), (-0.02, 1.35)], [(-0.04, 0.55), (0.04, 0.55), (0.01, 1.3), (-0.01, 1.3)], 0.05),
                        ([(0.12, -0.5), (-0.12, -0.5), (-0.03, -0.95), (0.03, -0.95)], [(0.04, -0.52), (-0.04, -0.52), (-0.01, -0.9), (0.01, -0.9)], 0.045)):
        fs = prism(bm, pts, -z, z, mat=0) + prism(bm, glo, z, z + 0.04, mat=1)
        verts = {v for f in fs for v in f.verts}
        bmesh.ops.transform(bm, matrix=roll, verts=list(verts))
    # twin engine pods
    for s in (1, -1):
        ex = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.08, radius2=0.08, depth=0.22,
                                   matrix=Matrix.Translation((0.34 * s, -0.48, 0.0)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
        for v in ex["verts"]:
            for f in v.link_faces:
                f.material_index = 1
    core = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0,
                                      matrix=Matrix.Translation((0, 0, 0.12)) @ Matrix.Diagonal((0.24, 0.24, 0.17, 1)))
    for v in core["verts"]:
        for f in v.link_faces:
            f.material_index = 2
    ob = mesh_obj("Player", bm, [body, glow, glass])
    return finish(ob, bevel=0.01)


# -------------------------------------------------------------------- drifter
def build_drifter(body, glow):
    bm = bmesh.new()
    # elongated octahedral crystal
    top, bot = bm.verts.new((0, 0, 0.75)), bm.verts.new((0, 0, -0.75))
    eq = [bm.verts.new((math.cos(a) * 0.7, math.sin(a) * 0.7, 0)) for a in [i * math.pi / 2 for i in range(4)]]
    for i in range(4):
        bm.faces.new((eq[i], eq[(i + 1) % 4], top))
        bm.faces.new((eq[(i + 1) % 4], eq[i], bot))
    seams(bm, list(bm.faces), frame=0.07, seam=0.03, depth=0.05)
    ob = mesh_obj("Drifter", bm, [body, glow])
    finish(ob, bevel=0.02)
    # torus ring as separate glow child for spin at runtime
    bpy.ops.mesh.primitive_torus_add(major_radius=1.05, minor_radius=0.035, major_segments=40, minor_segments=6)
    t = bpy.context.active_object
    t.name = "DrifterRing"
    t.data.materials.append(glow)
    t.parent = ob
    return ob


# --------------------------------------------------------------------- chaser
def build_chaser(body, glow):
    """A spiked icosahedral hunter: organic, aggressive, nothing like a crate."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=0, radius=0.72)
    faces = list(bm.faces)
    centers = [(f.calc_center_median().copy(), f.normal.copy()) for f in faces]
    seams(bm, faces, frame=0.05, seam=0.03, depth=0.06)
    for i, (c, nrm) in enumerate(centers):
        if i % 5 in (0, 2):  # 8 of the 20 faces carry a spike
            rot = nrm.to_track_quat("Z", "Y").to_matrix().to_4x4()
            sp = bmesh.ops.create_cone(bm, cap_ends=True, segments=3, radius1=0.13, radius2=0.0, depth=0.5,
                                       matrix=Matrix.Translation(c + nrm * 0.22) @ rot)
            tip = max(sp["verts"], key=lambda v: (v.co - c).length)
            for f in tip.link_faces:
                f.material_index = 1
    ob = mesh_obj("Chaser", bm, [body, glow])
    return finish(ob, bevel=0.02)


# ------------------------------------------------------------------- splitter
def build_splitter(body, glow):
    bm = bmesh.new()
    for k in range(4):
        a = k * math.pi / 2
        c, s = math.cos(a), math.sin(a)
        blade = [(0.15, 0.1), (1.05, 0.0), (0.2, 0.95)]
        pts = [(x * c - y * s, x * s + y * c) for x, y in blade]
        prism(bm, pts, -0.12, 0.12, mat=0)
        edge = [(1.05, 0.0), (0.2, 0.95), (0.19, 0.9), (0.99, 0.0)]
        pts = [(x * c - y * s, x * s + y * c) for x, y in edge]
        prism(bm, pts, -0.13, 0.13, mat=1)
    hub = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.2)
    for v in hub["verts"]:
        for f in v.link_faces:
            f.material_index = 1
    ob = mesh_obj("Splitter", bm, [body, glow])
    return finish(ob, bevel=0.015)


# --------------------------------------------------------------------- dasher
def build_dasher(body, glow):
    """A split chevron: two blades around a burning slot, tail of diamonds behind."""
    bm = bmesh.new()
    for sgn in (1, -1):
        blade = [(0.06 * sgn, 1.0), (0.75 * sgn, -0.7), (0.5 * sgn, -0.85), (0.06 * sgn, 0.2)]
        trim = [(0.75 * sgn, -0.7), (0.06 * sgn, 1.0), (0.1 * sgn, 1.05), (0.82 * sgn, -0.68)]
        inner = [(0.06 * sgn, 0.2), (0.06 * sgn, 1.0), (0.03 * sgn, 0.98), (0.03 * sgn, 0.24)]
        for pts in (blade, trim, inner):
            if sgn < 0:
                pts.reverse()
        prism(bm, blade, -0.09, 0.09, mat=0)
        prism(bm, trim, -0.06, 0.11, mat=1)
        prism(bm, inner, -0.07, 0.07, mat=1)
    for k, (y, r) in enumerate(((-0.95, 0.14), (-1.25, 0.11), (-1.5, 0.08))):
        d = [(0, y + r), (r * 0.7, y), (0, y - r), (-r * 0.7, y)]
        prism(bm, d, -0.04, 0.04, mat=1)
    ob = mesh_obj("Dasher", bm, [body, glow])
    return finish(ob, bevel=0.012)


# --------------------------------------------------------------------- bosses
def build_warden(body, glow, glass):
    """The Warden: a seamed core with a glass eye, and a segmented ring that spins at runtime."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.6)
    faces = list(bm.faces)
    seams(bm, faces[::2], frame=0.03, seam=0.018, depth=0.035)
    eye = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0,
                                     matrix=Matrix.Translation((0, 0, 0.42)) @ Matrix.Diagonal((0.27, 0.27, 0.2, 1)))
    for v in eye["verts"]:
        for f in v.link_faces:
            f.material_index = 2
    ob = mesh_obj("Warden", bm, [body, glow, glass])
    finish(ob, bevel=0.01)
    rb = bmesh.new()
    seg, gap = 6, math.radians(8)
    for k in range(seg):
        a0, a1 = k * 2 * math.pi / seg + gap / 2, (k + 1) * 2 * math.pi / seg - gap / 2
        steps = 6
        arc = [(math.cos(a0 + (a1 - a0) * i / steps), math.sin(a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]
        pts = [(c * 0.84, s_ * 0.84) for c, s_ in arc] + [(c * 1.0, s_ * 1.0) for c, s_ in reversed(arc)]
        prism(rb, pts, -0.08, 0.08, mat=0)
        strip = [(c * 1.0, s_ * 1.0) for c, s_ in arc] + [(c * 1.04, s_ * 1.04) for c, s_ in reversed(arc)]
        prism(rb, strip, -0.05, 0.05, mat=1)
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        rot = Vector((math.cos(a), math.sin(a), 0)).to_track_quat("Z", "Y").to_matrix().to_4x4()
        em = bmesh.ops.create_cone(rb, cap_ends=True, segments=6, radius1=0.09, radius2=0.0, depth=0.28,
                                   matrix=Matrix.Translation((math.cos(a) * 1.14, math.sin(a) * 1.14, 0)) @ rot)
        for v in em["verts"]:
            for f in v.link_faces:
                f.material_index = 1
    ring = mesh_obj("WardenRing", rb, [body, glow, glass])
    finish(ring, bevel=0.008)
    ring.parent = ob
    return ob


def build_quiet(body, glow):
    """The Quiet: a pulsar-shaped hole. A matte black sphere, a hairline halo, two dead beam stubs."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=0.8)
    for s_ in (1, -1):
        st = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.12, radius2=0.0, depth=0.6,
                                   matrix=Matrix.Translation((0, 0, 0.95 * s_)) @ Matrix.Rotation(0 if s_ > 0 else math.pi, 4, "X"))
        for v in st["verts"]:
            for f in v.link_faces:
                f.material_index = 1
    ob = mesh_obj("Quiet", bm, [body, glow])
    finish(ob, bevel=0)
    for p in ob.data.polygons:
        p.use_smooth = True
    bpy.ops.mesh.primitive_torus_add(major_radius=1.2, minor_radius=0.02, major_segments=64, minor_segments=6)
    t = bpy.context.active_object
    t.name = "QuietRing"
    t.data.materials.append(glow)
    t.parent = ob
    return ob


def build_all():
    reset()
    body = material("Body", (0.035, 0.035, 0.05), metal=0.85, rough=0.32)
    glow = material("Glow", (1, 1, 1), emit=4.0)
    glass = material("Glass", (0.2, 0.9, 1.0), emit=0.6, metal=0.2, rough=0.08)
    objs = [build_player(body, glow, glass), build_drifter(body, glow), build_chaser(body, glow),
            build_splitter(body, glow), build_dasher(body, glow), build_warden(body, glow, glass), build_quiet(body, glow)]
    for i, ob in enumerate(objs):
        ob.location = (0, 0, 0)
    return objs


def export(objs):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_apply=True, use_selection=True,
                              export_yup=True, export_normals=True, export_materials="EXPORT")
    print("exported", os.path.abspath(OUT), os.path.getsize(OUT), "bytes")


def preview(objs, outdir):
    """Cycles CPU render of each model on a dark stage, for visual QA."""
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 48
    sc.render.resolution_x, sc.render.resolution_y = 640, 480
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - High Contrast"
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.01, 0.004, 0.03, 1)
    sc.world = world
    tint = {"Player": (0, 0.94, 1), "Drifter": (0.69, 0.3, 1), "Chaser": (1, 0.18, 0.53),
            "Splitter": (0.49, 1, 0.31), "Dasher": (1, 0.54, 0), "Warden": (1, 0.18, 0.53), "Quiet": (1, 1, 1)}
    bpy.ops.object.light_add(type="AREA", location=(2.5, -2.5, 4))
    key = bpy.context.active_object
    key.data.energy = 300
    key.data.size = 3
    key.rotation_euler = (math.radians(40), 0, math.radians(45))
    bpy.ops.object.light_add(type="AREA", location=(-3, 2, 1.5))
    rim = bpy.context.active_object
    rim.data.energy = 220
    rim.data.color = (1, 0.2, 0.6)
    rim.rotation_euler = (math.radians(70), 0, math.radians(-120))
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    for ob in objs:
        ob.hide_render = True
        for c in ob.children:
            c.hide_render = True
    for ob in objs:
        ob.hide_render = False
        for c in ob.children:
            c.hide_render = False
        g = bpy.data.materials["Glow"].node_tree.nodes["Principled BSDF"]
        g.inputs["Emission Color"].default_value = (*tint[ob.name], 1)
        g.inputs["Emission Strength"].default_value = 2.0
        g.inputs["Base Color"].default_value = (*tint[ob.name], 1)
        cam.location = (2.6, -3.4, 2.4)
        direction = Vector((0, 0, 0)) - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(outdir, ob.name + ".png")
        bpy.ops.render.render(write_still=True)
        ob.hide_render = True
        for c in ob.children:
            c.hide_render = True


if __name__ == "__main__":
    objs = build_all()
    export(objs)
    if "--preview" in sys.argv:
        preview(objs, sys.argv[sys.argv.index("--preview") + 1])
