# -*- coding: utf-8 -*-
"""IMM Section Box History.

Every section box made in a model (with Revit's grips, the IMM tools or any
other add-in) is remembered together with a snapshot of the view. Per model
the last four are kept: the current one plus three older ones. Pinned boxes
are kept on top of those and never drop off.

  * The recorder (started once from startup.py) watches DocumentChanged for
    3D views whose section box changed. It waits until Revit is idle and the
    view has redrawn, then takes the snapshot (a screen grab of the view, or
    an image export when the view is not on screen).
  * The History button shows the four snapshots and puts the chosen box back.

Choosing an older box moves it up to "current"; nothing is dropped, because
no new box was made. Making a box that is already in the list does the same.

The recorder runs in the startup script engine and every button runs in its
own engine, so the on/off flag goes through the AppDomain and the history
itself through files on disk (data/sectionbox_history/<model>/).
"""
import os
import json
import time
import uuid
import shutil
import tempfile
import datetime
import traceback

import clr
clr.AddReference('System.Drawing')
clr.AddReference('System.Windows.Forms')

from System import Action, AppDomain, Int64
from System.Collections.Generic import List
import System.Drawing as Drawing
from System.Drawing.Drawing2D import InterpolationMode
from System.Drawing.Imaging import (Encoder, EncoderParameter, EncoderParameters,
                                    ImageCodecInfo)
import System.Windows.Forms as WinForms

from Autodesk.Revit.DB import (
    ElementClassFilter, ElementId, ExportRange, FilteredElementCollector,
    FitDirectionType, ImageExportOptions, ImageFileType, ImageResolution,
    Transaction, View3D, ViewOrientation3D, XYZ, ZoomFitType
)

import imm_sectionbox as sb
from imm_ws_common import doc_key, eid_int

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(EXT_DIR, 'data')
ROOT_DIR = os.path.join(DATA_DIR, 'sectionbox_history')
SETTINGS_FILE = os.path.join(DATA_DIR, 'imm_sbhistory_settings.json')
HISTORY_FILE = 'history.json'

MAX_RECENT = 4             # unpinned boxes kept: current + the 3 before it
MAX_PINNED = 4             # pinned boxes are kept on top of that, never dropped
MAX_ENTRIES = MAX_RECENT   # old name
SETTLE_SECONDS = 0.45      # wait this long after the last change before the snapshot
MOUSE_WAIT_LIMIT = 15.0    # stop waiting for the mouse button after this long
IMAGE_MAX_WIDTH = 1600     # pixels; big enough for the full-width preview
JPEG_QUALITY = 85
SAME_BOX_TOLERANCE = 0.001  # feet (about 0.3 mm) per corner
RESTORE_CAMERA = True      # going to a box also brings back the view angle of its snapshot

TXN_NAME = 'IMM Section Box History'
SHARED_PREFIX = 'IMM_SBH_'

NO_MOUSE_BUTTON = getattr(WinForms.MouseButtons, 'None')  # "None" is a Python keyword


# --------------------------------------------------------------------------
# Shared state between engines (AppDomain) and the on/off setting
# --------------------------------------------------------------------------
def shared_get(key, default=None):
    try:
        value = AppDomain.CurrentDomain.GetData(SHARED_PREFIX + key)
    except Exception:
        value = None
    return default if value is None else value


def shared_set(key, value):
    try:
        AppDomain.CurrentDomain.SetData(SHARED_PREFIX + key, value)
    except Exception:
        pass


def _bump(key):
    try:
        shared_set(key, int(shared_get(key, 0)) + 1)
    except Exception:
        shared_set(key, 1)


def _log(message):
    shared_set('LAST_LOG', '{} {}'.format(_now(), message))


def is_enabled():
    """Recording is on by default."""
    value = shared_get('ENABLED')
    if value is None:
        value = bool(_read_json(SETTINGS_FILE, {}).get('enabled', True))
        shared_set('ENABLED', value)
    return bool(value)


def set_enabled(state):
    shared_set('ENABLED', bool(state))
    data = _read_json(SETTINGS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data['enabled'] = bool(state)
    _write_json(SETTINGS_FILE, data)


def recorder_running():
    return bool(shared_get('RUNNING', False))


def recorder_error():
    return shared_get('ERROR', '') or ''


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
def _now():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _read_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=1)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return True
    except Exception:
        return False


