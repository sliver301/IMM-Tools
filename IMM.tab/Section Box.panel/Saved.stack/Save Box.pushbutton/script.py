# -*- coding: utf-8 -*-
"""Save the active 3D view's section box to the saved list, under a name
(like Revit's Save Selection). Opens the Saved tab with the name ready."""
__title__ = 'Save Box'
__author__ = 'IMM'

import imm_sbhistory_ui

imm_sbhistory_ui.run(__revit__, imm_sbhistory_ui.MODE_SAVE)
