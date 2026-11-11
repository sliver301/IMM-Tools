# -*- coding: utf-8 -*-
"""Toggle the Draw Layer of every DWG import and link in the file.
Sets all to Background; if they are all already Background, sets all to Foreground."""
__title__ = 'All DWGs\nin File'
__author__ = 'IMM'

import imm_drawlayer as dl

doc = __revit__.ActiveUIDocument.Document

dl.apply(doc, dl.file_imports(doc), 'IMM Toggle All DWG Draw Layers')
