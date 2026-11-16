# -*- coding: utf-8 -*-
"""Reset the layers changed by Isolate Layer and Color Layer in the active view."""
__title__ = 'Reset\nLayers'
__author__ = 'IMM'

from pyrevit import forms

import imm_isolate as iso
import imm_colorlayer as cl
import imm_dwgstyle as ds

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

selected = iso.selected_imports(uidoc)
only = selected if selected else None

colored = cl.colored_imports(doc, view, only)
if colored and not ds.free_template(doc, view):
    colored = []
try:
    n_iso = iso.reset(doc, view, only)
    n_col = cl.reset_colors(doc, view, colored) if colored else 0
    if colored:
        cl.forget_colored(doc, view, colored)
except Exception as ex:
    forms.alert('Could not reset the layers.\n\n{}'.format(ex), title='IMM Layers', exitscript=True)

if n_iso == 0 and n_col == 0:
    forms.alert('Nothing to reset: no layer was isolated or colored by the plugin in this view'
                + (' for the selected DWG.' if selected else '.'), title='IMM Layers')
else:
    uidoc.RefreshActiveView()
    forms.toast('{} isolated and {} colored DWG(s) reset'.format(n_iso, n_col), title='IMM Layers')
