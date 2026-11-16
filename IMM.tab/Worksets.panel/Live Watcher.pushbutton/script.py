# -*- coding: utf-8 -*-
"""Turn the live workset watcher on or off. The icon shows the state."""
__title__ = 'Live\nWatcher'
__author__ = 'IMM'
__context__ = 'zero-doc'

import os

import imm_ws_common as common


def _icon_path(folder, state):
    name = 'on' if state else 'off'
    if common.is_dark_theme():
        dark = os.path.join(folder, name + '.dark.png')
        if os.path.exists(dark):
            return dark
    return os.path.join(folder, name + '.png')


def _set_icon(button, folder, state):
    try:
        from pyrevit.coreutils.ribbon import ICON_LARGE
        button.set_icon(_icon_path(folder, state), icon_size=ICON_LARGE)
    except Exception:
        button.set_icon(_icon_path(folder, state))


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    try:
        _set_icon(ui_button_cmp, script_cmp.directory, common.is_live())
    except Exception:
        pass
    return True


if __name__ == '__main__':
    from pyrevit import forms, script

    folder = os.path.dirname(__file__)
    new_state = not common.is_live()
    common.set_live(new_state)
    try:
        _set_icon(script.get_button(), folder, new_state)
    except Exception:
        try:
            script.toggle_icon(new_state)
        except Exception:
            pass

    if not common.watcher_running():
        error = common.watcher_error().strip().splitlines()
        reason = error[-1] if error else 'it has not started in this Revit session'
        forms.alert('The setting was saved ({}), but the watcher itself is not running:\n{}\n\n'
                    'Close and reopen Revit to start it. If it still fails, send me this message.'
                    .format('Live' if new_state else 'Offline', reason))
