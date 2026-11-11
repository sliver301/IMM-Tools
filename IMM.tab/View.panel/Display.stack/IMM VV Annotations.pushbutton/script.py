# -*- coding: utf-8 -*-
"""Toggle annotation categories on/off in the active view."""
__title__ = 'Annotations'
__author__ = 'IMM'

from pyrevit import forms, revit

import imm_vv as vv

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = uidoc.ActiveView

vv.require_vg_view(view)
mode = vv.pick_target(doc, view)
try:
    with revit.Transaction('IMM Toggle Annotations'):
        target = vv.prepare_target(doc, view, mode)
        target.AreAnnotationCategoriesHidden = not target.AreAnnotationCategoriesHidden
except Exception as ex:
    forms.alert('Could not toggle annotations.\n\n{}'.format(ex), exitscript=True)
