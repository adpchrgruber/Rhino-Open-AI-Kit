#! python3
# Rhino Open AI Kit - offline AI assistant for Rhino 8 (CPython 3)
#
# Talks to a local llama.cpp server (OpenAI-compatible API) and lets the
# model act on the Rhino document through a small set of tools.
# No pip packages needed: only the Python standard library + RhinoCommon.
#
# Run:  _-RunPythonScript "<kit>/rhino/rhino_ai.py"
# Alias suggestion:  AI  ->  ! _-RunPythonScript "<kit>/rhino/rhino_ai.py"

import os
import sys
import json
import time
import base64
import tempfile
import threading
import traceback
import subprocess
import io
import contextlib
import urllib.request
import urllib.error

import System
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import Eto.Forms as forms
import Eto.Drawing as drawing


# ---------------------------------------------------------------- settings

def find_kit_dir():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        kit = os.path.dirname(here)
        if os.path.isfile(os.path.join(kit, "kit.conf")):
            return kit
    except NameError:
        pass
    remembered = sc.sticky.get("rhino_ai_kit_dir")
    if remembered and os.path.isfile(os.path.join(remembered, "kit.conf")):
        return remembered
    path = rs.OpenFileName("Locate kit.conf of Rhino Open AI Kit", "kit.conf|kit.conf||")
    if not path:
        return None
    return os.path.dirname(path)


