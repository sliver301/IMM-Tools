# -*- coding: utf-8 -*-
"""Shared logic for the IMM DWG Style tools (CAD panel).

Every DWG layer is a sub-category of the import's category, and the contents of
blocks (at any nesting depth) are drawn with their own layer. So overriding the
line weight and color of the import category and of ALL its layer
sub-categories in the active view restyles every line, block and nested block.
Overrides live in the view only; the DWG itself is not touched.
"""
import os
import json

from Autodesk.Revit.DB import (
    ElementId, ImportInstance, Transaction, OverrideGraphicSettings, Color
)

TITLE = 'IMM DWG Style'
MAX_WEIGHT = 16

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
PREFS_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_dwgstyle.json')


def load_prefs():
    try:
        with open(PREFS_FILE, 'r') as f:
            data = json.load(f)
        return int(data.get('weight', 1)), [int(c) for c in data.get('color', [255, 0, 0])]
    except Exception:
        return 1, [255, 0, 0]


def save_prefs(weight, rgb):
    try:
        folder = os.path.dirname(PREFS_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(PREFS_FILE, 'w') as f:
            json.dump({'weight': weight, 'color': list(rgb)}, f)
    except Exception:
        pass


def _targets(imp):
    cat = imp.Category
    ids = [cat.Id]
    for sub in cat.SubCategories:
        ids.append(sub.Id)
    return ids


def free_template(doc, view):
    """Overrides cannot be changed while a view template controls them.
    Returns False when the user declines to detach it."""
    from pyrevit import forms
    tid = view.ViewTemplateId
    if tid == ElementId.InvalidElementId:
        return True
    tmpl = doc.GetElement(tid)
    if not forms.alert('This view uses the view template "{}", which controls graphic '
                       'overrides.\n\nDetach the template from this view and continue?'
                       .format(tmpl.Name if tmpl else ''),
                       title=TITLE, yes=True, no=True):
        return False
    t = Transaction(doc, TITLE + ' detach template')
    t.Start()
    try:
        view.ViewTemplateId = ElementId.InvalidElementId
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return True


def apply_style(doc, view, imports, weight, rgb):
    """Set line weight (1-16) and color on every layer of the DWGs in view.
    Returns the number of categories overridden."""
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineWeight(int(weight))
    ogs.SetProjectionLineColor(Color(int(rgb[0]), int(rgb[1]), int(rgb[2])))
    return _override(doc, view, imports, ogs, TITLE)


def reset_style(doc, view, imports):
    """Clear the overrides of every layer of the DWGs in view."""
    return _override(doc, view, imports, OverrideGraphicSettings(), TITLE + ' reset')


def _override(doc, view, imports, ogs, name):
    count = 0
    seen = set()
    t = Transaction(doc, name)
    t.Start()
    try:
        for imp in imports:
            for cid in _targets(imp):
                key = cid.IntegerValue if hasattr(cid, 'IntegerValue') else int(cid.Value)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    view.SetCategoryOverrides(cid, ogs)
                    count += 1
                except Exception:
                    pass
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return count
