# -*- coding: utf-8 -*-
"""Clear the IMM DWG Style overrides of the selected DWGs (or all DWGs in the view)."""
__title__ = 'DWG Style\nReset'
__author__ = 'IMM'

from pyrevit import forms, script

import imm_dwgstyle as ds
import imm_drawlayer as dl

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

imports = dl.selected_imports(uidoc) or dl.view_imports(doc, view)
if not imports:
    forms.alert('No DWG imports or links found in this view.', title=ds.TITLE, exitscript=True)
if not ds.free_template(doc, view):
    script.exit()
try:
    ds.reset_style(doc, view, imports)
except Exception as ex:
    forms.alert('Could not reset the DWG style.\n\n{}'.format(ex), title=ds.TITLE, exitscript=True)
uidoc.RefreshActiveView()
forms.toast('{} DWG(s) reset'.format(len(imports)), title=ds.TITLE)
