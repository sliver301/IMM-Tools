# -*- coding: utf-8 -*-
"""Section box settings: creation offset, grow/shrink step, and parallel or native orientation."""
__title__ = 'Settings'
__author__ = 'IMM'

import os

from pyrevit import forms

import imm_sectionbox as sb

doc = __revit__.ActiveUIDocument.Document


def _fmt(value):
    return ('%.4f' % value).rstrip('0').rstrip('.')


def _parse(text):
    try:
        return float(text.strip().replace(',', '.'))
    except Exception:
        return None


class SettingsWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        unit = sb.length_unit_label(doc)
        self.lblOffsetUnit.Text = unit
        self.lblStepUnit.Text = unit
        self._show(sb.load_settings())

    def _show(self, settings):
        self.txtOffset.Text = _fmt(sb.to_display(doc, settings['creation_offset']))
        self.txtStep.Text = _fmt(sb.to_display(doc, settings['resize_step']))
        self.rbParallel.IsChecked = settings['mode'] == sb.MODE_PARALLEL
        self.rbNative.IsChecked = settings['mode'] == sb.MODE_NATIVE

    def OnDefaultsClick(self, sender, args):
        self._show({
            'creation_offset': sb.DEFAULT_CREATION_OFFSET,
            'resize_step': sb.DEFAULT_RESIZE_STEP,
            'mode': sb.DEFAULT_MODE,
        })

    def OnSaveClick(self, sender, args):
        offset = _parse(self.txtOffset.Text)
        step = _parse(self.txtStep.Text)
        if offset is None or offset < 0:
            forms.alert('Creation offset must be a number of 0 or more.')
            return
        if step is None or step <= 0:
            forms.alert('Grow / Shrink step must be a number greater than 0.')
            return
        mode = sb.MODE_PARALLEL if self.rbParallel.IsChecked else sb.MODE_NATIVE
        sb.save_settings(sb.from_display(doc, offset), sb.from_display(doc, step), mode)
        self.Close()

    def OnCancelClick(self, sender, args):
        self.Close()


SettingsWindow(os.path.join(os.path.dirname(__file__), 'settings.xaml')).ShowDialog()
