# -*- coding: utf-8 -*-
"""Turn the section box of the active 3D view on or off.
From a non-3D view, the default 3D view is opened first."""
__title__ = 'Toggle'
__author__ = 'IMM'

from pyrevit import forms, revit

import imm_sectionbox as sb

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

view = sb.active_3d_view(uidoc)
switch_view = view is None

try:
    with revit.Transaction('IMM Toggle Section Box'):
        if view is None:
            view = sb.find_or_create_default_3d(doc)
            if view is None:
                forms.alert('No 3D view type found in this project.', exitscript=True)

        if view.IsSectionBoxActive:
            sb.remember_box(view)
            view.IsSectionBoxActive = False
        else:
            view.IsSectionBoxActive = True
            saved = sb.recall_box(view)
            if saved is not None:
                view.SetSectionBox(saved)
except Exception as ex:
    forms.alert('Could not toggle the section box.\n\n{}'.format(ex), exitscript=True)

if switch_view:
    uidoc.ActiveView = view