def load_conf(kit):
    conf = {}
    with open(os.path.join(kit, "kit.conf"), "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            conf[key.strip()] = value.strip()
    return conf


# ---------------------------------------------------------------- server

def server_url(conf):
    return "http://127.0.0.1:%s" % conf.get("PORT", "8080")


def server_alive(conf, timeout=1.5):
    try:
        with urllib.request.urlopen(server_url(conf) + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_server(kit):
    """Launch the platform start script in its own terminal window."""
    if sys.platform == "darwin":
        script = os.path.join(kit, "start-mac.command")
        os.chmod(script, 0o755)
        subprocess.Popen(["open", "-a", "Terminal", script])
    else:
        script = os.path.join(kit, "start-win.bat")
        subprocess.Popen(["cmd", "/c", "start", "", script], cwd=kit)


def wait_for_server(conf, seconds=180, on_tick=None):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if server_alive(conf):
            return True
        if on_tick:
            on_tick(int(time.time() - t0))
        time.sleep(2)
    return False


def chat(conf, messages, tools):
    body = {
        "messages": messages,
        "tools": tools,
        "temperature": float(conf.get("TEMPERATURE", "0.4")),
        "stream": False,
    }
    if conf.get("THINKING", "0") != "1":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(
        server_url(conf) + "/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]


# ---------------------------------------------------------------- tools

SYSTEM_PROMPT = """You are an assistant inside Rhinoceros 3D (Rhino 8) for an architecture and design studio.
You act on the open Rhino document through tools. Document units are given by get_scene_info.

Rules:
- Call get_scene_info first when you need to know what is in the model.
- To create or change geometry call run_python with complete Python 3 code.
- Do NOT write import lines for ai, Rhino, sc, rs or System. They are already available.
- Model real objects with real proportions in the document units, one layer per material or element,
  named "Object::Element_Material". Round things are revolved profiles, not boxes.
- PREFER the ready-made helper module `ai` (already available in run_python):
    ai.box(x, y, z, sx, sy, sz, layer=None)        box with corner at (x,y,z) and sizes sx,sy,sz -> id
    ai.sphere(x, y, z, radius, layer=None)         -> id
    ai.cylinder(x, y, z, radius, height, layer=None)   vertical, base centre at (x,y,z) -> id
    ai.line((x1,y1,z1), (x2,y2,z2), layer=None)    -> id
    ai.polyline([(x,y,z), ...], closed=False, layer=None) -> id
    ai.circle(x, y, z, radius, layer=None)         -> id
    ai.extrude(curve_id, height, cap=True, layer=None) extrude a planar curve along Z -> id
    ai.move(ids, dx, dy, dz)   ai.copy(ids, dx, dy, dz) -> new ids
    ai.rotate(ids, angle_degrees, center=None)   ai.scale(ids, factor, center=None)
        center=None: each object turns/scales about its OWN centre. Give (cx,cy,cz) for a common centre.
    ai.objects(layer=None, name=None) -> ids of all objects (optionally filtered)   ai.center(id) -> (x,y,z)
    ai.delete(ids)   ai.select(ids)   ai.selected() -> ids
    ai.layer(name, (r,g,b)=None)                   create layer if missing -> name
    ai.set_layer(ids, name)   ai.set_name(ids, name)
    ai.bbox(ids) -> ((minx,miny,minz),(maxx,maxy,maxz))
    ai.boolean_union(ids)  ai.boolean_difference(ids_a, ids_b) -> ids
  2D drawing and curves (all on the XY plane at height z):
    ai.point(x, y, z=0)   ai.rectangle(x, y, w, h, z=0, corner_radius=0)   ai.polygon(cx, cy, radius, sides)
    ai.arc(cx, cy, radius, start_degrees, end_degrees)   ai.ellipse(cx, cy, rx, ry)
    ai.curve([(x,y,z), ...], through_points=True, closed=False)   smooth curve through / controlled by points
    ai.offset(curve_id, distance) -> ids   closed curve: positive = outward, negative = inward
    ai.fillet(curve_id, radius)   round all corners      ai.join(curve_ids) -> ids
    ai.divide(curve_id, count, add_points=False) -> [(x,y,z), ...] evenly spaced positions
    ai.length(curve_id)   ai.area(id)   ai.is_closed(curve_id)
    ai.curve_union(ids)   ai.curve_difference(id_a, ids_b)   ai.curve_intersection(id_a, id_b) -> ids
    ai.planar_surface(curve_ids) -> ids   ai.loft(curve_ids) -> ids   ai.pipe(curve_id, radius) -> ids
  Spatial arrangement (use these instead of calculating positions yourself):
    ai.describe(ids=None) -> list of {id, type, layer, name, center, size, min, max}   LOOK before you edit
    ai.move_to(id, x, y, z, anchor="center")     anchor: "center", "bottom" (bottom centre) or "corner"
    ai.array_grid(ids, nx, ny, dx, dy, nz=1, dz=0) -> all ids      ai.array_polar(ids, count, (cx,cy,cz), 360) -> all ids
    ai.array_along_curve(id, curve_id, count, rotate=True) -> new ids
    ai.align(ids, axis="x", mode="min")   mode "min"/"center"/"max"; e.g. axis="z", mode="min" puts all on one floor
    ai.distribute(ids, axis="x", gap=None)   gap=None: even spacing; gap=50: 50 units clear between neighbours
    ai.mirror(ids, axis="x", at=0, copy=True)   ai.place_on_surface(id, surface_id, u=0.5, v=0.5)   ai.distance(id_a, id_b)
  Layers, materials, round objects:
    ai.layer("Bottle::Body", (r,g,b))    "Parent::Child" makes nested layers
    ai.tube([(x,y,z), ...], radius, smooth=True, layer=None) -> id   solid round tube through 3D points.
        Use it for handles, spouts, legs, rails. Example handle on the +X side of a pot of radius 50:
        ai.tube([(48,0,150),(85,0,150),(95,0,100),(85,0,50),(48,0,50)], 6, layer="Kettle::Handle_Plastic")
        Example spout on the -X side, rising outward: ai.tube([(-45,0,90),(-70,0,130),(-85,0,165)], 9)
    ai.material(layer, (r,g,b), transparency=0.0, shine=0.3)   render material on a layer; 0.8 = glass/water
    ai.revolve([(radius, z), ...], cx=0, cy=0, smooth=False, cap=True, layer=None) -> id   lathe a profile around a
        vertical axis. Use it for bottles, vases, bowls, lamps, columns. Points go from bottom to top.
        cap=True closes it to a solid; cap=False leaves an open skin (label, sleeve, shade).
  Example, a bottle with layers per element and material:
    ai.material("Bottle::Body_PET", (220, 235, 245), transparency=0.7)
    ai.material("Bottle::Water", (120, 190, 255), transparency=0.8)
    ai.material("Bottle::Cap_HDPE", (30, 90, 200))
    ai.material("Bottle::Label_Paper", (245, 245, 235))
    body = ai.revolve([(0,0),(33,0),(35,5),(35,140),(30,165),(13,185),(13,205),(0,205)], smooth=False, layer="Bottle::Body_PET")
    water = ai.revolve([(0,2),(33,2),(33,130),(0,130)], layer="Bottle::Water")
    cap = ai.cylinder(0, 0, 195, 15, 14, layer="Bottle::Cap_HDPE")
    label = ai.revolve([(35.3,50),(35.3,110)], cap=False, layer="Bottle::Label_Paper")
    print("bottle parts:", 4)
  Coordinates: X = right, Y = back (plan view is XY), Z = up. A floor plan is drawn at z=0.
  Example, a 10 x 10 grid of boxes on a 30 mm grid:
    ids = [ai.box(i*30, j*30, 0, 25, 25, 25) for i in range(10) for j in range(10)]
    print(len(ids), "boxes")
- For anything else use RhinoCommon (Rhino, sc, rs, System are imported). Correct signatures:
    Rhino.Geometry.Point3d(x,y,z)   Vector3d(x,y,z)   Plane(origin_point, Vector3d.ZAxis)   Plane.WorldXY
    Rhino.Geometry.Interval(a, b)
    Rhino.Geometry.Box(plane, Interval(x0,x1), Interval(y0,y1), Interval(z0,z1))   # NOT Box(point, vector)
    Rhino.Geometry.Transform.Translation(Vector3d)   Transform.Rotation(radians, axis_vector, center_point)
    sc.doc.Objects.AddBrep(brep)  AddCurve(curve)  AddLine(p1,p2)  AddPoint(p)  AddMesh(mesh)  -> Guid
    box.ToBrep()   cylinder.ToBrep(True, True)
    obj = sc.doc.Objects.FindId(guid);  obj.Geometry
- Variables from earlier run_python calls in this chat still exist (e.g. `ids`). Reuse them for
  follow-up edits instead of recreating geometry. "Every second" object means ids[::2]; in a grid built
  with nested loops use a checkerboard: (i + j) % 2 == 0.
- Always print() a short summary of what you created (counts, not long id lists).
- If run_python returns an error, READ it and change the code. Never send the same code twice.
  After 2 failed tries with RhinoCommon, solve it with the ai helpers instead.
- A grid of N mm over a length L has L/N cells. If the user gives no object size, use the cell size
  and say which size you assumed.
- When the user attaches an image (photo, sketch, plan): first say in one or two sentences what you see
  (parts, proportions, materials). Estimate real dimensions in document units from known sizes and state
  your assumptions. Then model it part by part with the helpers. You cannot trace an image exactly.
- Answer briefly and concretely. Reply in the language the user writes in."""

TOOLS = [
    {"type": "function", "function": {
        "name": "get_scene_info",
        "description": "Summary of the Rhino document: units, layers, object counts by type, current selection with bounding boxes.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Run Python 3 code inside Rhino with RhinoCommon and rhinoscriptsyntax available. Returns printed output or the error traceback. The run is one undo step.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Complete Python 3 code to run."},
            "purpose": {"type": "string", "description": "One sentence: what the code does."}},
            "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "capture_viewport",
        "description": "Capture an image of the active viewport so you can see the model.",
        "parameters": {"type": "object", "properties": {}}}},
]


class AIHelpers(object):
    """Tested shortcuts exposed to the model as `ai` inside run_python."""

    # -- internals
    def _ids(self, ids):
        if ids is None:
            return []
        if isinstance(ids, (str, System.Guid)):
            ids = [ids]
        return [i if isinstance(i, System.Guid) else System.Guid(str(i)) for i in ids]

    def _pt(self, p):
        if isinstance(p, Rhino.Geometry.Point3d):
            return p
        p = list(p) + [0, 0, 0]
        return Rhino.Geometry.Point3d(float(p[0]), float(p[1]), float(p[2]))

    def _attr(self, layer):
        attr = sc.doc.CreateDefaultAttributes()
        if layer:
            self.layer(layer)
            attr.LayerIndex = sc.doc.Layers.FindByFullPath(layer, -1)
        return attr

    def _xform(self, ids, xf, copy):
        out = []
        for i in self._ids(ids):
            new_id = sc.doc.Objects.Transform(i, xf, not copy)
            out.append(new_id)
        return out

    # -- create
    def box(self, x, y, z, sx, sy, sz, layer=None):
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(x), float(y), float(z)), G.Vector3d.ZAxis)
        b = G.Box(plane, G.Interval(0, float(sx)), G.Interval(0, float(sy)), G.Interval(0, float(sz)))
        return sc.doc.Objects.AddBrep(b.ToBrep(), self._attr(layer))

    def sphere(self, x, y, z, radius, layer=None):
        G = Rhino.Geometry
        s = G.Sphere(G.Point3d(float(x), float(y), float(z)), float(radius))
        return sc.doc.Objects.AddBrep(s.ToBrep(), self._attr(layer))

    def cylinder(self, x, y, z, radius, height, layer=None):
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(x), float(y), float(z)), G.Vector3d.ZAxis)
        c = G.Cylinder(G.Circle(plane, float(radius)), float(height))
        return sc.doc.Objects.AddBrep(c.ToBrep(True, True), self._attr(layer))

    def line(self, a, b, layer=None):
        return sc.doc.Objects.AddLine(self._pt(a), self._pt(b), self._attr(layer))

    def polyline(self, points, closed=False, layer=None):
        pts = [self._pt(p) for p in points]
        if closed and pts and pts[0].DistanceTo(pts[-1]) > sc.doc.ModelAbsoluteTolerance:
            pts.append(pts[0])
        curve = Rhino.Geometry.Polyline(pts).ToNurbsCurve()
        return sc.doc.Objects.AddCurve(curve, self._attr(layer))

    def circle(self, x, y, z, radius, layer=None):
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(x), float(y), float(z)), G.Vector3d.ZAxis)
        return sc.doc.Objects.AddCurve(G.Circle(plane, float(radius)).ToNurbsCurve(), self._attr(layer))

    def extrude(self, curve_id, height, cap=True, layer=None):
        G = Rhino.Geometry
        if abs(float(height)) < 1e-9:
            raise ValueError("extrude height must not be 0. For a handle, spout or rod use "
                             "ai.tube([(x,y,z), ...], radius).")
        obj = sc.doc.Objects.FindId(self._ids(curve_id)[0])
        srf = G.Surface.CreateExtrusion(obj.Geometry, G.Vector3d(0, 0, float(height)))
        brep = srf.ToBrep()
        if cap:
            capped = brep.CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
            brep = capped or brep
        return sc.doc.Objects.AddBrep(brep, self._attr(layer))

    # -- transform
    def move(self, ids, dx, dy, dz):
        xf = Rhino.Geometry.Transform.Translation(float(dx), float(dy), float(dz))
        return self._xform(ids, xf, False)

    def copy(self, ids, dx, dy, dz):
        xf = Rhino.Geometry.Transform.Translation(float(dx), float(dy), float(dz))
        return self._xform(ids, xf, True)

    def _center(self, i):
        return sc.doc.Objects.FindId(i).Geometry.GetBoundingBox(True).Center

    def rotate(self, ids, angle_degrees, center=None):
        import math
        G = Rhino.Geometry
        out = []
        for i in self._ids(ids):
            c = self._pt(center) if center is not None else self._center(i)
            xf = G.Transform.Rotation(math.radians(float(angle_degrees)), G.Vector3d.ZAxis, c)
            out += self._xform([i], xf, False)
        return out

    def scale(self, ids, factor, center=None):
        out = []
        for i in self._ids(ids):
            c = self._pt(center) if center is not None else self._center(i)
            out += self._xform([i], Rhino.Geometry.Transform.Scale(c, float(factor)), False)
        return out

    def objects(self, layer=None, name=None):
        out = []
        for o in sc.doc.Objects:
            if layer and sc.doc.Layers[o.Attributes.LayerIndex].FullPath != layer:
                continue
            if name and (o.Attributes.Name or "") != name:
                continue
            out.append(o.Id)
        return out

    def center(self, obj_id):
        c = self._center(self._ids(obj_id)[0])
        return (c.X, c.Y, c.Z)

    # -- manage
    def delete(self, ids):
        return sum(1 for i in self._ids(ids) if sc.doc.Objects.Delete(i, True))

    def select(self, ids):
        sc.doc.Objects.UnselectAll()
        return sum(1 for i in self._ids(ids) if sc.doc.Objects.Select(i))

    def selected(self):
        return [o.Id for o in sc.doc.Objects.GetSelectedObjects(False, False)]

    def layer(self, name, color=None, transparency=None, shine=None):
        """Create a layer if missing. Use "Parent::Child" for nested layers. -> full layer path
        With transparency or shine it also gets a render material (same as ai.material)."""
        if transparency is not None or shine is not None:
            return self.material(name, color or (200, 200, 200), transparency or 0.0,
                                 0.3 if shine is None else shine)
        full = ""
        for part in [x.strip() for x in str(name).split("::") if x.strip()]:
            parent = full
            full = (full + "::" + part) if full else part
            if sc.doc.Layers.FindByFullPath(full, -1) >= 0:
                continue
            lay = Rhino.DocObjects.Layer()
            lay.Name = part
            if parent:
                lay.ParentLayerId = sc.doc.Layers[sc.doc.Layers.FindByFullPath(parent, -1)].Id
            sc.doc.Layers.Add(lay)
        if color:
            lay = sc.doc.Layers[sc.doc.Layers.FindByFullPath(full, -1)]
            lay.Color = System.Drawing.Color.FromArgb(*[int(v) for v in color[:3]])
        return full

    def material(self, layer, color, transparency=0.0, shine=0.3, name=None):
        """Give a layer a render material. color (r,g,b); transparency 0 = solid .. 1 = clear glass."""
        full = self.layer(layer, color)
        m = Rhino.DocObjects.Material()
        m.Name = name or full.split("::")[-1]
        m.DiffuseColor = System.Drawing.Color.FromArgb(*[int(v) for v in color[:3]])
        m.Transparency = max(0.0, min(1.0, float(transparency)))
        m.Shine = max(0.0, min(1.0, float(shine))) * Rhino.DocObjects.Material.MaxShine
        idx = sc.doc.Materials.Add(m)
        lay = sc.doc.Layers[sc.doc.Layers.FindByFullPath(full, -1)]
        lay.RenderMaterialIndex = idx
        return full

    def revolve(self, profile, cx=0, cy=0, smooth=False, cap=True, layer=None):
        """Lathe a profile around a vertical axis at (cx, cy). profile = [(radius, z), ...] from bottom to top.
        Use for bottles, vases, bowls, columns, knobs. smooth=True rounds the profile. -> id"""
        G = Rhino.Geometry
        pts = [G.Point3d(float(cx) + float(r), float(cy), float(z)) for r, z in profile]
        if len(pts) < 2:
            raise ValueError("profile needs at least 2 (radius, z) points.")
        if smooth and len(pts) > 2:
            crv = G.Curve.CreateInterpolatedCurve(pts, 3)
        else:
            crv = G.Polyline(pts).ToNurbsCurve()
        axis = G.Line(G.Point3d(float(cx), float(cy), 0), G.Point3d(float(cx), float(cy), 1))
        rev = G.RevSurface.Create(crv, axis)
        brep = G.Brep.CreateFromRevSurface(rev, bool(cap), bool(cap))
        if cap and not brep.IsSolid:
            brep = brep.CapPlanarHoles(sc.doc.ModelAbsoluteTolerance) or brep
        return sc.doc.Objects.AddBrep(brep, self._attr(layer))

    def set_layer(self, ids, name):
        self.layer(name)
        idx = sc.doc.Layers.FindByFullPath(name, -1)
        for i in self._ids(ids):
            obj = sc.doc.Objects.FindId(i)
            obj.Attributes.LayerIndex = idx
            obj.CommitChanges()

    def set_name(self, ids, name):
        for i in self._ids(ids):
            obj = sc.doc.Objects.FindId(i)
            obj.Attributes.Name = name
            obj.CommitChanges()

    def bbox(self, ids):
        bb = Rhino.Geometry.BoundingBox.Empty
        for i in self._ids(ids):
            bb.Union(sc.doc.Objects.FindId(i).Geometry.GetBoundingBox(True))
        return ((bb.Min.X, bb.Min.Y, bb.Min.Z), (bb.Max.X, bb.Max.Y, bb.Max.Z))

    # -- 2D drawing and curves
    def _add_curve(self, curve, layer=None):
        return sc.doc.Objects.AddCurve(curve, self._attr(layer))

    def _curve(self, curve_id):
        geo = sc.doc.Objects.FindId(self._ids(curve_id)[0]).Geometry
        if not isinstance(geo, Rhino.Geometry.Curve):
            raise ValueError("Object is not a curve.")
        return geo

    def _plane_of(self, curve):
        ok, plane = curve.TryGetPlane()
        return plane if ok else Rhino.Geometry.Plane.WorldXY

    def point(self, x, y, z=0, layer=None):
        return sc.doc.Objects.AddPoint(self._pt((x, y, z)), self._attr(layer))

    def rectangle(self, x, y, w, h, z=0, corner_radius=0, layer=None):
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(x), float(y), float(z)), G.Vector3d.ZAxis)
        curve = G.Rectangle3d(plane, G.Interval(0, float(w)), G.Interval(0, float(h))).ToNurbsCurve()
        if corner_radius:
            tol = sc.doc.ModelAbsoluteTolerance
            curve = G.Curve.CreateFilletCornersCurve(curve, float(corner_radius), tol, 0.01) or curve
        return self._add_curve(curve, layer)

    def polygon(self, cx, cy, radius, sides, z=0, rotation_degrees=0, layer=None):
        import math
        pts = []
        for k in range(int(sides)):
            a = math.radians(float(rotation_degrees)) + 2 * math.pi * k / int(sides)
            pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z))
        return self.polyline(pts, closed=True, layer=layer)

    def arc(self, cx, cy, radius, start_degrees, end_degrees, z=0, layer=None):
        import math
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(cx), float(cy), float(z)), G.Vector3d.ZAxis)
        a = G.Arc(G.Circle(plane, float(radius)),
                  G.Interval(math.radians(float(start_degrees)), math.radians(float(end_degrees))))
        return self._add_curve(G.ArcCurve(a), layer)

    def ellipse(self, cx, cy, rx, ry, z=0, layer=None):
        G = Rhino.Geometry
        plane = G.Plane(G.Point3d(float(cx), float(cy), float(z)), G.Vector3d.ZAxis)
        return self._add_curve(G.Ellipse(plane, float(rx), float(ry)).ToNurbsCurve(), layer)

    def curve(self, points, through_points=True, closed=False, degree=3, layer=None):
        G = Rhino.Geometry
        pts = [self._pt(p) for p in points]
        if closed and pts[0].DistanceTo(pts[-1]) > sc.doc.ModelAbsoluteTolerance:
            pts.append(pts[0])
        deg = max(1, min(int(degree), len(pts) - 1))
        if through_points:
            knot = G.CurveKnotStyle.ChordPeriodic if closed else G.CurveKnotStyle.Chord
            c = G.Curve.CreateInterpolatedCurve(pts, deg, knot)
        else:
            c = G.Curve.CreateControlPointCurve(pts, deg)
        return self._add_curve(c, layer)

    def offset(self, curve_id, distance, layer=None):
        """Closed curve: positive = outward, negative = inward. Open curve: positive = left side."""
        G = Rhino.Geometry
        c = self._curve(curve_id)
        plane = self._plane_of(c)
        tol = sc.doc.ModelAbsoluteTolerance
        style = G.CurveOffsetCornerStyle.Sharp
        d = float(distance)
        a = c.Offset(plane, d, tol, style)
        if c.IsClosed:
            b = c.Offset(plane, -d, tol, style)
            la = sum(x.GetLength() for x in a) if a else 0
            lb = sum(x.GetLength() for x in b) if b else 0
            outward, inward = (a, b) if la >= lb else (b, a)
            a = outward if d > 0 else inward
        if not a:
            raise ValueError("Offset failed (distance too large?).")
        return [self._add_curve(x, layer) for x in a]

    def fillet(self, curve_id, radius):
        """Round all corners of a polyline/curve in place."""
        G = Rhino.Geometry
        i = self._ids(curve_id)[0]
        c = G.Curve.CreateFilletCornersCurve(self._curve(i), float(radius), sc.doc.ModelAbsoluteTolerance, 0.01)
        if c is None:
            raise ValueError("Fillet failed (radius too large?).")
        sc.doc.Objects.Replace(i, c)
        return i

    def join(self, curve_ids):
        ids = self._ids(curve_ids)
        res = Rhino.Geometry.Curve.JoinCurves([self._curve(i) for i in ids], sc.doc.ModelAbsoluteTolerance)
        self.delete(ids)
        return [self._add_curve(c) for c in res]

    def divide(self, curve_id, count, add_points=False):
        """count evenly spaced positions along a curve -> [(x,y,z), ...]"""
        c = self._curve(curve_id)
        n = int(count)
        if n < 2 and not c.IsClosed:
            ts = [c.Domain.Mid]
        else:
            ts = list(c.DivideByCount(n if c.IsClosed else n - 1, True))
        pts = [c.PointAt(t) for t in ts]
        if add_points:
            for q in pts:
                sc.doc.Objects.AddPoint(q)
        return [(q.X, q.Y, q.Z) for q in pts]

    def length(self, curve_id):
        return self._curve(curve_id).GetLength()

    def area(self, obj_id):
        geo = sc.doc.Objects.FindId(self._ids(obj_id)[0]).Geometry
        mp = Rhino.Geometry.AreaMassProperties.Compute(geo)
        if mp is None:
            raise ValueError("Area needs a closed planar curve, surface or solid.")
        return mp.Area

    def is_closed(self, curve_id):
        return bool(self._curve(curve_id).IsClosed)

    def _region(self, fn, *groups):
        res = fn(*groups, sc.doc.ModelAbsoluteTolerance)
        if not res:
            raise ValueError("Curve boolean failed (curves must be closed, planar and overlapping).")
        return [self._add_curve(c) for c in res]

    def curve_union(self, curve_ids):
        return self._region(Rhino.Geometry.Curve.CreateBooleanUnion, [self._curve(i) for i in self._ids(curve_ids)])

    def curve_difference(self, curve_id_a, curve_ids_b):
        return self._region(Rhino.Geometry.Curve.CreateBooleanDifference, self._curve(curve_id_a),
                            [self._curve(i) for i in self._ids(curve_ids_b)])

    def curve_intersection(self, curve_id_a, curve_id_b):
        return self._region(Rhino.Geometry.Curve.CreateBooleanIntersection,
                            self._curve(curve_id_a), self._curve(curve_id_b))

    def planar_surface(self, curve_ids, layer=None):
        res = Rhino.Geometry.Brep.CreatePlanarBreps([self._curve(i) for i in self._ids(curve_ids)],
                                                    sc.doc.ModelAbsoluteTolerance)
        if not res:
            raise ValueError("Planar surface needs closed planar curves.")
        return [sc.doc.Objects.AddBrep(b, self._attr(layer)) for b in res]

    def loft(self, curve_ids, layer=None):
        G = Rhino.Geometry
        res = G.Brep.CreateFromLoft([self._curve(i) for i in self._ids(curve_ids)],
                                    G.Point3d.Unset, G.Point3d.Unset, G.LoftType.Normal, False)
        if not res:
            raise ValueError("Loft failed.")
        return [sc.doc.Objects.AddBrep(b, self._attr(layer)) for b in res]

    def tube(self, points, radius, smooth=True, layer=None):
        """Solid round tube through 3D points. Use for handles, spouts, legs, rails, cables. -> id"""
        G = Rhino.Geometry
        pts = [self._pt(q) for q in points]
        if len(pts) < 2:
            raise ValueError("tube needs at least 2 points.")
        if smooth and len(pts) > 2:
            crv = G.Curve.CreateInterpolatedCurve(pts, 3)
        else:
            crv = G.Polyline(pts).ToNurbsCurve()
        res = G.Brep.CreatePipe(crv, float(radius), False, G.PipeCapMode.Flat, True,
                                sc.doc.ModelAbsoluteTolerance, sc.doc.ModelAngleToleranceRadians)
        if not res:
            raise ValueError("Tube failed (radius too large for the bends?).")
        return sc.doc.Objects.AddBrep(res[0], self._attr(layer))

    def pipe(self, curve_id, radius, layer=None):
        G = Rhino.Geometry
        res = G.Brep.CreatePipe(self._curve(curve_id), float(radius), False, G.PipeCapMode.Flat, True,
                                sc.doc.ModelAbsoluteTolerance, sc.doc.ModelAngleToleranceRadians)
        if not res:
            raise ValueError("Pipe failed.")
        return [sc.doc.Objects.AddBrep(b, self._attr(layer)) for b in res]

    # -- spatial arrangement
    def _bb(self, i):
        return sc.doc.Objects.FindId(i).Geometry.GetBoundingBox(True)

    def _axis(self, axis):
        return {"x": 0, "y": 1, "z": 2}[str(axis).lower()]

    def describe(self, ids=None, limit=40):
        """Position and size of objects -> list of dicts (center, size, min, max, type, layer, name)."""
        ids = self._ids(ids) if ids is not None else [o.Id for o in sc.doc.Objects]
        out = []
        for i in ids[:int(limit)]:
            o = sc.doc.Objects.FindId(i)
            bb = o.Geometry.GetBoundingBox(True)
            r = lambda p: [round(p.X, 2), round(p.Y, 2), round(p.Z, 2)]
            out.append({"id": str(i), "type": str(o.ObjectType), "name": o.Attributes.Name or "",
                        "layer": sc.doc.Layers[o.Attributes.LayerIndex].FullPath,
                        "center": r(bb.Center), "size": r(bb.Max - bb.Min), "min": r(bb.Min), "max": r(bb.Max)})
        return out

    def move_to(self, obj_id, x, y, z, anchor="center"):
        """Move so that the anchor ('center', 'bottom' = bottom centre, 'corner' = min corner) lands on x,y,z."""
        G = Rhino.Geometry
        i = self._ids(obj_id)[0]
        bb = self._bb(i)
        a = {"center": bb.Center, "bottom": G.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z), "corner": bb.Min}[anchor]
        return self._xform([i], G.Transform.Translation(self._pt((x, y, z)) - a), False)[0]

    def array_grid(self, ids, nx, ny, dx, dy, nz=1, dz=0):
        """Copies on a grid with spacing dx, dy, dz. Returns ALL ids including the originals."""
        ids = self._ids(ids)
        out = list(ids)
        for a in range(int(nx)):
            for b in range(int(ny)):
                for c in range(int(nz)):
                    if a == b == c == 0:
                        continue
                    out += self.copy(ids, a * dx, b * dy, c * dz)
        return out

    def array_polar(self, ids, count, center=(0, 0, 0), total_degrees=360):
        """count items around a vertical axis through center. Returns ALL ids including the originals."""
        import math
        G = Rhino.Geometry
        ids = self._ids(ids)
        out = list(ids)
        n = int(count)
        step = float(total_degrees) / (n if abs(total_degrees) >= 360 else max(n - 1, 1))
        for k in range(1, n):
            xf = G.Transform.Rotation(math.radians(step * k), G.Vector3d.ZAxis, self._pt(center))
            out += self._xform(ids, xf, True)
        return out

    def array_along_curve(self, obj_id, curve_id, count, rotate=True):
        """count copies of an object, evenly spaced on a curve, optionally turned to follow it. -> new ids"""
        G = Rhino.Geometry
        i = self._ids(obj_id)[0]
        c = self._curve(curve_id)
        n = int(count)
        ts = [c.Domain.Mid] if (n < 2 and not c.IsClosed) else list(c.DivideByCount(n if c.IsClosed else n - 1, True))
        bb = self._bb(i)
        base = G.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z)
        out = []
        for t in ts:
            q = c.PointAt(t)
            xf = G.Transform.Translation(q - base)
            if rotate:
                tan = c.TangentAt(t)
                flat = G.Vector3d(tan.X, tan.Y, 0)
                if flat.Length > 1e-9:
                    xf = G.Transform.Rotation(G.Vector3d.XAxis, flat, q) * xf
            out += self._xform([i], xf, True)
        return out

    def align(self, ids, axis="x", mode="min", to=None):
        """Line objects up on one axis. mode: 'min', 'center' or 'max'. to: coordinate (default: first object)."""
        G = Rhino.Geometry
        ids = self._ids(ids)
        k = self._axis(axis)
        val = lambda bb: {"min": bb.Min[k], "center": bb.Center[k], "max": bb.Max[k]}[mode]
        target = float(to) if to is not None else val(self._bb(ids[0]))
        for i in ids:
            v = [0.0, 0.0, 0.0]
            v[k] = target - val(self._bb(i))
            self._xform([i], G.Transform.Translation(v[0], v[1], v[2]), False)
        return ids

    def distribute(self, ids, axis="x", gap=None):
        """Spread objects along an axis. gap=None: equal centre spacing between first and last.
        gap=number: that clear distance between neighbours, starting at the first object."""
        G = Rhino.Geometry
        k = self._axis(axis)
        ids = sorted(self._ids(ids), key=lambda i: self._bb(i).Center[k])
        if len(ids) < 2:
            return ids
        if gap is None:
            a, b = self._bb(ids[0]).Center[k], self._bb(ids[-1]).Center[k]
            targets = [a + (b - a) * n / (len(ids) - 1) for n in range(len(ids))]
            deltas = [t - self._bb(i).Center[k] for i, t in zip(ids, targets)]
        else:
            deltas, cursor = [], self._bb(ids[0]).Min[k]
            for i in ids:
                bb = self._bb(i)
                deltas.append(cursor - bb.Min[k])
                cursor += (bb.Max[k] - bb.Min[k]) + float(gap)
        for i, d in zip(ids, deltas):
            v = [0.0, 0.0, 0.0]
            v[k] = d
            self._xform([i], G.Transform.Translation(v[0], v[1], v[2]), False)
        return ids

    def mirror(self, ids, axis="x", at=0, copy=True):
        """Mirror across the plane axis = at (axis 'x' mirrors left/right). -> ids"""
        G = Rhino.Geometry
        k = self._axis(axis)
        p = [0.0, 0.0, 0.0]
        n = [0.0, 0.0, 0.0]
        p[k], n[k] = float(at), 1.0
        xf = G.Transform.Mirror(G.Point3d(p[0], p[1], p[2]), G.Vector3d(n[0], n[1], n[2]))
        return self._xform(ids, xf, copy)

    def place_on_surface(self, obj_id, surface_id, u=0.5, v=0.5, copy=False):
        """Put the object's bottom centre on a surface at u,v (each 0..1) and stand it along the normal."""
        G = Rhino.Geometry
        i = self._ids(obj_id)[0]
        brep = G.Brep.TryConvertBrep(sc.doc.Objects.FindId(self._ids(surface_id)[0]).Geometry)
        if brep is None:
            raise ValueError("Target is not a surface.")
        face = brep.Faces[0]
        uu = face.Domain(0).ParameterAt(float(u))
        vv = face.Domain(1).ParameterAt(float(v))
        ok, frame = face.FrameAt(uu, vv)
        if face.OrientationIsReversed:
            frame = G.Plane(frame.Origin, frame.YAxis, frame.XAxis)
        bb = self._bb(i)
        src = G.Plane(G.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z), G.Vector3d.ZAxis)
        return self._xform([i], G.Transform.PlaneToPlane(src, frame), copy)[0]

    def distance(self, id_a, id_b):
        return self._bb(self._ids(id_a)[0]).Center.DistanceTo(self._bb(self._ids(id_b)[0]).Center)

    def _breps(self, ids):
        return [Rhino.Geometry.Brep.TryConvertBrep(sc.doc.Objects.FindId(i).Geometry) for i in self._ids(ids)]

    def boolean_union(self, ids):
        res = Rhino.Geometry.Brep.CreateBooleanUnion(self._breps(ids), sc.doc.ModelAbsoluteTolerance)
        if not res:
            raise ValueError("Boolean union failed (objects may not overlap or are open).")
        self.delete(ids)
        return [sc.doc.Objects.AddBrep(b) for b in res]

    def boolean_difference(self, ids_a, ids_b):
        res = Rhino.Geometry.Brep.CreateBooleanDifference(
            self._breps(ids_a), self._breps(ids_b), sc.doc.ModelAbsoluteTolerance)
        if not res:
            raise ValueError("Boolean difference failed (objects may not intersect or are open).")
        self.delete(ids_a)
        self.delete(ids_b)
        return [sc.doc.Objects.AddBrep(b) for b in res]


