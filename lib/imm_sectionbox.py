# -*- coding: utf-8 -*-
"""Shared section box logic and settings for the IMM Section Box tools."""
import json

from Autodesk.Revit.DB import (
    BoundingBoxXYZ, Curve, FamilyInstance, FilteredElementCollector,
    GeometryInstance, Grid, LabelUtils, LocationCurve, LocationPoint, Mesh,
    Options, Point, Solid, Transform, UnitUtils, View3D, ViewDetailLevel,
    ViewFamily, ViewFamilyType, XYZ
)

from pyrevit import script

CONFIG_SECTION = 'IMMSectionBox'

MODE_PARALLEL = 'parallel'
MODE_NATIVE = 'native'

# Internal units are feet
DEFAULT_CREATION_OFFSET = 300.0 / 304.8
DEFAULT_RESIZE_STEP = 500.0 / 304.8
DEFAULT_MODE = MODE_PARALLEL

# Smallest box edge Shrink will leave behind (about 30 mm)
MIN_BOX_SIZE = 0.1

MAX_SAVED_BOXES = 50


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def _config():
    return script.get_config(CONFIG_SECTION)


def _get_float(cfg, name, default):
    try:
        return float(cfg.get_option(name, default))
    except Exception:
        return default


def load_settings():
    cfg = _config()
    mode = cfg.get_option('mode', DEFAULT_MODE)
    if mode not in (MODE_PARALLEL, MODE_NATIVE):
        mode = DEFAULT_MODE
    return {
        'creation_offset': _get_float(cfg, 'creation_offset', DEFAULT_CREATION_OFFSET),
        'resize_step': _get_float(cfg, 'resize_step', DEFAULT_RESIZE_STEP),
        'mode': mode,
    }


def save_settings(creation_offset, resize_step, mode):
    cfg = _config()
    cfg.creation_offset = float(creation_offset)
    cfg.resize_step = float(resize_step)
    cfg.mode = mode
    script.save_config()


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
def length_unit(doc):
    """Project length unit (ForgeTypeId on 2021+, DisplayUnitType before)."""
    units = doc.GetUnits()
    try:
        from Autodesk.Revit.DB import SpecTypeId
        return units.GetFormatOptions(SpecTypeId.Length).GetUnitTypeId()
    except Exception:
        from Autodesk.Revit.DB import UnitType
        return units.GetFormatOptions(UnitType.UT_Length).DisplayUnits


def length_unit_label(doc):
    unit = length_unit(doc)
    try:
        return LabelUtils.GetLabelForUnit(unit)
    except Exception:
        try:
            return LabelUtils.GetLabelFor(unit)
        except Exception:
            return 'project units'


def to_display(doc, value):
    return UnitUtils.ConvertFromInternalUnits(value, length_unit(doc))


def from_display(doc, value):
    return UnitUtils.ConvertToInternalUnits(value, length_unit(doc))


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
def _usable_3d(view):
    return isinstance(view, View3D) and not view.IsTemplate


def find_or_create_default_3d(doc):
    """Return the user's default 3D view, creating it when missing.
    Must be called inside a transaction if creation might be needed."""
    views = [v for v in FilteredElementCollector(doc).OfClass(View3D)
             if _usable_3d(v) and not v.IsPerspective]
    names = ['{3D}']
    if doc.IsWorkshared:
        names.insert(0, '{3D - %s}' % doc.Application.Username)
    for name in names:
        for v in views:
            if v.Name == name:
                return v

    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if t.ViewFamily == ViewFamily.ThreeDimensional:
            vft = t
            break
    if vft is None:
        return None
    view = View3D.CreateIsometric(doc, vft.Id)
    try:
        view.Name = names[0]
    except Exception:
        pass
    return view


def active_3d_view(uidoc):
    view = uidoc.ActiveView
    if _usable_3d(view):
        return view
    return None


# --------------------------------------------------------------------------
# Remembering boxes so Toggle can restore them
# --------------------------------------------------------------------------
def _box_to_list(box):
    t = box.Transform
    vals = []
    for p in (t.Origin, t.BasisX, t.BasisY, t.BasisZ, box.Min, box.Max):
        vals.extend([p.X, p.Y, p.Z])
    return vals


def _box_from_list(vals):
    pts = [XYZ(vals[i], vals[i + 1], vals[i + 2]) for i in range(0, 18, 3)]
    t = Transform.Identity
    t.Origin, t.BasisX, t.BasisY, t.BasisZ = pts[0], pts[1], pts[2], pts[3]
    box = BoundingBoxXYZ()
    box.Transform = t
    box.Min, box.Max = pts[4], pts[5]
    return box


def _saved_boxes(cfg):
    raw = cfg.get_option('saved_boxes', '{}')
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def remember_box(view):
    cfg = _config()
    boxes = _saved_boxes(cfg)
    boxes.pop(view.UniqueId, None)
    boxes[view.UniqueId] = _box_to_list(view.GetSectionBox())
    # Keep the store small; dict order is not guaranteed so trim arbitrarily
    while len(boxes) > MAX_SAVED_BOXES:
        boxes.pop(next(iter(boxes)))
    cfg.saved_boxes = json.dumps(boxes)
    script.save_config()


