# -*- coding: utf-8 -*-
"""Create a section box around the selection.
Parallel mode turns the box to follow the selected element,
native mode keeps it aligned to the project axes (see Settings)."""
__title__ = 'Create'
__author__ = 'IMM'

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import forms, revit

import imm_sectionbox as sb

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

elements = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
elements = [e for e in elements if e is not None]
if not elements:
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, 'Select elements for the section box, then click Finish')
    except OperationCanceledException:
        refs = []
    elements = [doc.GetElement(r) for r in refs]
if not elements:
    forms.alert('Nothing selected.', exitscript=True)

settings = sb.load_settings()
box = sb.box_for_elements(elements, settings['mode'], settings['creation_offset'])
if box is None:
    forms.alert('The selected elements have no geometry to box.', exitscript=True)

view = sb.active_3d_view(uidoc)
switch_view = view is None

try:
    with revit.Transaction('IMM Create Section Box'):
        if view is None:
            view = sb.find_or_create_default_3d(doc)
            if view is None:
                forms.alert('No 3D view type found in this project.', exitscript=True)
        view.IsSectionBoxActive = True
        view.SetSectionBox(box)
except Exception as ex:
    forms.alert('Could not create the section box.\n\n{}'.format(ex), exitscript=True)

if switch_view:
    uidoc.ActiveView = view
