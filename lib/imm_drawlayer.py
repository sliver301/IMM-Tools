# -*- coding: utf-8 -*-
"""Shared logic for the IMM Draw Layer tools (DWG foreground / background)."""
from Autodesk.Revit.DB import (
    BuiltInParameter, FilteredElementCollector, ImportInstance
)

from pyrevit import forms, revit

FOREGROUND = 0
BACKGROUND = 1


def _draw_layer_param(imp):
    param = imp.get_Parameter(BuiltInParameter.IMPORT_BACKGROUND)
    if param is None:
        param = imp.LookupParameter('Draw Layer')
    return param


def is_background(imp):
    param = _draw_layer_param(imp)
    return param is not None and param.AsInteger() == BACKGROUND


def selected_imports(uidoc):
    doc = uidoc.Document
    found = []
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, ImportInstance):
            found.append(el)
    return found


def view_imports(doc, view):
    try:
        return list(FilteredElementCollector(doc, view.Id)
                    .OfClass(ImportInstance).ToElements())
    except Exception:
        return []


def file_imports(doc):
    return list(FilteredElementCollector(doc).OfClass(ImportInstance).ToElements())


def apply(doc, imports, title):
    """Set the draw layer of the given DWGs and report the result.

    Toggle: if every DWG is already Background they all go to Foreground,
    otherwise they all go to Background.
    """
    if not imports:
        forms.alert('No DWG imports or links found.', exitscript=True)

    editable = [i for i in imports if _draw_layer_param(i) is not None
                and not _draw_layer_param(i).IsReadOnly]
    if not editable:
        forms.alert('The Draw Layer parameter could not be edited on these DWGs.',
                    exitscript=True)

    target = FOREGROUND if all(is_background(i) for i in editable) else BACKGROUND

    changed = 0
    try:
        with revit.Transaction(title):
            for imp in editable:
                param = _draw_layer_param(imp)
                if param.AsInteger() != target:
                    param.Set(target)
                    changed += 1
    except Exception as ex:
        forms.alert('Could not change the draw layer.\n\n{}'.format(ex), exitscript=True)

    label = 'Background' if target == BACKGROUND else 'Foreground'
    forms.toast('{} DWG(s) set to {}'.format(len(editable), label), title='IMM Draw Layer')