def _md5(text):
    try:
        import hashlib
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    except Exception:
        from System.Security.Cryptography import MD5
        from System.Text import Encoding
        data = MD5.Create().ComputeHash(Encoding.UTF8.GetBytes(text))
        return ''.join('%02x' % int(b) for b in data)


def _safe_name(text):
    out = []
    for ch in text or 'model':
        out.append(ch if (ch.isalnum() or ch in '-_ ') else '_')
    return (''.join(out).strip() or 'model')[:40]


def model_dir(doc, create=False):
    """One folder per model. Workshared models use the central path, so all
    local copies of the same model share one history."""
    key = doc_key(doc) or doc.Title or 'model'
    base = os.path.splitext(os.path.basename(key.replace('\\', '/').rstrip('/')))[0]
    folder = os.path.join(ROOT_DIR, '{}_{}'.format(_safe_name(base), _md5(key)[:10]))
    if create and not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def _valid(entry):
    return (isinstance(entry, dict) and entry.get('id')
            and isinstance(entry.get('box'), list) and len(entry['box']) == 18)


def is_pinned(entry):
    return bool(entry and entry.get('pinned'))


def _trim(entries):
    """Keep every pinned box and the newest MAX_RECENT unpinned ones, in order."""
    keep_recent = set(id(e) for e in [e for e in entries if not is_pinned(e)][-MAX_RECENT:])
    return [e for e in entries if is_pinned(e) or id(e) in keep_recent]


def load(doc):
    """History of this model, oldest first, current last (pinned ones included)."""
    data = _read_json(os.path.join(model_dir(doc), HISTORY_FILE), {})
    entries = data.get('entries') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    entries = [e for e in entries if _valid(e)]
    # Just-unpinned boxes may push the unpinned count over MAX_RECENT: they
    # stay visible until the next new box trims the list. The cap here only
    # guards against a damaged file.
    return _trim_to(entries, MAX_RECENT + MAX_PINNED)


def _trim_to(entries, limit):
    recent = [e for e in entries if not is_pinned(e)]
    if len(recent) <= limit:
        return entries
    drop = set(id(e) for e in recent[:len(recent) - limit])
    return [e for e in entries if id(e) not in drop]


def save(doc, entries, trim=True):
    """trim=False keeps unpinned boxes beyond the limit (used when unpinning,
    so the box does not vanish the moment it is unpinned)."""
    folder = model_dir(doc, create=True)
    if trim:
        entries = _trim(entries)
    _write_json(os.path.join(folder, HISTORY_FILE),
                {'version': 1, 'model': doc_key(doc), 'entries': entries})
    # snapshots of boxes that dropped off the list
    keep = set(e.get('image') for e in entries if e.get('image'))
    try:
        for name in os.listdir(folder):
            if name.lower().endswith('.jpg') and name not in keep:
                try:
                    os.remove(os.path.join(folder, name))
                except Exception:
                    pass
    except Exception:
        pass
    return entries


def image_path(doc, entry):
    name = entry.get('image') if entry else None
    if not name:
        return None
    path = os.path.join(model_dir(doc), name)
    return path if os.path.isfile(path) else None


def current_entry(doc):
    entries = load(doc)
    return entries[-1] if entries else None


def promote(doc, entry_id):
    """Move an entry to the end of the list (= current). Nothing is dropped."""
    entries = load(doc)
    for entry in entries:
        if entry['id'] == entry_id:
            entries.remove(entry)
            entries.append(entry)
            save(doc, entries, trim=False)
            return entry
    return None


def set_pinned(doc, entry_id, pinned):
    """Pin or unpin a box. Returns None when done, or a message saying why not."""
    entries = load(doc)
    target = None
    for entry in entries:
        if entry['id'] == entry_id:
            target = entry
    if target is None:
        return 'That box is no longer in the history.'
    if pinned and not is_pinned(target):
        if len([e for e in entries if is_pinned(e)]) >= MAX_PINNED:
            return 'Up to {} boxes can be pinned. Unpin one first.'.format(MAX_PINNED)
    target['pinned'] = bool(pinned)
    save(doc, entries, trim=False)
    return None


# --------------------------------------------------------------------------
# Boxes
# --------------------------------------------------------------------------
def entry_box(entry):
    if not entry:
        return None
    try:
        return sb.box_from_list(entry['box'])
    except Exception:
        return None


