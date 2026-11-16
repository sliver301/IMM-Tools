# -*- coding: utf-8 -*-
"""IMM Worksets: shared constants, personal settings, local files and the
state shared between the watcher (startup) and the buttons.

The watcher runs in the startup script engine and every button runs in its
own engine, so Python objects can't be shared between them. Simple values
(live flag, version counters, status text) go through the AppDomain instead.
"""
import os
import json
import datetime

from System import AppDomain

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(EXT_DIR, 'lib')
DATA_DIR = os.path.join(EXT_DIR, 'data')

SETTINGS_FILE = os.path.join(DATA_DIR, 'imm_worksets_settings.json')
ACTIVITY_FILE = os.path.join(DATA_DIR, 'imm_worksets_activity.json')
SEEN_FILE = os.path.join(DATA_DIR, 'imm_worksets_seen.json')

TXN_PREFIX = 'IMM Worksets'
APP_NAME = 'IMM Workset Manager'

MODE_REASSIGN = 'reassign'
MODE_FOLLOW = 'follow'

DEFAULT_SETTINGS = {
    'live': True,                 # watcher on/off, remembered between sessions
    'mode': MODE_REASSIGN,        # reassign only, or reassign + follow
    'nudge_enabled': True,        # "5 in a row" suggestion (reassign mode)
    'nudge_threshold': 5,
    'notice_seconds': 5,
    'warn_unmapped': True,        # first use of an unmapped category
    'warn_family_load': True,     # family of an unmapped category loaded
    'warn_others': True,          # working on worksets claimed by others
    'notify_owner': True,         # others worked on my worksets (on sync)
    'notify_mapping': True,       # adopted mappings and mapping conflicts
    'checkout_on_claim': False,   # private claim also makes the workset editable
    'follow_notice': False,       # small notice each time follow mode switches
}

MAX_ACTIVITY = 300


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def now_iso():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')


def local_time_text(iso):
    """'2026-11-11T08:30:00' (UTC) -> '11 Nov 10:30' in local time."""
    try:
        utc = datetime.datetime.strptime(iso, '%Y-%m-%dT%H:%M:%S')
        offset = datetime.datetime.now() - datetime.datetime.utcnow()
        local = utc + offset
        return local.strftime('%d %b %H:%M')
    except Exception:
        return iso or ''


def eid_int(eid):
    """ElementId -> int on every Revit version."""
    if eid is None:
        return -1
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def make_eid(value):
    from Autodesk.Revit.DB import ElementId
    try:
        from System import Int64
        return ElementId(Int64(value))
    except Exception:
        return ElementId(int(value))


def username(doc_or_app):
    try:
        return doc_or_app.Application.Username
    except Exception:
        try:
            return doc_or_app.Username
        except Exception:
            return ''


def is_dark_theme():
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        return UIThemeManager.CurrentTheme == UITheme.Dark
    except Exception:
        return False


def doc_key(doc):
    """Stable key for a model: the central path when workshared."""
    try:
        if doc.IsWorkshared:
            from Autodesk.Revit.DB import ModelPathUtils
            path = doc.GetWorksharingCentralModelPath()
            if path is not None:
                return ModelPathUtils.ConvertModelPathToUserVisiblePath(path)
    except Exception:
        pass
    return doc.PathName or doc.Title


def is_cloud(doc):
    try:
        return bool(doc.IsModelInCloud)
    except Exception:
        return False


def eligible(doc):
    """Only workshared project models (not families, not links)."""
    try:
        return (doc is not None and doc.IsWorkshared and not doc.IsFamilyDocument
                and not doc.IsLinked)
    except Exception:
        return False


# --------------------------------------------------------------------------
# JSON files (personal, on this PC only)
# --------------------------------------------------------------------------
def _read_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    try:
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR)
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=1, sort_keys=True)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return True
    except Exception:
        return False


def load_settings():
    data = _read_json(SETTINGS_FILE, {})
    out = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        for key in DEFAULT_SETTINGS:
            if key in data:
                out[key] = data[key]
    if out['mode'] not in (MODE_REASSIGN, MODE_FOLLOW):
        out['mode'] = MODE_REASSIGN
    try:
        out['nudge_threshold'] = max(2, int(out['nudge_threshold']))
    except Exception:
        out['nudge_threshold'] = DEFAULT_SETTINGS['nudge_threshold']
    try:
        out['notice_seconds'] = max(2, min(30, int(out['notice_seconds'])))
    except Exception:
        out['notice_seconds'] = DEFAULT_SETTINGS['notice_seconds']
    return out


def save_settings(settings):
    out = dict(DEFAULT_SETTINGS)
    out.update(settings or {})
    _write_json(SETTINGS_FILE, out)
    bump('CFG_VER')


def read_activity():
    data = _read_json(ACTIVITY_FILE, [])
    return data if isinstance(data, list) else []


def append_activity(entries):
    if not entries:
        return
    data = read_activity()
    data.extend(entries)
    _write_json(ACTIVITY_FILE, data[-MAX_ACTIVITY:])


def clear_activity():
    _write_json(ACTIVITY_FILE, [])


def get_seen(key):
    data = _read_json(SEEN_FILE, {})
    if not isinstance(data, dict):
        return None
    return data.get(key)


def set_seen(key, value):
    data = _read_json(SEEN_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data[key] = value
    _write_json(SEEN_FILE, data)


# --------------------------------------------------------------------------
# State shared between engines (AppDomain)
# --------------------------------------------------------------------------
def shared_get(key, default=None):
    try:
        value = AppDomain.CurrentDomain.GetData('IMM_WS_' + key)
    except Exception:
        value = None
    return default if value is None else value


def shared_set(key, value):
    try:
        AppDomain.CurrentDomain.SetData('IMM_WS_' + key, value)
    except Exception:
        pass


def bump(key):
    try:
        shared_set(key, int(shared_get(key, 0)) + 1)
    except Exception:
        shared_set(key, 1)


def is_live():
    value = shared_get('LIVE')
    if value is None:
        return bool(load_settings().get('live', True))
    return bool(value)


def set_live(state):
    shared_set('LIVE', bool(state))
    settings = load_settings()
    settings['live'] = bool(state)
    _write_json(SETTINGS_FILE, settings)


def watcher_running():
    return bool(shared_get('RUNNING', False))


def watcher_error():
    return shared_get('ERROR', '') or ''


def mapping_changed():
    """Tell the watcher to reload mappings and claims from the model."""
    bump('MAP_VER')
