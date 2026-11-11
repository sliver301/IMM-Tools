# -*- coding: utf-8 -*-
"""Isolate one or more layers of the selected DWG in the active view."""
__title__ = 'Isolate\nLayer'
__author__ = 'IMM'

from pyrevit import forms, script

import imm_isolate as iso
import imm_vv as vv

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

if vv.view_kind(view) is None:
    forms.alert('The active view has no Visibility/Graphics.\nOpen a plan, section, elevation or 3D view first.',
                title=iso.TITLE, exitscript=True)

imports = iso.selected_imports(uidoc)
if not imports:
    with forms.WarningBar(title='Select the DWG instance to isolate layers in (Esc to cancel)'):
        one = iso.pick_import(uidoc)
    if one is None:
        script.exit()
    imports = [one]

with forms.WarningBar(title='Click a layer to keep. Ctrl + click for several, then Enter or '
                            'double-click empty space to finish. Esc cancels.'):
    picked = iso.pick_layers(uidoc, imports)
if not picked:
    script.exit()

if not iso.free_template(doc, view):
    script.exit()

names = []
count = 0
try:
    for imp, layers, block_layers in picked:
        count += iso.isolate(doc, view, imp, layers + block_layers)
        names.extend(l.Name for l in layers)
except Exception as ex:
    forms.alert('Could not isolate the layers.\n\n{}'.format(ex), title=iso.TITLE, exitscript=True)

uidoc.RefreshActiveView()
forms.toast('Kept {} - {} layer(s) hidden'.format(', '.join(names), count), title=iso.TITLE)
