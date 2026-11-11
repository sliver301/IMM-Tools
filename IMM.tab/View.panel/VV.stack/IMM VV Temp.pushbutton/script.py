# -*- coding: utf-8 -*-
"""Toggle temporary view properties mode on the active view."""
__title__ = 'Temp. VV'
__author__ = 'IMM'

from Autodesk.Revit.DB import ElementId, TemporaryViewMode, Transaction
from pyrevit import forms

import imm_vv as vv

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = uidoc.ActiveView
MODE = TemporaryViewMode.TemporaryViewProperties


def run(action):
    try:
        action()
        return
    except Exception:
        pass
    t = Transaction(doc, 'IMM Temp. VV')
    t.Start()
    try:
        action()
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def enable():
    try:
        view.EnableTemporaryViewPropertiesMode(ElementId.InvalidElementId)
    except Exception:
        tid = view.ViewTemplateId
        if tid == ElementId.InvalidElementId:
            raise
        view.EnableTemporaryViewPropertiesMode(tid)


try:
    if vv.in_temp_mode(view):
        run(lambda: view.DisableTemporaryViewMode(MODE))
    else:
        if vv.view_kind(view) is None:
            forms.alert('This view cannot use temporary view properties.', exitscript=True)
        run(enable)
    uidoc.RefreshActiveView()
except Exception as ex:
    forms.alert('Could not switch temporary view mode.\n\n{}'.format(ex), exitscript=True)
