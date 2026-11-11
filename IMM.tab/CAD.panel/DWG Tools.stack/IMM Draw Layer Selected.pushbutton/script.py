# -*- coding: utf-8 -*-
"""Toggle the Draw Layer (foreground / background) of the selected DWGs.
With nothing selected, all DWGs visible in the active view are used."""
__title__ = 'Selected\nDWG'
__author__ = 'IMM'

import imm_drawlayer as dl

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document

imports = dl.selected_imports(uidoc)
if not imports:
    imports = dl.view_imports(doc, uidoc.ActiveView)

dl.apply(doc, imports, 'IMM Toggle DWG Draw Layer')
