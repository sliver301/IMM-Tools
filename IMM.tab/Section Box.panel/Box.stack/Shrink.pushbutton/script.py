# -*- coding: utf-8 -*-
"""Shrink the section box of the active 3D view on all sides by the step set in Settings."""
__title__ = 'Shrink'
__author__ = 'IMM'

import imm_sectionbox as sb

sb.run_resize(__revit__.ActiveUIDocument, grow=False)