def tool_get_scene_info():
    doc = sc.doc
    info = {
        "units": str(doc.ModelUnitSystem),
        "tolerance": doc.ModelAbsoluteTolerance,
        "layers": [l.FullPath for l in doc.Layers if not l.IsDeleted][:200],
        "object_counts": {},
        "selection": [],
    }
    for obj in doc.Objects:
        t = str(obj.ObjectType)
        info["object_counts"][t] = info["object_counts"].get(t, 0) + 1
    for obj in list(doc.Objects.GetSelectedObjects(False, False))[:50]:
        bb = obj.Geometry.GetBoundingBox(True)
        info["selection"].append({
            "id": str(obj.Id),
            "type": str(obj.ObjectType),
            "name": obj.Attributes.Name or "",
            "layer": doc.Layers[obj.Attributes.LayerIndex].FullPath,
            "bbox_min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "bbox_max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)],
        })
    if doc.Objects.Count <= 30:
        info["objects"] = AIHelpers().describe()
    else:
        info["note"] = "Many objects. Use ai.describe(ids) or ai.objects(layer=...) in run_python for details."
    return json.dumps(info)


# Variables survive between run_python calls of one chat (cleared by "New chat")
RUN_ENV = {}

# Code that reaches files, the network or other programs is always shown for confirmation,
# even with CONFIRM_CODE=0. A guard for honest mistakes, not a sandbox: see SECURITY.md.
RISKY_PATTERNS = (
    ("import os", "file system"), ("from os", "file system"),
    ("pathlib", "file system"), ("shutil", "file system"), ("open(", "file access"),
    ("System.IO", "file system"), ("subprocess", "runs other programs"),
    ("System.Diagnostics", "runs other programs"), ("ctypes", "native code"),
    ("socket", "network"), ("urllib", "network"), ("requests", "network"), ("http", "network"),
    ("System.Net", "network"), ("eval(", "dynamic code"), ("exec(", "dynamic code"),
    ("compile(", "dynamic code"), ("__import__", "dynamic import"), ("importlib", "dynamic import"),
    ("rs.Command", "runs Rhino commands"), ("RunScript", "runs Rhino commands"),
    ("WriteFile", "writes files"), ("Export", "writes files"),
)


