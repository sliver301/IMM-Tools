# -*- coding: utf-8 -*-
"""Copy Current View"""
__title__ = 'Copy Current View'
__author__ = 'IMM'

import imm_vv as vv

vv.store_current(__revit__.ActiveUIDocument, None)
