# -*- coding: utf-8 -*-
"""Set one line weight and color on every layer of the selected DWGs in the active view."""
__title__ = 'DWG\nStyle'
__author__ = 'IMM'

import os

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System.Windows.Forms as WinForms
from System.Windows.Controls import Button
from System.Windows import Thickness
from System.Windows.Media import SolidColorBrush, Color as WColor
from pyrevit import forms, script

import imm_dwgstyle as ds
import imm_isolate as iso

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

SWATCHES = [(0, 0, 0), (255, 0, 0), (255, 128, 0), (255, 255, 0), (0, 200, 0),
            (0, 200, 200), (0, 0, 255), (200, 0, 200), (128, 128, 128), (255, 255, 255)]


def _brush(rgb):
    return SolidColorBrush(WColor.FromRgb(rgb[0], rgb[1], rgb[2]))


class StyleWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        weight, rgb = ds.load_prefs()
        for n in range(1, ds.MAX_WEIGHT + 1):
            self.cmbWeight.Items.Add(str(n))
        self.cmbWeight.SelectedIndex = max(0, min(ds.MAX_WEIGHT, weight) - 1)
        self.result = None
        self._rgb = rgb
        for sw in SWATCHES:
            b = Button()
            b.Width = 26
            b.Height = 26
            b.Margin = Thickness(0, 0, 4, 4)
            b.Background = _brush(sw)
            b.Tag = '%d,%d,%d' % sw
            b.Click += self.OnSwatchClick
            self.pnlSwatches.Children.Add(b)
        self._show()

    def _show(self):
        self.brdPreview.Background = _brush(self._rgb)

    def OnSwatchClick(self, sender, args):
        self._rgb = [int(x) for x in sender.Tag.split(',')]
        self._show()

    def OnCustomClick(self, sender, args):
        dlg = WinForms.ColorDialog()
        dlg.FullOpen = True
        from System.Drawing import Color as DColor
        dlg.Color = DColor.FromArgb(self._rgb[0], self._rgb[1], self._rgb[2])
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self._rgb = [dlg.Color.R, dlg.Color.G, dlg.Color.B]
            self._show()

    def OnApplyClick(self, sender, args):
        self.result = (self.cmbWeight.SelectedIndex + 1, self._rgb)
        self.Close()

    def OnCancelClick(self, sender, args):
        self.Close()



imports = iso.selected_imports(uidoc)
if not imports:
    with forms.WarningBar(title='Select the DWG instance to restyle (Esc to cancel)'):
        one = iso.pick_import(uidoc)
    if one is None:
        script.exit()
    imports = [one]

win = StyleWindow(os.path.join(os.path.dirname(__file__), 'style.xaml'))
win.ShowDialog()
if win.result is None:
    script.exit()
weight, rgb = win.result

if not ds.free_template(doc, view):
    script.exit()
try:
    n = ds.apply_style(doc, view, imports, weight, rgb)
except Exception as ex:
    forms.alert('Could not change the DWG style.\n\n{}'.format(ex), title=ds.TITLE, exitscript=True)
ds.save_prefs(weight, rgb)
uidoc.RefreshActiveView()
forms.toast('Weight {} applied to {} DWG(s) ({} layers)'.format(weight, len(imports), n), title=ds.TITLE)
