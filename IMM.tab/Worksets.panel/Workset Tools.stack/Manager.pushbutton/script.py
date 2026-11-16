# -*- coding: utf-8 -*-
"""Open the Workset Manager: create, rename, delete, set active, make
editable, sync, relinquish and claim worksets; map categories to worksets."""
__title__ = 'Workset Manager'
__author__ = 'IMM'

from pyrevit import forms

import imm_ws_manager

if __revit__.ActiveUIDocument is None:
    forms.alert('Open a model first.', exitscript=True)

imm_ws_manager.show(__revit__)
