# -*- coding: utf-8 -*-
"""Section box settings: creation offset, grow/shrink step, parallel or
native orientation, and History recording. Same look as the History window."""
__title__ = 'Settings'
__author__ = 'IMM'

import os

# WPF assemblies first: the System.Windows imports below need them
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import Visibility
from System.Windows.Input import Key, MouseButtonState

import imm_sectionbox as sb
import imm_sbhistory as hist
import imm_ui as ui

doc = __revit__.ActiveUIDocument.Document

MODE_NOTES = {
    sb.MODE_PARALLEL: 'Parallel: the box turns to follow the selected element.',
    sb.MODE_NATIVE: 'Native: the box stays aligned to the project axes.',
}


def _fmt(value):
    return ('%.4f' % value).rstrip('0').rstrip('.')


def _parse(text):
    try:
        return float((text or '').strip().replace(',', '.'))
    except Exception:
        return None


class SettingsWindow(object):
    """Runs inside ShowDialog only; no timers (see lib/imm_ui)."""

    def __init__(self):
        self.closing = False
        self.win = ui.load_window(os.path.join(os.path.dirname(__file__), 'settings.xaml'))
        for name in ('Header', 'CloseButton', 'OffsetBox', 'OffsetUnit', 'StepBox', 'StepUnit',
                     'ParallelOption', 'NativeOption', 'ModeNote', 'HistorySwitch',
                     'ErrorText', 'DefaultsButton', 'CancelButton', 'SaveButton'):
            setattr(self, name, self.win.FindName(name))

        unit = sb.length_unit_label(doc)
        self.OffsetUnit.Text = unit
        self.StepUnit.Text = unit
        self.ParallelOption.Checked += lambda s, e: self._mode_note(sb.MODE_PARALLEL)
        self.NativeOption.Checked += lambda s, e: self._mode_note(sb.MODE_NATIVE)
        self._show(sb.load_settings(), hist.is_enabled())

        self.Header.MouseLeftButtonDown += self._drag
        self.CloseButton.Click += lambda s, e: self._close()
        self.CancelButton.Click += lambda s, e: self._close()
        self.DefaultsButton.Click += lambda s, e: self._defaults()
        self.SaveButton.Click += lambda s, e: self._save()
        self.win.KeyDown += self._on_key

        ui.attach(self.win, __revit__.MainWindowHandle)   # owner = Revit (CenterOwner)
        # ContentRendered, not Loaded: Loaded can fire before the window is shown
        self.win.ContentRendered += self._on_rendered

    def _show(self, settings, history_on):
        self.OffsetBox.Text = _fmt(sb.to_display(doc, settings['creation_offset']))
        self.StepBox.Text = _fmt(sb.to_display(doc, settings['resize_step']))
        if settings['mode'] == sb.MODE_PARALLEL:
            self.ParallelOption.IsChecked = True
        else:
            self.NativeOption.IsChecked = True
        self._mode_note(settings['mode'])
        self.HistorySwitch.IsChecked = bool(history_on)

    @ui.guard
    def _mode_note(self, mode):
        if self.closing:
            return
        self.ModeNote.Text = MODE_NOTES.get(mode, '')

    def _error(self, text):
        self.ErrorText.Text = text
        self.ErrorText.Visibility = Visibility.Visible

    @ui.guard
    def _defaults(self):
        if self.closing:
            return
        self._show({'creation_offset': sb.DEFAULT_CREATION_OFFSET,
                    'resize_step': sb.DEFAULT_RESIZE_STEP,
                    'mode': sb.DEFAULT_MODE}, True)

    @ui.guard
    def _save(self):
        if self.closing:
            return
        offset = _parse(self.OffsetBox.Text)
        step = _parse(self.StepBox.Text)
        if offset is None or offset < 0:
            self._error('Creation offset must be a number of 0 or more.')
            return
        if step is None or step <= 0:
            self._error('Grow / Shrink step must be a number greater than 0.')
            return
        mode = sb.MODE_PARALLEL if self.ParallelOption.IsChecked else sb.MODE_NATIVE
        sb.save_settings(sb.from_display(doc, offset), sb.from_display(doc, step), mode)
        hist.set_enabled(bool(self.HistorySwitch.IsChecked))
        self._close()

    @ui.guard
    def _drag(self, sender, args):
        if self.closing:
            return
        try:
            if args.LeftButton == MouseButtonState.Pressed:
                self.win.DragMove()
        except Exception:
            pass

    @ui.guard
    def _on_key(self, sender, args):
        if self.closing:
            return
        if args.Key == Key.Escape:
            args.Handled = True
            self._close()
        elif args.Key in (Key.Enter, Key.Return):
            args.Handled = True
            self._save()

    @ui.guard
    def _on_rendered(self, sender, args):
        if self.closing:
            return
        self.OffsetBox.Focus()   # ShowDialog activates the window itself

    @ui.guard
    def _close(self):
        if self.closing:
            return
        self.closing = True
        try:
            self.win.Close()
        except Exception:
            pass

    def show(self):
        self.win.ShowDialog()


SettingsWindow().show()