def risky_reasons(code):
    found = []
    for pattern, reason in RISKY_PATTERNS:
        if pattern in code and reason not in found:
            found.append(reason)
    return found


def _forgiving(name, fn):
    """Drop unknown keyword arguments instead of failing, and tell the model about it."""
    import inspect
    import functools
    params = inspect.signature(fn).parameters

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        bad = [k for k in kwargs if k not in params]
        for k in bad:
            kwargs.pop(k)
        if bad:
            print("NOTE: ai.%s ignored unknown argument(s) %s. Valid: %s"
                  % (name, ", ".join(bad), ", ".join(q for q in params if q != "self")))
        return fn(self, *args, **kwargs)
    return wrapper


def _missing_helper(self, name):
    import difflib
    names = [n for n in dir(type(self)) if not n.startswith("_")]
    near = difflib.get_close_matches(name, names, n=4, cutoff=0.4)
    raise AttributeError("ai.%s does not exist. %s" % (
        name, ("Did you mean: " + ", ".join("ai." + n for n in near)) if near
        else "Available: " + ", ".join(names)))


for _n, _f in list(vars(AIHelpers).items()):
    if not _n.startswith("_") and callable(_f):
        setattr(AIHelpers, _n, _forgiving(_n, _f))
AIHelpers.__getattr__ = _missing_helper
AI_HELPERS = AIHelpers()


