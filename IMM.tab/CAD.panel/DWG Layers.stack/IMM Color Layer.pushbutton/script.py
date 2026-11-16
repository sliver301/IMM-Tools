# -*- coding: utf-8 -*-
"""Color the clicked DWG layer(s) and grey out all other layers of that DWG.
Click: pick a DWG (or use the selection), then click a line. Ctrl+click for more layers.
Shift+click: open the settings (colors, transparency, line weights)."""
__title__ = 'Color\nLayer'
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

import imm_isolate as iso
import imm_dwgstyle as ds
import imm_colorlayer as cl
import imm_vv as vv

uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
view = uidoc.ActiveView

SWATCHES = [(255, 0, 0), (255, 128, 0), (255, 255, 0), (0, 200, 0), (0, 200, 200),
            (0, 0, 255), (200, 0, 200), (0, 0, 0), (160, 160, 160), (255, 255, 255)]


def _brush(rgb):
    return SolidColorBrush(WColor.FromRgb(int(rgb[0]), int(rgb[1]), int(rgb[2])))


class SettingsWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.saved = False
        for combo in (self.cmbHiWeight, self.cmbGreyWeight):
            combo.Items.Add('Unchanged')
            for n in range(1, cl.MAX_WEIGHT + 1):
                combo.Items.Add(str(n))
        self._rgb = {}
        self._pv = {'hi': self.brdHi, 'grey': self.brdGrey}
        self._add_swatches('hi', self.pnlHiSwatches)
        self._add_swatches('grey', self.pnlGreySwatches)
        self._load(cl.load_prefs())

    def _add_swatches(self, key, panel):
        for sw in SWATCHES:
            b = Button()
            b.Width = 22
            b.Height = 22
            b.Margin = Thickness(0, 0, 4, 4)
            b.Background = _brush(sw)
            b.Tag = '%s:%d,%d,%d' % ((key,) + sw)
            b.Click += self.OnSwatchClick
            panel.Children.Add(b)

    def _load(self, p):
        self._rgb['hi'] = list(p['hi_color'])
        self._rgb['grey'] = list(p['grey_color'])
        self.cmbHiWeight.SelectedIndex = max(0, min(cl.MAX_WEIGHT, int(p['hi_weight'])))
        self.cmbGreyWeight.SelectedIndex = max(0, min(cl.MAX_WEIGHT, int(p['grey_weight'])))
        self.sldTrans.Value = int(p['grey_transparency'])
        self.chkHalftone.IsChecked = bool(p['grey_halftone'])
        self._show()

    def _show(self):
        for k in self._pv:
            self._pv[k].Background = _brush(self._rgb[k])
        self.lblTrans.Text = '{}%'.format(int(self.sldTrans.Value))

    def OnSwatchClick(self, sender, args):
        key, val = sender.Tag.split(':')
        self._rgb[key] = [int(x) for x in val.split(',')]
        self._show()

    def _custom(self, key):
        dlg = WinForms.ColorDialog()
        dlg.FullOpen = True
        from System.Drawing import Color as DColor
        c = self._rgb[key]
        dlg.Color = DColor.FromArgb(c[0], c[1], c[2])
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self._rgb[key] = [dlg.Color.R, dlg.Color.G, dlg.Color.B]
            self._show()

    def OnHiCustom(self, sender, args):
        self._custom('hi')

    def OnGreyCustom(self, sender, args):
        self._custom('grey')

    def OnTransChanged(self, sender, args):
        try:
            self._show()
        except Exception:
            pass

    def OnResetClick(self, sender, args):
        self._load(cl.defaults())

    def OnSaveClick(self, sender, args):
        cl.save_prefs({
            'hi_color': self._rgb['hi'],
            'hi_weight': self.cmbHiWeight.SelectedIndex,
            'grey_color': self._rgb['grey'],
            'grey_weight': self.cmbGreyWeight.SelectedIndex,
            'grey_transparency': int(self.sldTrans.Value),
            'grey_halftone': bool(self.chkHalftone.IsChecked),
        })
        self.saved = True
        self.Close()

    def OnCancelClick(self, sender, args):
        self.Close()


try:
    settings_mode = bool(__shiftclick__)  # noqa: F821 (set by pyRevit)
except NameError:
    settings_mode = False

if settings_mode:
    SettingsWindow(os.path.join(os.path.dirname(__file__), 'settings.xaml')).ShowDialog()
    script.exit()

if vv.view_kind(view) is None:
    forms.alert('The active view has no Visibility/Graphics.\nOpen a plan, section, elevation or 3D view first.',
                title=cl.TITLE, exitscript=True)

prefs = cl.load_prefs()

imports = iso.selected_imports(uidoc)
if not imports:
    with forms.WarningBar(title='Select the DWG instance to color layers in (Esc to cancel)'):
        one = iso.pick_import(uidoc)
    if one is None:
        script.exit()
    imports = [one]

with forms.WarningBar(title='Click a layer to color. Ctrl + click for several, then Enter, Esc or '
                            'double-click empty space to finish.'):
    picked = iso.pick_layers(uidoc, imports, styles=cl.styles(prefs),
                             prompt='Click a layer to color (Ctrl + click for more; Enter, Esc or '
                                    'double-click empty space to finish)')
if not picked:
    script.exit()

if not ds.free_template(doc, view):
    script.exit()

try:
    cl.apply_colors(doc, view, picked, prefs)
    cl.mark_colored(doc, view, [imp for imp, _l, _b in picked])
except Exception as ex:
    forms.alert('Could not color the layers.\n\n{}'.format(ex), title=cl.TITLE, exitscript=True)

uidoc.RefreshActiveView()
names = [l.Name for _imp, layers, _b in picked for l in layers]
forms.toast('Colored {}'.format(', '.join(names)), title=cl.TITLE)
