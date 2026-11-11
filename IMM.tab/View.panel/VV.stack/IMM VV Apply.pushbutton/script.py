# -*- coding: utf-8 -*-
"""Apply the saved 2D or 3D Visibility/Graphics set to the active view."""
__title__ = 'Apply VV'
__author__ = 'IMM'

from pyrevit import forms, revit

import imm_vv as vv

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = uidoc.ActiveView

kind = vv.require_vg_view(view)
data = vv.load_slot(kind)
if not data:
    forms.alert('No {0} VV set saved yet.\nOpen a {0} view and use IMM VV Settings > Set {0} View Template.'.format(
        kind.upper()), exitscript=True)

mode = vv.pick_target(doc, view)
notes = []
try:
    with revit.Transaction('IMM VV Apply ' + kind.upper()):
        target = vv.prepare_target(doc, view, mode)
        notes = vv.apply_to_view(doc, target, data)
except Exception as ex:
    forms.alert('Could not apply the VV set.\n\n{}'.format(ex), exitscript=True)

if notes:
    forms.alert('Applied, with notes:\n\n' + '\n'.join(notes))