def recall_box(view):
    vals = _saved_boxes(_config()).get(view.UniqueId)
    if not vals or len(vals) != 18:
        return None
    try:
        return _box_from_list(vals)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def _horizontal(vec):
    v = XYZ(vec.X, vec.Y, 0)
    if v.GetLength() < 1e-6:
        return None
    return v.Normalize()


def element_direction(elem):
    """Horizontal direction that best describes how an element is laid out."""
    if isinstance(elem, Grid):
        c = elem.Curve
        return _horizontal(c.GetEndPoint(1) - c.GetEndPoint(0))

    loc = elem.Location
    if isinstance(loc, LocationCurve):
        c = loc.Curve
        d = _horizontal(c.GetEndPoint(1) - c.GetEndPoint(0))
        if d is not None:
            return d

    if isinstance(elem, FamilyInstance):
        for vec in (elem.HandOrientation, elem.FacingOrientation):
            try:
                d = _horizontal(vec)
            except Exception:
                d = None
            if d is not None:
                return d

    if isinstance(loc, LocationPoint):
        try:
            import math
            a = loc.Rotation
            return XYZ(math.cos(a), math.sin(a), 0)
        except Exception:
            pass
    return None


def selection_transform(elements, mode):
    """Box orientation: rotated to the first oriented element in parallel
    mode, aligned to the project axes in native mode."""
    t = Transform.Identity
    if mode != MODE_PARALLEL:
        return t
    for elem in elements:
        d = element_direction(elem)
        if d is not None:
            t.BasisX = d
            t.BasisY = XYZ.BasisZ.CrossProduct(d)
            t.BasisZ = XYZ.BasisZ
            return t
    return t


def _walk_geometry(geo, pts):
    for obj in geo:
        if isinstance(obj, Solid):
            for edge in obj.Edges:
                pts.extend(edge.Tessellate())
        elif isinstance(obj, Curve):
            try:
                pts.extend(obj.Tessellate())
            except Exception:
                pass
        elif isinstance(obj, Mesh):
            pts.extend(obj.Vertices)
        elif isinstance(obj, Point):
            pts.append(obj.Coord)
        elif isinstance(obj, GeometryInstance):
            _walk_geometry(obj.GetInstanceGeometry(), pts)


def element_points(elem):
    pts = []
    opts = Options()
    opts.DetailLevel = ViewDetailLevel.Medium
    try:
        geo = elem.get_Geometry(opts)
        if geo is not None:
            _walk_geometry(geo, pts)
    except Exception:
        pts = []
    if pts:
        return pts

    bb = elem.get_BoundingBox(None)
    if bb is None:
        return []
    lo, hi = bb.Min, bb.Max
    corners = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                corners.append(bb.Transform.OfPoint(XYZ(x, y, z)))
    return corners


def box_for_elements(elements, mode, offset):
    """Section box around elements, padded by offset on every side."""
    t = selection_transform(elements, mode)
    inv = t.Inverse
    lo = [float('inf')] * 3
    hi = [float('-inf')] * 3
    for elem in elements:
        for p in element_points(elem):
            q = inv.OfPoint(p)
            for i, v in enumerate((q.X, q.Y, q.Z)):
                if v < lo[i]:
                    lo[i] = v
                if v > hi[i]:
                    hi[i] = v
    if lo[0] == float('inf'):
        return None

    box = BoundingBoxXYZ()
    box.Transform = t
    box.Min = XYZ(lo[0] - offset, lo[1] - offset, lo[2] - offset)
    box.Max = XYZ(hi[0] + offset, hi[1] + offset, hi[2] + offset)
    return box


def resized_box(box, delta):
    """Move every face out by delta (in by a negative delta). Each axis
    keeps at least MIN_BOX_SIZE so the box never collapses."""
    lo, hi = box.Min, box.Max
    new_lo, new_hi = [], []
    for a, b in ((lo.X, hi.X), (lo.Y, hi.Y), (lo.Z, hi.Z)):
        center = (a + b) / 2.0
        half = max((b - a) / 2.0 + delta, MIN_BOX_SIZE / 2.0)
        new_lo.append(center - half)
        new_hi.append(center + half)
    out = BoundingBoxXYZ()
    out.Transform = box.Transform
    out.Min = XYZ(*new_lo)
    out.Max = XYZ(*new_hi)
    return out


def is_at_min_size(box):
    lo, hi = box.Min, box.Max
    return all((b - a) <= MIN_BOX_SIZE + 1e-6
               for a, b in ((lo.X, hi.X), (lo.Y, hi.Y), (lo.Z, hi.Z)))


# --------------------------------------------------------------------------
# Grow / Shrink buttons
# --------------------------------------------------------------------------
def run_resize(uidoc, grow):
    from pyrevit import forms, revit

    view = active_3d_view(uidoc)
    if view is None:
        forms.alert('Open a 3D view first.', exitscript=True)
    if not view.IsSectionBoxActive:
        forms.alert('The section box is off in this view. Use Toggle or Create first.',
                    exitscript=True)

    step = load_settings()['resize_step']
    box = view.GetSectionBox()
    if not grow and is_at_min_size(box):
        forms.alert('The section box is already as small as it can go.', exitscript=True)

    new_box = resized_box(box, step if grow else -step)
    name = 'IMM Grow Section Box' if grow else 'IMM Shrink Section Box'
    try:
        with revit.Transaction(name):
            view.SetSectionBox(new_box)
    except Exception as ex:
        forms.alert('Could not resize the section box.\n\n{}'.format(ex), exitscript=True)