def tool_run_python(code):
    out = io.StringIO()
    undo = sc.doc.BeginUndoRecord("RhinoAI")
    try:
        env = RUN_ENV
        sys.modules["ai"] = AI_HELPERS  # so a stray "import ai" in model code works
        env.update({"__name__": "__rhino_ai__", "Rhino": Rhino, "sc": sc, "rs": rs, "System": System,
                    "ai": AI_HELPERS})
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<rhino_ai>", "exec"), env)
        result = out.getvalue().strip() or "OK (no output)"
        kept = []
        for k, v in env.items():
            if k.startswith("_") or k in ("Rhino", "sc", "rs", "System", "ai"):
                continue
            if isinstance(v, System.Guid):
                kept.append("%s (1 object id)" % k)
            elif isinstance(v, (list, tuple)) and v and all(isinstance(x, System.Guid) for x in v):
                kept.append("%s (list of %d object ids)" % (k, len(v)))
        if kept:
            result += ("\nVariables kept for follow-up edits: " + ", ".join(kept[:12])
                       + ". To change these objects later, reuse the variables. Do NOT create them again.")
    except Exception:
        lines = traceback.format_exc().strip().splitlines()
        tail = [l for l in lines if "<rhino_ai>" in l][-1:] + lines[-1:]
        if "ModuleNotFoundError" in lines[-1] or "ImportError" in lines[-1]:
            tail.append("Remove that import. ai, Rhino, sc (scriptcontext), rs and System are ALREADY available; "
                        "import nothing except standard modules like math.")
        result = (out.getvalue() + "\nERROR:\n" + "\n".join(tail)
                  + "\nHint: prefer the ai.* helpers (ai.box, ai.cylinder, ...) and never resend unchanged code.").strip()
    finally:
        sc.doc.EndUndoRecord(undo)
        sc.doc.Views.Redraw()
    return result[:4000]