def corner_tuples(box):
    """The 8 corners in model coordinates. Comparing corners works no matter
    how Revit stores the box (origin, min/max split)."""
    t = box.Transform
    lo, hi = box.Min, box.Max
    out = []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                p = t.OfPoint(XYZ(x, y, z))
                out.append((p.X, p.Y, p.Z))
    return out


def same_corners(a, b, tol=SAME_BOX_TOLERANCE):
    if not a or not b:
        return False
    for p in a:
        found = False
        for q in b:
            if (abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
                    and abs(p[2] - q[2]) <= tol):
                found = True
                break
        if not found:
            return False
    return True


def entry_corners(entry):
    box = entry_box(entry)
    return corner_tuples(box) if box is not None else None


def box_size_text(entry):
    """'12.4 x 8.0 x 3.5 m' from the stored box (internal feet -> metres)."""
    try:
        v = entry['box']
        dims = [abs(v[15 + i] - v[12 + i]) * 0.3048 for i in range(3)]
        return u'{:.1f} \u00d7 {:.1f} \u00d7 {:.1f} m'.format(*dims)
    except Exception:
        return ''


def time_text(entry):
    try:
        t = datetime.datetime.strptime(entry.get('t', ''), '%Y-%m-%dT%H:%M:%S')
    except Exception:
        return ''
    if t.date() == datetime.date.today():
        return t.strftime('%H:%M')
    return t.strftime('%d %b %H:%M')


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
def same_id(a, b):
    return eid_int(a) == eid_int(b)


def find_uiview(uidoc, view):
    try:
        for uiview in uidoc.GetOpenUIViews():
            if same_id(uiview.ViewId, view.Id):
                return uiview
    except Exception:
        pass
    return None


def _usable(view):
    return isinstance(view, View3D) and not view.IsTemplate


def _camera(view):
    try:
        o = view.GetOrientation()
        vals = []
        for p in (o.EyePosition, o.UpDirection, o.ForwardDirection):
            vals.extend([p.X, p.Y, p.Z])
        return vals
    except Exception:
        return None


def _xyz(vals, start):
    return XYZ(vals[start], vals[start + 1], vals[start + 2])


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------
_JPEG = []


def _jpeg_codec():
    if not _JPEG:
        for codec in ImageCodecInfo.GetImageEncoders():
            if codec.MimeType == 'image/jpeg':
                _JPEG.append(codec)
                break
    return _JPEG[0] if _JPEG else None


def _save_scaled(image, path):
    """Save as JPEG, scaled down to IMAGE_MAX_WIDTH. Returns (w, h)."""
    w, h = image.Width, image.Height
    scale = min(1.0, float(IMAGE_MAX_WIDTH) / max(1, w))
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    out = Drawing.Bitmap(nw, nh)
    try:
        g = Drawing.Graphics.FromImage(out)
        try:
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            g.DrawImage(image, 0, 0, nw, nh)
        finally:
            g.Dispose()
        codec = _jpeg_codec()
        if codec is not None:
            params = EncoderParameters(1)
            params.Param[0] = EncoderParameter(Encoder.Quality, Int64(JPEG_QUALITY))
            out.Save(path, codec, params)
        else:
            out.Save(path, Drawing.Imaging.ImageFormat.Jpeg)
    finally:
        out.Dispose()
    return nw, nh


_USER32 = []


def _user32():
    if not _USER32:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        _USER32.append(user32)
    return _USER32[0]


def _revit_in_front(uiapp):
    """True when Revit (or one of its own windows) is the foreground window,
    so the view on screen is not covered by another program."""
    try:
        user32 = _user32()
        fg = user32.GetForegroundWindow()
        if not fg:
            return False
        root = user32.GetAncestor(fg, 3) or fg   # GA_ROOTOWNER
        return int(root) == int(uiapp.MainWindowHandle.ToInt64())
    except Exception:
        return True


def _grab_screen(uiview, path):
    r = uiview.GetWindowRectangle()
    w, h = r.Right - r.Left, r.Bottom - r.Top
    if w < 60 or h < 60:
        return None
    bmp = Drawing.Bitmap(w, h)
    try:
        g = Drawing.Graphics.FromImage(bmp)
        try:
            g.CopyFromScreen(r.Left, r.Top, 0, 0, Drawing.Size(w, h))
        finally:
            g.Dispose()
        return _save_scaled(bmp, path)
    finally:
        bmp.Dispose()


