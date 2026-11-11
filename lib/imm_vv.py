# -*- coding: utf-8 -*-
"""Shared helpers for the IMM VV tools (View panel).

The saved 2D and 3D Visibility/Graphics sets live in data/imm_vv.json next to
the lib folder, so they are shared by every Revit project on this PC.
"""
import os
import json
import time

from System import Enum
from Autodesk.Revit.DB import (
    ElementId, OverrideGraphicSettings, Color, View3D, FilterElement,
    FilteredElementCollector, FillPatternElement, LinePatternElement,
    ViewDetailLevel, DisplayStyle, TemporaryViewMode,
)
from pyrevit import forms

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_vv.json')

# View types that have no Visibility/Graphics.
_NO_VG = ('Schedule', 'DrawingSheet', 'Report', 'PanelSchedule', 'ColumnSchedule',
          'CostReport', 'LoadsReport', 'PressureLossReport', 'ProjectBrowser',
          'SystemBrowser', 'Internal', 'Undefined', 'Legend')

# key, getter property, setter method, kind
_OGS = [
    ('pw', 'ProjectionLineWeight', 'SetProjectionLineWeight', 'weight'),
    ('cw', 'CutLineWeight', 'SetCutLineWeight', 'weight'),
    ('pc', 'ProjectionLineColor', 'SetProjectionLineColor', 'color'),
    ('cc', 'CutLineColor', 'SetCutLineColor', 'color'),
    ('pp', 'ProjectionLinePatternId', 'SetProjectionLinePatternId', 'line'),
    ('cp', 'CutLinePatternId', 'SetCutLinePatternId', 'line'),
    ('sfp', 'SurfaceForegroundPatternId', 'SetSurfaceForegroundPatternId', 'fill'),
    ('sfc', 'SurfaceForegroundPatternColor', 'SetSurfaceForegroundPatternColor', 'color'),
    ('sfv', 'IsSurfaceForegroundPatternVisible', 'SetSurfaceForegroundPatternVisible', 'booltrue'),
    ('sbp', 'SurfaceBackgroundPatternId', 'SetSurfaceBackgroundPatternId', 'fill'),
    ('sbc', 'SurfaceBackgroundPatternColor', 'SetSurfaceBackgroundPatternColor', 'color'),
    ('sbv', 'IsSurfaceBackgroundPatternVisible', 'SetSurfaceBackgroundPatternVisible', 'booltrue'),
    ('cfp', 'CutForegroundPatternId', 'SetCutForegroundPatternId', 'fill'),
    ('cfc', 'CutForegroundPatternColor', 'SetCutForegroundPatternColor', 'color'),
    ('cfv', 'IsCutForegroundPatternVisible', 'SetCutForegroundPatternVisible', 'booltrue'),
    ('cbp', 'CutBackgroundPatternId', 'SetCutBackgroundPatternId', 'fill'),
    ('cbc', 'CutBackgroundPatternColor', 'SetCutBackgroundPatternColor', 'color'),
    ('cbv', 'IsCutBackgroundPatternVisible', 'SetCutBackgroundPatternVisible', 'booltrue'),
    ('tr', 'Transparency', 'SetSurfaceTransparency', 'int0'),
    ('ht', 'Halftone', 'SetHalftone', 'boolfalse'),
    ('dl', 'DetailLevel', 'SetDetailLevel', 'detail'),
]


def eid_int(eid):
    try:
        return int(eid.Value)
    except AttributeError:
        return eid.IntegerValue


def make_id(n):
    return ElementId(int(n))


def _is_valid_id(eid):
    return eid is not None and eid != ElementId.InvalidElementId


# ----------------------------------------------------------------- view info
def view_kind(view):
    """'3d', '2d' or None when the view has no Visibility/Graphics."""
    try:
        if str(view.ViewType) in _NO_VG:
            return None
    except Exception:
        return None
    return '3d' if isinstance(view, View3D) else '2d'


def in_temp_mode(view):
    try:
        return view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryViewProperties)
    except Exception:
        return False


def require_vg_view(view):
    kind = view_kind(view)
    if kind is None:
        forms.alert('The active view has no Visibility/Graphics.\nOpen a plan, section, elevation or 3D view first.',
                    exitscript=True)
    return kind


