# -*- coding: utf-8 -*-
"""Shared logic for the IMM Color Layer tools (CAD panel).

The picked DWG layers get a highlight override (default red) and every other
layer of the same DWG gets a grey override (halftone, optional transparency).
Overrides are set on the layer sub-categories in the active view only; the DWG
itself is not touched. Settings live in data/imm_colorlayer.json (inside the
extension, never next to a model).
"""
import os
import json

from Autodesk.Revit.DB import (
    ElementId, Transaction, OverrideGraphicSettings, Color
)

TITLE = 'IMM Color Layer'
MAX_WEIGHT = 16

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
PREFS_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_colorlayer.json')

# weight 0 = leave the line weight as it is
DEFAULTS = {
    'hi_color': [255, 0, 0],
    'hi_weight': 0,
    'grey_color': [160, 160, 160],
    'grey_weight': 0,
    'grey_transparency': 0,
    'grey_halftone': True,
}


def defaults():
    d = dict(DEFAULTS)
    d['hi_color'] = list(DEFAULTS['hi_color'])
    d['grey_color'] = list(DEFAULTS['grey_color'])
    return d


def load_prefs():
    prefs = defaults()
    try:
        with open(PREFS_FILE, 'r') as f:
            data = json.load(f)
        for k in prefs:
            if k in data:
                prefs[k] = data[k]
    except Exception:
        pass
    return prefs


def save_prefs(prefs):
    try:
        folder = os.path.dirname(PREFS_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(PREFS_FILE, 'w') as f:
            json.dump(prefs, f, indent=1)
    except Exception:
        pass


def _ogs(rgb, weight, halftone=False, transparency=0):
    o = OverrideGraphicSettings()
    o.SetProjectionLineColor(Color(int(rgb[0]), int(rgb[1]), int(rgb[2])))
    if int(weight) > 0:
        o.SetProjectionLineWeight(int(weight))
    if halftone:
        o.SetHalftone(True)
    if int(transparency) > 0:
        o.SetSurfaceTransparency(int(transparency))
    return o


def styles(prefs):
    """(highlight overrides, grey overrides) built from the settings."""
    hi = _ogs(prefs['hi_color'], prefs['hi_weight'])
    grey = _ogs(prefs['grey_color'], prefs['grey_weight'],
                bool(prefs['grey_halftone']), prefs['grey_transparency'])
    return hi, grey


def _eid(eid):
    try:
        return int(eid.Value)
    except AttributeError:
        return eid.IntegerValue


def apply_colors(doc, view, picked, prefs):
    """picked = [(import, [picked layers], [block layers])] from pick_layers.
    Picked layers get the highlight, every other layer of the DWG the grey.
    Returns the number of layers highlighted."""
    hi, grey = styles(prefs)
    count = 0
    t = Transaction(doc, TITLE)
    t.Start()
    try:
        for imp, layers, _blocks in picked:
            keep = set(_eid(c.Id) for c in layers)
            for sub in imp.Category.SubCategories:
                if _eid(sub.Id) in keep:
                    view.SetCategoryOverrides(sub.Id, hi)
                    count += 1
                else:
                    view.SetCategoryOverrides(sub.Id, grey)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return count


STATE_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_colorlayer_state.json')


def _state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _key(doc):
    try:
        return str(doc.ProjectInformation.UniqueId)
    except Exception:
        return str(doc.Title)


def mark_colored(doc, view, imports):
    """Remember which DWGs were colored in this view, so Reset only touches them."""
    data = _state()
    views = data.setdefault(_key(doc), {})
    uids = set(views.get(str(view.UniqueId), []))
    uids.update(str(i.UniqueId) for i in imports)
    views[str(view.UniqueId)] = sorted(uids)
    try:
        folder = os.path.dirname(STATE_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f, indent=1)
    except Exception:
        pass


def colored_imports(doc, view, only=None):
    """DWGs colored in this view (optionally limited to the `only` list)."""
    uids = set(_state().get(_key(doc), {}).get(str(view.UniqueId), []))
    found = []
    for u in uids:
        el = doc.GetElement(u)
        if el is not None and el.Category is not None:
            if only is None or str(el.UniqueId) in set(str(o.UniqueId) for o in only):
                found.append(el)
    return found


def forget_colored(doc, view, imports):
    data = _state()
    views = data.get(_key(doc), {})
    cur = set(views.get(str(view.UniqueId), []))
    cur -= set(str(i.UniqueId) for i in imports)
    if cur:
        views[str(view.UniqueId)] = sorted(cur)
    else:
        views.pop(str(view.UniqueId), None)
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f, indent=1)
    except Exception:
        pass


def reset_colors(doc, view, imports):
    """Clear the overrides of every layer of the DWGs in view."""
    blank = OverrideGraphicSettings()
    t = Transaction(doc, TITLE + ' reset')
    t.Start()
    try:
        for imp in imports:
            cat = imp.Category
            view.SetCategoryOverrides(cat.Id, blank)
            for sub in cat.SubCategories:
                view.SetCategoryOverrides(sub.Id, blank)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return len(imports)
