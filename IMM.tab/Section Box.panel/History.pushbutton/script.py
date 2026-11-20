# -*- coding: utf-8 -*-
"""Section box history: the last four section boxes made in this model with a
snapshot each (current on the right), up to four pinned boxes on the left,
and the saved list on the Saved tab. The window lives in lib/imm_sbhistory_ui."""
__title__ = 'History'
__author__ = 'IMM'

import imm_sbhistory_ui

imm_sbhistory_ui.run(__revit__, imm_sbhistory_ui.MODE_RECENT)