def pick_target(doc, view):
    """Decide what to edit when the view is controlled by a view template.
    Returns 'view', 'detach', 'template' or exits the script."""
    tid = view.ViewTemplateId
    if not _is_valid_id(tid) or in_temp_mode(view):
        return 'view'
    tmpl = doc.GetElement(tid)
    name = tmpl.Name if tmpl else '?'
    detach = 'Detach the template, then change this view'
    edit = 'Change the template "{}" (all views using it)'.format(name)
    choice = forms.alert(
        'This view uses the view template "{}", so its graphics are locked.\n\n'
        'Tip: start Temp. VV first if you only want a temporary change.'.format(name),
        options=[detach, edit], exitscript=True)
    if choice == detach:
        return 'detach'
    if choice == edit:
        return 'template'
    forms.alert('Cancelled.', exitscript=True)


def prepare_target(doc, view, mode):
    """Call inside a transaction. Returns the View object to modify."""
    if mode == 'detach':
        view.ViewTemplateId = ElementId.InvalidElementId
        return view
    if mode == 'template':
        return doc.GetElement(view.ViewTemplateId)
    return view


# --------------------------------------------------------------- json storage
def load_all():
    data = {'2d': None, '3d': None}
    try:
        with open(DATA_FILE) as f:
            loaded = json.load(f)
        data.update(loaded)
    except Exception:
        pass
    return data


def load_slot(kind):
    return load_all().get(kind)


def save_slot(kind, slot):
    data = load_all()
    data[kind] = slot
    folder = os.path.dirname(DATA_FILE)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(DATA_FILE, 'w') as f:
        f.write(json.dumps(data, indent=1, sort_keys=True))


# -------------------------------------------------------- override conversion
def _color_list(c):
    if c is None or not c.IsValid:
        return None
    return [int(c.Red), int(c.Green), int(c.Blue)]


def _name_of(doc, eid):
    if not _is_valid_id(eid):
        return None
    el = doc.GetElement(eid)
    return el.Name if el is not None else None


def ogs_to_dict(doc, ogs):
    d = {}
    for key, getter, _, kind in _OGS:
        try:
            v = getattr(ogs, getter)
        except Exception:
            continue
        if kind == 'weight':
            if v != -1:
                d[key] = int(v)
        elif kind == 'color':
            lst = _color_list(v)
            if lst is not None:
                d[key] = lst
        elif kind in ('line', 'fill'):
            n = _name_of(doc, v)
            if n:
                d[key] = n
        elif kind == 'int0':
            if v:
                d[key] = int(v)
        elif kind == 'booltrue':
            if not v:
                d[key] = False
        elif kind == 'boolfalse':
            if v:
                d[key] = True
        elif kind == 'detail':
            if v != ViewDetailLevel.Undefined:
                d[key] = int(v)
    return d


class _Lookups(object):
    def __init__(self, doc):
        self.fill = {}
        self.line = {}
        self.filters = {}
        for el in FilteredElementCollector(doc).OfClass(FillPatternElement):
            self.fill[el.Name] = el.Id
        for el in FilteredElementCollector(doc).OfClass(LinePatternElement):
            self.line[el.Name] = el.Id
        for el in FilteredElementCollector(doc).OfClass(FilterElement):
            self.filters[el.Name] = el.Id


def dict_to_ogs(d, lk):
    ogs = OverrideGraphicSettings()
    for key, _, setter, kind in _OGS:
        if key not in d:
            continue
        v = d[key]
        try:
            if kind in ('weight', 'int0'):
                val = int(v)
            elif kind == 'color':
                val = Color(v[0], v[1], v[2])
            elif kind == 'line':
                val = lk.line.get(v)
            elif kind == 'fill':
                val = lk.fill.get(v)
            elif kind == 'detail':
                val = Enum.ToObject(ViewDetailLevel, int(v))
            else:
                val = bool(v)
            if val is None:
                continue
            getattr(ogs, setter)(val)
        except Exception:
            pass
    return ogs


# ------------------------------------------------------------ capture / apply
def _all_categories(doc):
    for cat in doc.Settings.Categories:
        yield cat
        try:
            for sub in cat.SubCategories:
                yield sub
        except Exception:
            pass