def _export_view(doc, view, path):
    """Image export, for boxes changed in a view that is not on screen."""
    tmp = tempfile.mkdtemp(prefix='imm_sbh_')
    try:
        opts = ImageExportOptions()
        opts.ExportRange = ExportRange.SetOfViews
        opts.SetViewsAndSheets(List[ElementId]([view.Id]))
        opts.FilePath = os.path.join(tmp, 'snap')
        opts.HLRandWFViewsFileType = ImageFileType.PNG
        opts.ShadowViewsFileType = ImageFileType.PNG
        opts.ImageResolution = ImageResolution.DPI_150
        opts.ZoomType = ZoomFitType.FitToPage
        opts.FitDirection = FitDirectionType.Horizontal
        opts.PixelSize = IMAGE_MAX_WIDTH
        doc.ExportImage(opts)
        files = [f for f in os.listdir(tmp) if f.lower().endswith('.png')]
        if not files:
            return None
        image = Drawing.Image.FromFile(os.path.join(tmp, files[0]))
        try:
            return _save_scaled(image, path)
        finally:
            image.Dispose()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def capture(uiapp, doc, view, path):
    """Snapshot of the view. A screen grab when the view is the one on
    screen (fast, exactly what you see), an image export otherwise.
    Returns {'w', 'h', 'zoom'} or None."""
    uidoc = uiapp.ActiveUIDocument
    on_screen = False
    try:
        on_screen = (uidoc is not None and uidoc.Document.Equals(doc)
                     and same_id(uidoc.ActiveView.Id, view.Id))
    except Exception:
        on_screen = False

    if on_screen and _revit_in_front(uiapp):
        uiview = find_uiview(uidoc, view)
        if uiview is not None:
            try:
                size = _grab_screen(uiview, path)
                if size:
                    zoom = None
                    try:
                        c = uiview.GetZoomCorners()
                        zoom = [c[0].X, c[0].Y, c[0].Z, c[1].X, c[1].Y, c[1].Z]
                    except Exception:
                        pass
                    return {'w': size[0], 'h': size[1], 'zoom': zoom}
            except Exception:
                _log('grab: ' + traceback.format_exc())
    try:
        size = _export_view(doc, view, path)
        if size:
            return {'w': size[0], 'h': size[1], 'zoom': None}
    except Exception:
        _log('export: ' + traceback.format_exc())
    return None


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------
def record(uiapp, doc, view):
    """Put the view's section box into the history: new boxes are added as
    current (the oldest drops off), a box that is already in the list moves
    up to current. Returns the entries."""
    if not _usable(view) or not view.IsSectionBoxActive:
        return None
    box = view.GetSectionBox()
    corners = corner_tuples(box)
    entries = load(doc)

    match = None
    for entry in entries:
        if same_corners(corners, entry_corners(entry)):
            match = entry
    if match is not None and match is entries[-1] and image_path(doc, match):
        return entries          # already current, with its snapshot

    folder = model_dir(doc, create=True)
    if match is not None:
        entries.remove(match)
        entry = match
    else:
        entry = {'id': _new_id()}
    entries.append(entry)
    entry.update(_view_fields(view, box))

    name = _image_name(entry['id'])
    shot = capture(uiapp, doc, view, os.path.join(folder, name))
    if shot is not None:
        entry['image'] = name
        entry['w'], entry['h'] = shot['w'], shot['h']
        entry['zoom'] = shot['zoom']
    elif match is None:
        entry['image'] = None
        entry['zoom'] = None
    return save(doc, entries)


def _new_id():
    return uuid.uuid4().hex[:12]


def _image_name(entry_id):
    # new file name each time so a window never shows a stale cached image
    return '{}_{}.jpg'.format(entry_id, int(time.time() * 1000) % 100000000)


def _view_fields(view, box):
    return {
        'box': sb.box_to_list(box),
        'view': view.UniqueId,
        'view_name': view.Name,
        'persp': bool(view.IsPerspective),
        'cam': _camera(view),
        't': _now(),
    }


