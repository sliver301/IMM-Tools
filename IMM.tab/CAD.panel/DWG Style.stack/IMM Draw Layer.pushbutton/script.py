# -*- coding: utf-8 -*-
"""Toggle the Draw Layer (foreground / background) of DWGs.
Click: the selected DWGs, or all DWGs visible in the active view when nothing is selected.
Shift+click: every DWG import and link in the whole file."""
__title__ = 'Draw Layer'
__author__ = 'IMM'

import imm_drawlayer as dl

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

try:
    whole_file = bool(__shiftclick__)  # noqa: F821 (set by pyRevit)
except NameError:
    whole_file = False

if whole_file:
    dl.apply(doc, dl.file_imports(doc), 'IMM Toggle All DWG Draw Layers')
else:
    imports = dl.selected_imports(uidoc)
    if not imports:
        imports = dl.view_imports(doc, uidoc.ActiveView)
    dl.apply(doc, imports, 'IMM Toggle DWG Draw Layer')