def tool_capture_viewport():
    view = sc.doc.Views.ActiveView
    bmp = view.CaptureToBitmap(System.Drawing.Size(768, 512))
    path = os.path.join(tempfile.gettempdir(), "rhino_ai_view.png")
    bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# ---------------------------------------------------------------- agent

class Agent(object):
    def __init__(self, conf, ui):
        self.conf = conf
        self.ui = ui
        self.vision = bool(conf.get("MMPROJ"))
        self.reset()

    def reset(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.failed_code = set()
        RUN_ENV.clear()

    def on_ui(self, fn):
        """Run fn on Rhino's UI thread and return its result."""
        box = {}

        def run():
            try:
                box["value"] = fn()
            except Exception:
                box["value"] = "ERROR:\n" + traceback.format_exc(limit=3)
        forms.Application.Instance.Invoke(System.Action(run))
        return box.get("value")

    def execute(self, name, args):
        if name == "get_scene_info":
            return self.on_ui(tool_get_scene_info), None
        if name == "run_python":
            code = args.get("code", "")
            if code.strip() in self.failed_code:
                return ("This exact code already failed. Do not resend it. "
                        "Rewrite it using the ai.* helpers, e.g. ai.box(x, y, z, sx, sy, sz)."), None
            self.ui.log("code", code)
            risky = risky_reasons(code)
            if self.conf.get("CONFIRM_CODE", "1") == "1" or risky:
                purpose = args.get("purpose", "Run this code?")
                if risky:
                    purpose = ("WARNING: this code goes beyond modelling (" + ", ".join(risky) + ").\n"
                               "Only run it if you understand it.\n\n" + purpose)
                ok = self.on_ui(lambda: self.ui.confirm(purpose))
                if not ok:
                    return "The user declined to run this code. Ask what to change.", None
            result = self.on_ui(lambda: tool_run_python(code))
            if "ERROR:" in (result or ""):
                self.failed_code.add(code.strip())
            return result, None
        if name == "capture_viewport":
            if not self.vision:
                return "Vision is disabled (no MMPROJ in kit.conf).", None
            png = self.on_ui(tool_capture_viewport)
            if png.startswith("ERROR"):
                return png, None
            return "Viewport image attached in the next message.", png
        return "Unknown tool: %s" % name, None

    def ask(self, text, max_steps=8, images=None):
        if images:
            content = [{"type": "text", "text": text}]
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})
            self.messages.append({"role": "user", "content": content})
        else:
            self.messages.append({"role": "user", "content": text})
        for _ in range(max_steps):
            msg = chat(self.conf, self.messages, TOOLS)
            calls = msg.get("tool_calls") or []
            self.messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                **({"tool_calls": calls} if calls else {}),
            })
            if not calls:
                return msg.get("content") or ""
            if msg.get("content"):
                self.ui.log("ai", msg["content"])
            images = []
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                self.ui.log("tool", name)
                result, png = self.execute(name, args)
                self.messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
                if name == "run_python":
                    self.ui.log("result", result)
                if png:
                    images.append(png)
            for png in images:
                self.messages.append({"role": "user", "content": [
                    {"type": "text", "text": "Current viewport:"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}},
                ]})
        return "(Stopped after %d steps.)" % max_steps