def view_entry(uiapp, doc, view):
    """The view's current box as an entry with a snapshot, for saving it.
    Uses the history's current entry when it is the same box; otherwise
    takes a snapshot into a scratch file (path in entry['image_path']).
    Call before any window covers the view. None when the box is off."""
    if not _usable(view) or not view.IsSectionBoxActive:
        return None
    box = view.GetSectionBox()
    current = current_entry(doc)
    if current is not None and same_corners(corner_tuples(box), entry_corners(current)):
        path = image_path(doc, current)
        if path:
            entry = dict(current)
            entry['image_path'] = path
            return entry
    entry = {'id': _new_id()}
    entry.update(_view_fields(view, box))
    folder = os.path.join(model_dir(doc, create=True), 'tmp')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        for old in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, old))
            except Exception:
                pass
    except Exception:
        pass
    path = os.path.join(folder, _image_name(entry['id']))
    shot = capture(uiapp, doc, view, path)
    if shot is not None:
        entry['image_path'] = path
        entry['w'], entry['h'] = shot['w'], shot['h']
        entry['zoom'] = shot['zoom']
    return entry


def tidy(doc):
    """Drop unpinned boxes beyond the last MAX_RECENT (boxes unpinned while
    the History window was open stay until it closes)."""
    entries = load(doc)
    if len(_trim(entries)) != len(entries):
        save(doc, entries)


# --------------------------------------------------------------------------
# Saved boxes: a named list with no limit, like Revit's saved selections.
# On this PC, per model: <model folder>/saved/saved.json + snapshots.
# --------------------------------------------------------------------------
SAVED_FILE = 'saved.json'
_SAVED_FIELDS = ('box', 'view', 'view_name', 'persp', 'cam', 'zoom', 'w', 'h')


def saved_dir(doc, create=False):
    folder = os.path.join(model_dir(doc, create), 'saved')
    if create and not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def load_saved(doc):
    data = _read_json(os.path.join(saved_dir(doc), SAVED_FILE), {})
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [i for i in items if _valid(i) and i.get('name')]


def _write_saved(doc, items):
    folder = saved_dir(doc, create=True)
    _write_json(os.path.join(folder, SAVED_FILE),
                {'version': 1, 'model': doc_key(doc), 'items': items})
    keep = set(i.get('image') for i in items if i.get('image'))
    try:
        for name in os.listdir(folder):
            if name.lower().endswith('.jpg') and name not in keep:
                try:
                    os.remove(os.path.join(folder, name))
                except Exception:
                    pass
    except Exception:
        pass


def saved_image_path(doc, item):
    name = item.get('image') if item else None
    if not name:
        return None
    path = os.path.join(saved_dir(doc), name)
    return path if os.path.isfile(path) else None


def saved_name_taken(doc, name, except_id=None):
    key = (name or '').strip().lower()
    for item in load_saved(doc):
        if item['name'].strip().lower() == key and item['id'] != except_id:
            return True
    return False


def next_saved_name(doc):
    names = set(i['name'].strip().lower() for i in load_saved(doc))
    n = 1
    while 'box {}'.format(n) in names:
        n += 1
    return 'Box {}'.format(n)


def add_saved(doc, entry, name, image_src=None):
    """Save a box (a history entry or a view_entry) under a name. Its
    snapshot is copied, so it stays when the history moves on."""
    name = (name or '').strip()
    if not name:
        raise Exception('Give the box a name.')
    if saved_name_taken(doc, name):
        raise Exception('A saved box called "{}" already exists.'.format(name))
    items = load_saved(doc)
    item = {'id': _new_id(), 'name': name, 't': _now(), 'image': None}
    for key in _SAVED_FIELDS:
        if key in entry:
            item[key] = entry[key]
    src = image_src or entry.get('image_path')
    if src and os.path.isfile(src):
        folder = saved_dir(doc, create=True)
        item['image'] = _image_name(item['id'])
        try:
            shutil.copyfile(src, os.path.join(folder, item['image']))
        except Exception:
            item['image'] = None
    items.append(item)
    _write_saved(doc, items)
    return item


def rename_saved(doc, item_id, name):
    name = (name or '').strip()
    if not name:
        raise Exception('Give the box a name.')
    if saved_name_taken(doc, name, except_id=item_id):
        raise Exception('A saved box called "{}" already exists.'.format(name))
    items = load_saved(doc)
    for item in items:
        if item['id'] == item_id:
            item['name'] = name
    _write_saved(doc, items)


def delete_saved(doc, item_id):
    _write_saved(doc, [i for i in load_saved(doc) if i['id'] != item_id])


