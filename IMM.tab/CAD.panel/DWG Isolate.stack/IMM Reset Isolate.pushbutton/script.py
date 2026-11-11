# -*- coding: utf-8 -*-
"""Reset DWG layers isolated by the plugin in the active view."""
__title__ = 'Reset\nIsolate'
__author__ = 'IMM'

from pyrevit import forms

import imm_isolate as iso

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

selected = iso.selected_imports(uidoc)
try:
    count = iso.reset(doc, view, selected if selected else None)
except Exception as ex:
    forms.alert('Could not reset the layers.\n\n{}'.format(ex), title=iso.TITLE, exitscript=True)

if count == 0:
    if selected:
        forms.alert('The selected DWG has no isolated layer in this view.', title=iso.TITLE)
    else:
        forms.alert('No DWG was isolated by the plugin in this view.', title=iso.TITLE)
else:
    uidoc.RefreshActiveView()
    forms.toast('{} DWG(s) reset'.format(count), title=iso.TITLE)
