# -*- coding: utf-8 -*-
"""Personal settings of the Workset Manager: placement mode, the switch
suggestion, notices and claims. Saved on this PC only."""
__title__ = 'Settings'
__author__ = 'IMM'

import os

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
from System.Windows import Visibility
from System.Windows.Media import BrushConverter

from pyrevit import forms

import imm_ws_common as common

DARK = {'Bg': '#1E2228', 'Card': '#2B2F36', 'Line': '#3D434C', 'Fg': '#F0F3F6',
        'Fg2': '#B3BCC6', 'Accent': '#4C8DFF', 'Hover': '#353B44'}


class SettingsWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        if common.is_dark_theme():
            conv = BrushConverter()
            for key, value in DARK.items():
                self.Resources[key] = conv.ConvertFromString(value)
        self.btnSave.Click += self.on_save
        self.btnCancel.Click += lambda s, e: self.Close()
        self.btnDefaults.Click += lambda s, e: self.fill(dict(common.DEFAULT_SETTINGS))
        self.fill(common.load_settings())

    def fill(self, s):
        self.rbReassign.IsChecked = s['mode'] == common.MODE_REASSIGN
        self.rbFollow.IsChecked = s['mode'] == common.MODE_FOLLOW
        self.chkFollowNotice.IsChecked = bool(s['follow_notice'])
        self.chkNudge.IsChecked = bool(s['nudge_enabled'])
        self.tbThreshold.Text = str(s['nudge_threshold'])
        self.chkUnmapped.IsChecked = bool(s['warn_unmapped'])
        self.chkFamily.IsChecked = bool(s['warn_family_load'])
        self.chkOthers.IsChecked = bool(s['warn_others'])
        self.chkOwner.IsChecked = bool(s['notify_owner'])
        self.chkMapping.IsChecked = bool(s['notify_mapping'])
        self.tbSeconds.Text = str(s['notice_seconds'])
        self.chkCheckout.IsChecked = bool(s['checkout_on_claim'])

    def _int(self, box, low, high, label):
        try:
            value = int((box.Text or '').strip())
        except Exception:
            value = None
        if value is None or value < low or value > high:
            raise ValueError('{} must be a whole number from {} to {}.'.format(label, low, high))
        return value

    def on_save(self, sender, args):
        try:
            threshold = self._int(self.tbThreshold, 2, 50, 'The number of placements')
            seconds = self._int(self.tbSeconds, 2, 30, 'The notice time')
        except ValueError as ex:
            self.txtError.Text = str(ex)
            self.txtError.Visibility = Visibility.Visible
            return
        settings = common.load_settings()
        settings.update({
            'mode': common.MODE_FOLLOW if self.rbFollow.IsChecked else common.MODE_REASSIGN,
            'follow_notice': bool(self.chkFollowNotice.IsChecked),
            'nudge_enabled': bool(self.chkNudge.IsChecked),
            'nudge_threshold': threshold,
            'warn_unmapped': bool(self.chkUnmapped.IsChecked),
            'warn_family_load': bool(self.chkFamily.IsChecked),
            'warn_others': bool(self.chkOthers.IsChecked),
            'notify_owner': bool(self.chkOwner.IsChecked),
            'notify_mapping': bool(self.chkMapping.IsChecked),
            'notice_seconds': seconds,
            'checkout_on_claim': bool(self.chkCheckout.IsChecked),
        })
        common.save_settings(settings)
        self.Close()


SettingsWindow(os.path.join(os.path.dirname(__file__), 'settings.xaml')).ShowDialog()