def capture_view(doc, view):
    data = {'categories': {}, 'filters': [], 'source_view': view.Name,
            'saved_at': time.strftime('%Y-%m-%d %H:%M')}
    for cat in _all_categories(doc):
        eid = cat.Id
        n = eid_int(eid)
        if n >= 0:  # built-in only; imported/custom categories differ per project
            continue
        try:
            if not view.CanCategoryBeHidden(eid):
                continue
            rec = {'n': cat.Name, 'h': bool(view.GetCategoryHidden(eid))}
            o = ogs_to_dict(doc, view.GetCategoryOverrides(eid))
            if o:
                rec['o'] = o
            data['categories'][str(n)] = rec
        except Exception:
            continue
    try:
        for fid in view.GetFilters():
            el = doc.GetElement(fid)
            if el is None:
                continue
            data['filters'].append({
                'n': el.Name,
                'v': bool(view.GetFilterVisibility(fid)),
                'o': ogs_to_dict(doc, view.GetFilterOverrides(fid)),
            })
    except Exception:
        pass
    for key, prop in (('detail_level', 'DetailLevel'), ('display_style', 'DisplayStyle')):
        try:
            data[key] = int(getattr(view, prop))
        except Exception:
            pass
    try:
        data['annotations_hidden'] = bool(view.AreAnnotationCategoriesHidden)
    except Exception:
        pass
    return data


def apply_to_view(doc, view, data):
    """Call inside a transaction. Returns a list of notes about skipped items."""
    notes = []
    lk = _Lookups(doc)
    skipped = 0
    for key, rec in data.get('categories', {}).items():
        try:
            eid = make_id(key)
            if not view.CanCategoryBeHidden(eid):
                continue
            view.SetCategoryHidden(eid, bool(rec.get('h')))
            view.SetCategoryOverrides(eid, dict_to_ogs(rec.get('o', {}), lk))
        except Exception:
            skipped += 1
    if skipped:
        notes.append('{} categories could not be set in this view.'.format(skipped))

    saved = {}
    for f in data.get('filters', []):
        saved[f['n']] = f
    try:
        for fid in list(view.GetFilters()):
            el = doc.GetElement(fid)
            if el is not None and el.Name not in saved:
                view.RemoveFilter(fid)
        have = set(eid_int(f) for f in view.GetFilters())
        missing = []
        for f in data.get('filters', []):
            fid = lk.filters.get(f['n'])
            if fid is None:
                missing.append(f['n'])
                continue
            try:
                if eid_int(fid) not in have:
                    view.AddFilter(fid)
                view.SetFilterVisibility(fid, bool(f.get('v', True)))
                view.SetFilterOverrides(fid, dict_to_ogs(f.get('o', {}), lk))
            except Exception:
                missing.append(f['n'])
        if missing:
            notes.append('Filters not applied (missing or not valid here): ' + ', '.join(missing))
    except Exception:
        pass

    if 'detail_level' in data:
        try:
            view.DetailLevel = Enum.ToObject(ViewDetailLevel, data['detail_level'])
        except Exception:
            pass
    if 'display_style' in data:
        try:
            view.DisplayStyle = Enum.ToObject(DisplayStyle, data['display_style'])
        except Exception:
            pass
    if 'annotations_hidden' in data:
        try:
            view.AreAnnotationCategoriesHidden = bool(data['annotations_hidden'])
        except Exception:
            pass
    return notes


def store_current(uidoc, forced=None):
    """Save the active view's Visibility/Graphics as the 2D or 3D set."""
    doc = uidoc.Document
    view = uidoc.ActiveView
    kind = require_vg_view(view)
    if forced and kind != forced:
        forms.alert('The active view is a {} view.\nOpen a {} view to set the {} template.'.format(
            kind.upper(), forced.upper(), forced.upper()), exitscript=True)
    data = capture_view(doc, view)
    try:
        save_slot(kind, data)
    except Exception as ex:
        forms.alert('Could not write the settings file:\n{}\n\n{}'.format(DATA_FILE, ex), exitscript=True)
    forms.alert('Saved the {} VV set from "{}".\n{} categories, {} filters.\n\nFile: {}'.format(
        kind.upper(), view.Name, len(data['categories']), len(data['filters']), DATA_FILE))
