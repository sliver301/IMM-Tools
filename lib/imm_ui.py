# -*- coding: utf-8 -*-
"""Shared look for the IMM windows: theme colours, the common styles
(imm_ui_styles.xaml) and small window helpers.

Rules for every window built on this:
  * No timers or other callbacks may outlive the window. pyRevit clears a
    button script's names when it ends, and a late callback then fails
    outside any error handler and crashes Revit.
  * Every event handler is wrapped in @guard. An exception that escapes a
    WPF handler can surface where nothing catches it (e.g. while Windows is
    still creating the window) and crashes Revit.
  * Never call Activate()/DragMove() from Loaded: Loaded can fire before the
    window is shown (SizeToContent windows), and both throw then. ShowDialog
    activates the window by itself.
"""
import os
import codecs
import traceback

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows.Interop import HwndSource, WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter

from imm_ws_common import is_dark_theme

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
STYLES_FILE = os.path.join(LIB_DIR, 'imm_ui_styles.xaml')

LIGHT = {
    'BG': '#FFFFFF', 'BORDER': '#E3E6EA', 'FG': '#1F2328', 'FG2': '#59636E',
    'TILE': '#F4F5F7', 'TILEH': '#EAF1FE', 'IMGBG': '#E3E6EA', 'ACCENT': '#2F6FEB',
    'TRACK': '#C3C9D1', 'INPUT': '#FFFFFF', 'INPUTB': '#CDD3DA',
    'SEG': '#EEF0F3', 'SEGON': '#FFFFFF', 'WARN': '#C2410C',
}
DARK = {
    'BG': '#2B2F36', 'BORDER': '#3D434C', 'FG': '#F0F3F6', 'FG2': '#B3BCC6',
    'TILE': '#343941', 'TILEH': '#33404F', 'IMGBG': '#1F2329', 'ACCENT': '#4C8DFF',
    'TRACK': '#4A515C', 'INPUT': '#23272D', 'INPUTB': '#4A515C',
    'SEG': '#23272D', 'SEGON': '#3D434C', 'WARN': '#FB923C',
}


LAST_ERROR = ['']


def guard(fn):
    """Decorator for event handlers: never let an exception reach WPF/Revit.
    The last swallowed error is kept in LAST_ERROR[0] for debugging."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            try:
                LAST_ERROR[0] = traceback.format_exc()
            except Exception:
                pass
        return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def palette():
    return DARK if is_dark_theme() else LIGHT


def _read(path):
    with codecs.open(path, 'r', 'utf-8') as f:
        return f.read()


def _styles():
    text = _read(STYLES_FILE)
    start = text.index('<!--BEGIN-->') + len('<!--BEGIN-->')
    end = text.index('<!--END-->')
    return text[start:end]


def load_window(path, colors=None):
    """Parse a window XAML file: paste the shared styles at <!--@STYLES@-->
    and fill in the @TOKEN@ colours."""
    colors = colors or palette()
    text = _read(path).replace('<!--@STYLES@-->', _styles())
    for key, value in colors.items():
        text = text.replace('@' + key + '@', value)
    return XamlReader.Parse(text)


def brush(color):
    return BrushConverter().ConvertFromString(color)


def attach(win, owner_hwnd):
    """Owner = Revit, and the window's pixel -> DIP scale (sx, sy)."""
    helper = WindowInteropHelper(win)
    try:
        helper.Owner = owner_hwnd
    except Exception:
        pass
    try:
        helper.EnsureHandle()
        m = HwndSource.FromHwnd(helper.Handle).CompositionTarget.TransformFromDevice
        return m.M11, m.M22
    except Exception:
        return 1.0, 1.0


def center_on(win, rect, scale):
    """Centre a SizeToContent window on a screen rectangle (pixels)."""
    sx, sy = scale
    win.UpdateLayout()
    w = win.ActualWidth or win.Width
    h = win.ActualHeight or win.Height
    cx = (rect.Left + rect.Right) / 2.0 * sx
    cy = (rect.Top + rect.Bottom) / 2.0 * sy
    win.Left = cx - w / 2.0
    win.Top = cy - h / 2.0


def alert(message):
    """pyRevit's alert, imported only when needed (it is slow to load)."""
    from pyrevit import forms
    forms.alert(message)