def adopt(doc, item):
    """Make a saved box the current box of the history: an identical box in
    the history moves up, otherwise it is added as a new box (snapshot
    copied), like any newly made box."""
    corners = entry_corners(item)
    entries = load(doc)
    match = None
    for entry in entries:
        if same_corners(corners, entry_corners(entry)):
            match = entry
    if match is not None:
        entries.remove(match)
        entries.append(match)
        save(doc, entries)
        return match
    entry = {'id': _new_id(), 't': _now(), 'image': None}
    for key in _SAVED_FIELDS:
        if key in item:
            entry[key] = item[key]
    src = saved_image_path(doc, item)
    if src:
        entry['image'] = _image_name(entry['id'])
        try:
            shutil.copyfile(src, os.path.join(model_dir(doc, create=True), entry['image']))
        except Exception:
            entry['image'] = None
    entries.append(entry)
    save(doc, entries)
    return entry


# --------------------------------------------------------------------------
# Going back to a box (History, Load)
# --------------------------------------------------------------------------
def go_to(uidoc, entry):
    """Go to a history box and make it the current entry."""
    view = apply_box(uidoc, entry)
    promote(uidoc.Document, entry['id'])
    return view


def load_saved_box(uidoc, item):
    """Go to a saved box and make it the current box of the history."""
    view = apply_box(uidoc, item)
    adopt(uidoc.Document, item)
    return view


def apply_box(uidoc, entry):
    """Apply a box to the active 3D view (or the view it came from, or the
    default 3D view), bring back the view angle of its snapshot and zoom to
    the box. Toggle remembers it afterwards."""
    doc = uidoc.Document
    box = entry_box(entry)
    if box is None:
        raise Exception('This entry has no usable box.')

    view = sb.active_3d_view(uidoc)
    switch_view = view is None
    camera_set = False
    t = Transaction(doc, TXN_NAME)
    t.Start()
    try:
        if view is None:
            source = None
            try:
                source = doc.GetElement(entry.get('view') or '')
            except Exception:
                source = None
            view = source if _usable(source) else sb.find_or_create_default_3d(doc)
            if view is None:
                raise Exception('No 3D view type found in this project.')
        view.IsSectionBoxActive = True
        view.SetSectionBox(box)
        cam = entry.get('cam')
        if (RESTORE_CAMERA and cam and len(cam) == 9 and not view.IsLocked
                and bool(entry.get('persp')) == bool(view.IsPerspective)):
            try:
                view.SetOrientation(ViewOrientation3D(_xyz(cam, 0), _xyz(cam, 3), _xyz(cam, 6)))
                camera_set = True
            except Exception:
                camera_set = False
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    finally:
        t.Dispose()

    try:
        sb.remember_box(view)   # Toggle off/on keeps this box
    except Exception:
        pass

    if switch_view:
        uidoc.ActiveView = view
    sb.zoom_to_box(uidoc, view, box)   # focus on the box
    return view


