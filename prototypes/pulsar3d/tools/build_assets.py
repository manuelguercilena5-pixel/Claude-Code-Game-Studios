"""Builds PULSAR's 3D models in Blender and exports them as one GLB.

Run headless:  uv run --python 3.11 --with bpy==4.2.0 python tools/build_assets.py [--preview DIR]

Every object uses two materials: "Body" (dark metal, tinted per entity at runtime)
and "Glow" (emissive trim, coloured per entity at runtime). Object names are the
contract with the game: Player, Drifter, Chaser, Splitter, Dasher.
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
def build_player(body, glow, glass):
    bm = bmesh.new()
    # fuselage: nose at +Y
    loft(bm, [(1.25, 0.02, 0.02, 0.02), (0.75, 0.16, 0.12, 0.03), (0.15, 0.27, 0.19, 0.05),
              (-0.45, 0.30, 0.2, 0.03), (-0.85, 0.22, 0.15, 0.0)], mat=0)
    # swept wings (mirrored)
    for s in (1, -1):
        wing = [(0.18 * s, 0.35), (1.05 * s, -0.55), (1.0 * s, -0.78), (0.25 * s, -0.62)]
        if s < 0:
            wing.reverse()
        prism(bm, wing, -0.035, 0.035, mat=0)
        # glowing leading-edge strip
        strip = [(0.2 * s, 0.39), (1.09 * s, -0.53), (1.06 * s, -0.47), (0.24 * s, 0.3)]
        if s < 0:
            strip.reverse()
        prism(bm, strip, -0.02, 0.05, mat=1)
        # wingtip fin
        fin = [(0.98 * s, -0.5), (1.0 * s, -0.8), (1.02 * s, -0.8)]
        if s < 0:
            fin.reverse()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=0.05, radius2=0.0, depth=0.32,
                              matrix=Matrix.Translation((1.0 * s, -0.62, 0.15)))
        # engine pod + emissive exhaust
        pod = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.11, radius2=0.13, depth=0.55,
                                    matrix=Matrix.Translation((0.38 * s, -0.62, -0.02)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
        ex = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.085, radius2=0.085, depth=0.06,
                                   matrix=Matrix.Translation((0.38 * s, -0.92, -0.02)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
        for v in ex["verts"]:
            for f in v.link_faces:
                f.material_index = 1
    # central exhaust
    ex = bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.15, radius2=0.12, depth=0.08,
                               matrix=Matrix.Translation((0, -0.88, 0.0)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
    for v in ex["verts"]:
        for f in v.link_faces:
            f.material_index = 1
    # cockpit canopy
    can = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0,
                                     matrix=Matrix.Translation((0, 0.22, 0.17)) @ Matrix.Diagonal((0.13, 0.38, 0.09, 1)))
    for v in can["verts"]:
        for f in v.link_faces:
            f.material_index = 2
    ob = mesh_obj("Player", bm, [body, glow, glass])
    return finish(ob, bevel=0.012)


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
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.3)
    faces = list(bm.faces)
    seams(bm, faces, frame=0.12, seam=0.045, depth=0.09)
    # spikes on the 8 corners
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                d = Vector((x, y, z)).normalized()
                rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
                sp = bmesh.ops.create_cone(bm, cap_ends=True, segments=3, radius1=0.12, radius2=0.0, depth=0.4,
                                           matrix=Matrix.Translation(d * 1.1) @ rot)
    ob = mesh_obj("Chaser", bm, [body, glow])
    return finish(ob, bevel=0.03)


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
    bm = bmesh.new()
    # arrowhead hull, nose at +Y
    loft(bm, [(1.2, 0.02, 0.02, 0.0), (0.4, 0.42, 0.18, 0.02), (-0.5, 0.75, 0.16, 0.0), (-0.75, 0.5, 0.12, 0.0)], mat=0)
    for s in (1, -1):
        blade = [(0.3 * s, 0.4), (1.0 * s, -0.95), (0.6 * s, -0.7)]
        if s < 0:
            blade.reverse()
        prism(bm, blade, -0.05, 0.05, mat=0)
        trim = [(0.32 * s, 0.45), (1.06 * s, -1.0), (0.98 * s, -0.88), (0.3 * s, 0.32)]
        if s < 0:
            trim.reverse()
        prism(bm, trim, -0.03, 0.07, mat=1)
    # dorsal spine glow
    prism(bm, [(-0.04, 1.05), (0.04, 1.05), (0.06, -0.6), (-0.06, -0.6)], 0.12, 0.24, mat=1)
    ex = bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.2, radius2=0.14, depth=0.1,
                               matrix=Matrix.Translation((0, -0.8, 0.0)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
    for v in ex["verts"]:
        for f in v.link_faces:
            f.material_index = 1
    ob = mesh_obj("Dasher", bm, [body, glow])
    return finish(ob, bevel=0.015)


def build_all():
    reset()
    body = material("Body", (0.035, 0.035, 0.05), metal=0.85, rough=0.32)
    glow = material("Glow", (1, 1, 1), emit=4.0)
    glass = material("Glass", (0.2, 0.9, 1.0), emit=0.6, metal=0.2, rough=0.08)
    objs = [build_player(body, glow, glass), build_drifter(body, glow), build_chaser(body, glow),
            build_splitter(body, glow), build_dasher(body, glow)]
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
            "Splitter": (0.49, 1, 0.31), "Dasher": (1, 0.69, 0)}
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
