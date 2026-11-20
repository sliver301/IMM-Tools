# -*- coding: utf-8 -*-
"""Load a saved section box: opens the saved list; the chosen box is applied
to the 3D view and becomes the current box of the History."""
__title__ = 'Load Box'
__author__ = 'IMM'

import imm_sbhistory_ui

imm_sbhistory_ui.run(__revit__, imm_sbhistory_ui.MODE_SAVED)