# ---------------------------------------------------------------- UI

def image_data_url(path, max_side=1024):
    """Read an image file as a data URL, scaled down so it does not fill the context window."""
    try:
        bmp = drawing.Bitmap(path)
        w, h = bmp.Width, bmp.Height
        if max(w, h) > max_side:
            f = float(max_side) / max(w, h)
            bmp = drawing.Bitmap(bmp, int(w * f), int(h * f), drawing.ImageInterpolation.High)
        tmp = os.path.join(tempfile.gettempdir(), "rhino_ai_input.png")
        bmp.Save(tmp, drawing.ImageFormat.Png)
        with open(tmp, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        ext = os.path.splitext(path)[1].lower().strip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif", "bmp": "bmp"}.get(ext, "png")
        with open(path, "rb") as f:
            return "data:image/%s;base64,%s" % (mime, base64.b64encode(f.read()).decode("ascii"))


class ChatForm(forms.Form):
    def __init__(self, kit, conf):
        super().__init__()
        self.kit = kit
        self.conf = conf
        self.agent = Agent(conf, self)
        self.busy = False

        self.Title = "Rhino Open AI Kit - " + conf.get("MODEL", "")
        self.ClientSize = drawing.Size(460, 620)
        self.Resizable = True
        self.Topmost = False

        self.history = forms.TextArea()
        self.history.ReadOnly = True
        self.history.Wrap = True
        self.history.Font = drawing.Font("Menlo" if sys.platform == "darwin" else "Consolas", 11)

        self.prompt = forms.TextArea()
        self.prompt.Height = 80
        self.prompt.Wrap = True

        self.send_btn = forms.Button()
        self.send_btn.Text = "Send"
        self.send_btn.Click += self.on_send
        self.images = []
        self.image_btn = forms.Button()
        self.image_btn.Text = "Image"
        self.image_btn.ToolTip = "Attach an image (photo, sketch, plan, reference) to your next message"
        self.image_btn.Click += self.on_image
        clear_btn = forms.Button()
        clear_btn.Text = "New chat"
        clear_btn.Click += self.on_clear
        self.status = forms.Label()
        self.status.Text = "Checking model server ..."

        buttons = forms.StackLayout()
        buttons.Orientation = forms.Orientation.Horizontal
        buttons.Spacing = 6
        buttons.Items.Add(forms.StackLayoutItem(self.send_btn))
        buttons.Items.Add(forms.StackLayoutItem(self.image_btn))
        buttons.Items.Add(forms.StackLayoutItem(clear_btn))
        buttons.Items.Add(forms.StackLayoutItem(self.status))

        layout = forms.DynamicLayout()
        layout.Padding = drawing.Padding(8)
        layout.Spacing = drawing.Size(6, 6)
        layout.Add(self.history, yscale=True)
        layout.Add(self.prompt)
        layout.Add(buttons)
        self.Content = layout

        if conf.get("CONFIRM_CODE", "1") != "1":
            self.log("error", "CONFIRM_CODE=0: generated code runs without asking. "
                              "Code that touches files, network or other programs is still confirmed.")
        threading.Thread(target=self.ensure_server, daemon=True).start()

    # -- helpers callable from any thread
    def ui(self, fn):
        forms.Application.Instance.AsyncInvoke(System.Action(fn))

    def set_status(self, text):
        self.ui(lambda: setattr(self.status, "Text", text))

    def log(self, kind, text):
        prefix = {"you": "YOU", "ai": "AI", "tool": "  > tool", "code": "  > code",
                  "result": "  > result", "error": "ERROR"}.get(kind, kind)
        if kind == "code":
            text = "\n" + "\n".join("    " + l for l in text.splitlines())
        line = "%s: %s\n\n" % (prefix, text)
        self.ui(lambda: self.history.Append(line, True))

    def confirm(self, purpose):
        r = forms.MessageBox.Show(self, purpose + "\n\nRun the generated code (see chat)?",
                                  "Rhino Open AI Kit", forms.MessageBoxButtons.YesNo)
        return r == forms.DialogResult.Yes

    # -- server
    def ensure_server(self):
        if server_alive(self.conf):
            self.set_status("Ready")
            return
        self.set_status("Starting model server ...")
        start_server(self.kit)
        ok = wait_for_server(self.conf, on_tick=lambda s: self.set_status("Loading model ... %ds" % s))
        self.set_status("Ready" if ok else "Server not reachable - check the terminal window")

    # -- events
    def on_clear(self, sender, e):
        self.agent.reset()
        self.history.Text = ""

    def on_image(self, sender, e):
        if not self.agent.vision:
            forms.MessageBox.Show(self, "Image input needs the vision file.\n\nPut mmproj-F16.gguf into models/, "
                                  "set MMPROJ=mmproj-F16.gguf in kit.conf, then restart the model server "
                                  "and this window.", "RhinoAI")
            return
        dlg = forms.OpenFileDialog()
        dlg.Title = "Attach image"
        dlg.MultiSelect = True
        dlg.Filters.Add(forms.FileFilter("Images", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
        if dlg.ShowDialog(self) != forms.DialogResult.Ok:
            return
        for path in list(dlg.Filenames)[:3]:
            try:
                self.images.append((os.path.basename(path), image_data_url(path)))
            except Exception as ex:
                self.log("error", "Could not read image %s (%s)" % (path, ex))
        self.image_btn.Text = "Image (%d)" % len(self.images) if self.images else "Image"

    def on_send(self, sender, e):
        text = (self.prompt.Text or "").strip()
        if self.images and not text:
            text = "Describe this image and what in it could be modelled in Rhino."
        if not text or self.busy:
            return
        images = self.images
        self.images = []
        self.image_btn.Text = "Image"
        self.prompt.Text = ""
        self.busy = True
        self.send_btn.Enabled = False
        self.log("you", text + ("".join("  [image: %s]" % n for n, _ in images)))
        self.set_status("Thinking ...")
        threading.Thread(target=self.run_agent, args=(text, [u for _, u in images]), daemon=True).start()

    def run_agent(self, text, images=None):
        try:
            answer = self.agent.ask(text, images=images)
            self.log("ai", answer)
        except urllib.error.URLError as ex:
            self.log("error", "Model server not reachable (%s). Is the terminal window running?" % ex)
        except Exception:
            self.log("error", traceback.format_exc(limit=3))
        finally:
            self.busy = False
            self.ui(lambda: setattr(self.send_btn, "Enabled", True))
            self.set_status("Ready")


def main():
    kit = find_kit_dir()
    if not kit:
        return
    sc.sticky["rhino_ai_kit_dir"] = kit
    conf = load_conf(kit)
    form = sc.sticky.get("rhino_ai_form")
    if form is not None:
        try:
            form.Show()
            form.BringToFront()
            return
        except Exception:
            pass
    form = ChatForm(kit, conf)
    form.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    form.Closed += lambda s, e: sc.sticky.pop("rhino_ai_form", None)
    sc.sticky["rhino_ai_form"] = form
    form.Show()


if __name__ == "__main__":
    main()