# --------------------------------------------------------------------------
# The recorder (started from startup.py)
# --------------------------------------------------------------------------
class Recorder(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.app = uiapp.Application
        _bump('GEN')
        self.gen = shared_get('GEN', 0)
        self.seen = {}       # (model key, view UniqueId) -> corners of the last box seen
        self.pending = {}    # (model key, view UniqueId) -> [first change, last change]
        self.handlers = []

    def start(self):
        self._hook(self.app, 'DocumentChanged', self.on_changed)
        self._hook(self.app, 'DocumentOpened', self.on_opened)
        self._hook(self.app, 'DocumentCreated', self.on_opened)
        self._hook(self.app, 'DocumentClosing', self.on_closing)
        self._hook(self.uiapp, 'Idling', self.on_idling)
        try:
            for doc in self.app.Documents:
                self._seed(doc)
        except Exception:
            _log('seed: ' + traceback.format_exc())
        shared_set('STOP', Action(self.stop))
        shared_set('RUNNING', True)
        shared_set('ERROR', '')

    def _hook(self, source, name, func):
        event = getattr(source, name)
        event += func
        self.handlers.append((source, name, func))

    def stop(self):
        for source, name, func in self.handlers:
            try:
                event = getattr(source, name)
                event -= func
            except Exception:
                pass
        self.handlers = []
        self.pending = {}
        shared_set('RUNNING', False)

    def alive(self):
        return shared_get('GEN', 0) == self.gen

    @staticmethod
    def _eligible(doc):
        try:
            return doc is not None and not doc.IsFamilyDocument and not doc.IsLinked
        except Exception:
            return False

    def _seed(self, doc):
        """Remember the boxes a model already has, so only new ones count."""
        if not self._eligible(doc):
            return
        key = doc_key(doc)
        for view in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if not view.IsTemplate and view.IsSectionBoxActive:
                    self.seen[(key, view.UniqueId)] = corner_tuples(view.GetSectionBox())
            except Exception:
                pass

    # ------------------------------------------------------------------
    def on_opened(self, sender, args):
        if not self.alive():
            return
        try:
            self._seed(args.Document)
        except Exception:
            _log('opened: ' + traceback.format_exc())

    def on_closing(self, sender, args):
        if not self.alive():
            return
        try:
            key = doc_key(args.Document)
            for k in [k for k in self.seen if k[0] == key]:
                del self.seen[k]
            for k in [k for k in self.pending if k[0] == key]:
                del self.pending[k]
        except Exception:
            pass

    def on_changed(self, sender, args):
        if not self.alive() or not is_enabled():
            return
        try:
            self._changed(args)
        except Exception:
            _log('changed: ' + traceback.format_exc())

    def _changed(self, args):
        doc = args.GetDocument()
        if not self._eligible(doc):
            return
        ids = []
        view_filter = ElementClassFilter(View3D)
        for getter in (args.GetModifiedElementIds, args.GetAddedElementIds):
            try:
                ids.extend(getter(view_filter))
            except Exception:
                pass
        # Dragging the box grips may only touch the box element, so always
        # look at the active view as well.
        try:
            uidoc = self.uiapp.ActiveUIDocument
            if uidoc is not None and uidoc.Document.Equals(doc):
                active = uidoc.ActiveView
                if isinstance(active, View3D):
                    ids.append(active.Id)
        except Exception:
            pass
        if not ids:
            return

        key = doc_key(doc)
        done = set()
        now = time.time()
        for eid in ids:
            n = eid_int(eid)
            if n in done:
                continue
            done.add(n)
            view = doc.GetElement(eid)
            if not _usable(view):
                continue
            try:
                if not view.IsSectionBoxActive:
                    continue
                corners = corner_tuples(view.GetSectionBox())
            except Exception:
                continue
            k = (key, view.UniqueId)
            old = self.seen.get(k)
            self.seen[k] = corners
            if old is not None and same_corners(old, corners):
                continue
            first = self.pending.get(k, [now, now])[0]
            self.pending[k] = [first, now]

    # ------------------------------------------------------------------
    def on_idling(self, sender, args):
        if not self.pending or not self.alive():
            return
        try:
            if self._idle(sender):
                args.SetRaiseWithoutDelay()
        except Exception:
            _log('idling: ' + traceback.format_exc())

    def _idle(self, uiapp):
        now = time.time()
        due = []
        for k, (first, last) in list(self.pending.items()):
            if now - last < SETTLE_SECONDS:
                continue
            # still orbiting / dragging: wait, so the snapshot shows the result
            if (WinForms.Control.MouseButtons != NO_MOUSE_BUTTON
                    and now - first < MOUSE_WAIT_LIMIT):
                continue
            due.append(k)
        for k in due:
            del self.pending[k]
            if not is_enabled():
                continue
            doc = self._doc_by_key(uiapp, k[0])
            if doc is None:
                continue
            try:
                view = doc.GetElement(k[1])
                if _usable(view) and view.IsSectionBoxActive:
                    record(uiapp, doc, view)
            except Exception:
                _log('record: ' + traceback.format_exc())
        return bool(self.pending)

    def _doc_by_key(self, uiapp, key):
        try:
            for doc in uiapp.Application.Documents:
                if self._eligible(doc) and doc_key(doc) == key:
                    return doc
        except Exception:
            pass
        return None


def start(uiapp):
    """Called from startup.py. Stops a recorder left by a pyRevit reload."""
    old_stop = shared_get('STOP')
    if old_stop is not None:
        try:
            old_stop.Invoke()
        except Exception:
            pass
        shared_set('STOP', None)
    try:
        recorder = Recorder(uiapp)
        recorder.start()
        return recorder
    except Exception:
        shared_set('RUNNING', False)
        shared_set('ERROR', traceback.format_exc())
        raise
