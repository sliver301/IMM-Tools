# -*- coding: utf-8 -*-
"""Quick look at your workset situation: live state, active workset,
your worksets, what you own and mapping health."""
__title__ = 'Quick Status'
__author__ = 'IMM'

import os

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')
from System.Windows import Visibility
from System.Windows import PresentationSource
from System.Windows.Forms import Cursor, Screen
from System.Windows.Media import BrushConverter

from pyrevit import forms

import imm_ws_common as common
import imm_ws_core as core
import imm_ws_store as store

DARK = {'Card': '#2B2F36', 'Line': '#3D434C', 'Fg': '#F0F3F6', 'Fg2': '#B3BCC6',
        'Accent': '#4C8DFF', 'Soft': '#353B44'}

uidoc = __revit__.ActiveUIDocument
if uidoc is None:
    forms.alert('Open a model first.', exitscript=True)
doc = uidoc.Document


class StatusWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.conv = BrushConverter()
        if common.is_dark_theme():
            for key, value in DARK.items():
                self.Resources[key] = self.conv.ConvertFromString(value)
        self.open_manager = False
        self.btnClose.Click += lambda s, e: self.Close()
        self.btnOpen.Click += self.on_open
        self.Deactivated += self.on_deactivated
        self.fill()
        self.Loaded += self.on_loaded

    def _chip(self, text, bg, fg):
        self.txtLive.Text = text
        self.chipLive.Background = self.conv.ConvertFromString(bg)
        self.txtLive.Foreground = self.conv.ConvertFromString(fg)

    def fill(self):
        running = common.watcher_running()
        live = common.is_live()
        if running and live:
            self._chip('Live', '#E6F4EA', '#1F7A43')
        elif running:
            self._chip('Offline', '#F0F2F5', '#59636E')
        else:
            self._chip('Not running', '#FDECEC', '#B42318')

        self.txtModel.Text = doc.Title
        settings = common.load_settings()
        self.txtMode.Text = ('Reassign and follow' if settings['mode'] == common.MODE_FOLLOW
                             else 'Reassign after placement')
        if not common.eligible(doc):
            for box in (self.txtActive, self.txtMine, self.txtEditable, self.txtMapping):
                box.Text = '-'
            self.note('This model is not workshared.')
            return

        me = common.username(doc)
        records = store.read_all(doc)
        claims = store.claim_table(records)
        effective, sources, conflicts = store.merge_mappings(records, me)

        active_id = core.active_workset_id(doc)
        active = core.workset_by_id(doc, active_id)
        status, claimers, open_share = store.ws_status(claims, active_id, me)
        text = active.Name if active is not None else '-'
        if status == store.STATUS_OTHERS:
            text += "   ({}'s)".format(', '.join(claimers))
        elif status in (store.STATUS_MINE, store.STATUS_SHARED):
            text += '   (yours)'
        self.txtActive.Text = text

        mine = [core.workset_by_id(doc, w) for w in store.my_worksets(claims, me)]
        mine = sorted(w.Name for w in mine if w is not None)
        self.txtMine.Text = ', '.join(mine) if mine else 'none claimed yet'

        owned = core.owned_by_me(doc, me)
        self.txtEditable.Text = ('{} workset(s)'.format(len(owned)) if owned else 'nothing checked out')

        categories = core.mappable_categories(doc)
        counts = core.category_counts(doc, categories)
        mine_rec = records.get(me) or store.empty_record(me)
        unmapped = [k for k in categories if counts.get(k, 0) > 0
                    and k not in effective and k not in mine_rec['never']]
        open_conflicts = [c for c, i in conflicts.items() if i.get('new')]
        self.txtMapping.Text = '{} mapped, {} used unmapped, {} conflicts'.format(
            len(effective), len(unmapped), len(open_conflicts))

        notes = []
        if not running:
            notes.append('The live watcher is not running. Restart Revit.')
        if status == store.STATUS_OTHERS:
            notes.append('Your active workset is claimed by {}.'.format(', '.join(claimers)))
        if open_conflicts:
            notes.append('Mapping conflicts are waiting in Workset Manager > Mapping.')
        if notes:
            self.note(' '.join(notes))

    def note(self, text):
        self.txtNote.Text = text
        self.txtNote.Visibility = Visibility.Visible

    def on_loaded(self, sender, args):
        # place near the mouse, kept on screen
        try:
            pos = Cursor.Position
            m = PresentationSource.FromVisual(self).CompositionTarget.TransformFromDevice
            x = pos.X * m.M11
            y = pos.Y * m.M22
            screen = Screen.FromPoint(pos)
            right = screen.WorkingArea.Right * m.M11
            bottom = screen.WorkingArea.Bottom * m.M22
            self.Left = min(x - 20, right - self.ActualWidth)
            self.Top = min(y + 10, bottom - self.ActualHeight)
        except Exception:
            pass

    def on_deactivated(self, sender, args):
        try:
            self.Close()
        except Exception:
            pass

    def on_open(self, sender, args):
        self.open_manager = True
        self.Deactivated -= self.on_deactivated
        self.Close()


window = StatusWindow(os.path.join(os.path.dirname(__file__), 'status.xaml'))
window.ShowDialog()
if window.open_manager:
    import imm_ws_manager
    imm_ws_manager.show(__revit__)
