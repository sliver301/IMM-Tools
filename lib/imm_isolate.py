# -*- coding: utf-8 -*-
"""Shared logic for the IMM DWG Isolate / Reset tools (CAD panel).

Isolating hides every other layer (DWG sub-category) in the active view and
puts the view in Revit's Temporary Hide/Isolate mode, only to get its blue
frame (Revit cannot hide DWG sub-categories temporarily). What was hidden is
remembered in data/imm_isolate.json so Reset can undo it.
"""
import os
import json

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('WindowsBase')
import ctypes
import System
import System.Windows.Forms as WinForms
from System import TimeSpan, IntPtr
from System.Windows.Threading import DispatcherTimer

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    ElementId, ImportInstance, GeometryInstance, TemporaryViewMode, Transaction,
    Options, Curve, PolyLine, Solid, ViewPlan, XYZ, FilteredElementCollector,
    Transform, SolidUtils, TransactionGroup, OverrideGraphicSettings, Color
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_isolate.json')
LOG_FILE = os.path.join(os.path.dirname(_LIB_DIR), 'data', 'imm_isolate_lastpick.json')
MODE = TemporaryViewMode.TemporaryHideIsolate
TITLE = 'IMM DWG Isolate'


def eid_int(eid):
    try:
        return int(eid.Value)
    except AttributeError:
        return eid.IntegerValue


# ------------------------------------------------------------------- state
def _load():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    folder = os.path.dirname(DATA_FILE)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=1)


def _key(doc):
    try:
        return str(doc.ProjectInformation.UniqueId)
    except Exception:
        return str(doc.Title)


def view_state(doc, view):
    """{'temp': bool, 'dwgs': {import_uid: {'hidden': [...], 'shown': [...]}}}"""
    st = _load().get(_key(doc), {}).get(str(view.UniqueId))
    if not st:
        return {'temp': False, 'dwgs': {}}
    return st


def save_view_state(doc, view, st):
    data = _load()
    proj = data.setdefault(_key(doc), {})
    if st['dwgs']:
        proj[str(view.UniqueId)] = st
    else:
        proj.pop(str(view.UniqueId), None)
    _save(data)


# ------------------------------------------------------------ view / temp mode
def in_temp_mode(view):
    try:
        return view.IsTemporaryHideIsolateActive()
    except Exception:
        return False


def enable_frame(doc, view, layer_ids):
    """Temporary Hide/Isolate on the already hidden layers: no visual change,
    but Revit draws its temporary-mode frame around the view."""
    ids = List[ElementId]()
    for n in layer_ids:
        ids.Add(ElementId(int(n)))
    if ids.Count == 0:
        return
    t = Transaction(doc, TITLE + ' frame on')
    t.Start()
    try:
        view.HideCategoriesTemporary(ids)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _visible_ids(doc, view):
    return set(eid_int(i) for i in FilteredElementCollector(doc, view.Id).ToElementIds())


def disable_frame(doc, view):
    """End Temporary Hide/Isolate but keep whatever the user hid temporarily
    (HH / HI / HC): those elements are hidden again right after."""
    before = _visible_ids(doc, view)
    t = Transaction(doc, TITLE + ' frame off')
    t.Start()
    try:
        view.DisableTemporaryViewMode(MODE)
        doc.Regenerate()
        back = List[ElementId]()
        for n in _visible_ids(doc, view) - before:
            el = doc.GetElement(ElementId(n))
            try:
                if el is not None and el.CanBeHidden(view):
                    back.Add(el.Id)
            except Exception:
                pass
        if back.Count:
            view.HideElementsTemporary(back)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def free_template(doc, view):
    """The layers cannot be hidden while a view template controls the view.
    Returns False when the user declines to detach it."""
    tid = view.ViewTemplateId
    if tid == ElementId.InvalidElementId:
        return True
    tmpl = doc.GetElement(tid)
    if not forms.alert('This view uses the view template "{}", which controls layer '
                       'visibility.\n\nDetach the template from this view and continue?'
                       .format(tmpl.Name if tmpl else ''),
                       title=TITLE, yes=True, no=True):
        return False
    t = Transaction(doc, TITLE + ' detach template')
    t.Start()
    try:
        view.ViewTemplateId = ElementId.InvalidElementId
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return True


# ----------------------------------------------------------------- selection
class _ImportFilter(ISelectionFilter):
    def __init__(self, ids):
        self._ids = ids

    def AllowElement(self, e):
        if not isinstance(e, ImportInstance):
            return False
        return self._ids is None or eid_int(e.Id) in self._ids

    def AllowReference(self, ref, point):
        return True


def selected_imports(uidoc):
    doc = uidoc.Document
    found = []
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, ImportInstance):
            found.append(el)
    return found


def pick_import(uidoc):
    """Pick a DWG import in the model. Returns it or None when cancelled."""
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, _ImportFilter(None),
            'Select the DWG import / link to isolate a layer in (Esc to cancel)')
    except OperationCanceledException:
        return None
    return uidoc.Document.GetElement(ref.ElementId)


def _ctrl_down():
    try:
        return bool(WinForms.Control.ModifierKeys & WinForms.Keys.Control)
    except Exception:
        return False


CURSOR_FILE = os.path.join(_LIB_DIR, 'imm_cursor_add.cur')
WM_SETCURSOR = 0x0020


class _Point(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


try:
    _user32 = ctypes.windll.user32
    _user32.LoadImageW.restype = ctypes.c_void_p
    _user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.SetCursor.restype = ctypes.c_void_p
    _user32.SetCursor.argtypes = [ctypes.c_void_p]
    _user32.WindowFromPoint.restype = ctypes.c_void_p
    _user32.WindowFromPoint.argtypes = [_Point]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    _user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
    _user32.GetDoubleClickTime.restype = ctypes.c_uint
except Exception:
    _user32 = None


WM_LBUTTONDOWN = 0x0201
WM_LBUTTONDBLCLK = 0x0203
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B


class _CursorHook(WinForms.NativeWindow):
    """Sub-classes one Revit window: shows our cursor while Ctrl is held and
    reports left clicks (for double-click-to-finish)."""

    def __init__(self, hwnd, owner):
        self._owner = owner
        self.AssignHandle(IntPtr(hwnd))

    def WndProc(self, m):
        try:
            msg = m.Value if hasattr(m, 'Value') else m
            if msg.Msg == WM_SETCURSOR and self._owner.active:
                _user32.SetCursor(self._owner.hcur)
                msg.Result = IntPtr(1)
                if hasattr(m, 'Value'):
                    m.Value = msg
                return
            if msg.Msg in (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK):
                self._owner.on_click()
        except Exception:
            pass
        WinForms.NativeWindow.WndProc(self, m)


class PickSession(object):
    """Runs beside Revit's pick prompt:
    - holding Ctrl swaps Revit's cursor for an arrow with a +
    - Enter, or a double-click on empty space, finishes the selection
      (an Esc is sent to end Revit's prompt and flagged as "approved")."""

    def __init__(self):
        self.hcur = None
        self.active = False
        self.approved = False
        self.picks = 0
        self._hooks = {}
        self._timer = None
        self._pid = None
        self._down = None
        self._enter = False
        self._dbl = 500

    def start(self):
        if _user32 is None:
            return
        try:
            self._pid = System.Diagnostics.Process.GetCurrentProcess().Id
            self._dbl = int(_user32.GetDoubleClickTime()) or 500
            self._enter = bool(_user32.GetAsyncKeyState(VK_RETURN) & 0x8000)
            self.hcur = _user32.LoadImageW(None, CURSOR_FILE, 2, 0, 0, 0x10)
            self._timer = DispatcherTimer()
            self._timer.Interval = TimeSpan.FromMilliseconds(25)
            self._timer.Tick += self._tick
            self._timer.Start()
        except Exception:
            self._timer = None

    def _ours(self, hwnd):
        if not hwnd:
            return False
        pid = ctypes.c_ulong(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return self._pid is None or pid.value == self._pid

    def _window_under_cursor(self):
        pt = _Point()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        hwnd = _user32.WindowFromPoint(pt)
        return hwnd if self._ours(hwnd) else None

    def approve(self):
        if self.approved:
            return
        self.approved = True
        try:
            _user32.keybd_event(VK_ESCAPE, 0, 0, None)
            _user32.keybd_event(VK_ESCAPE, 0, 2, None)
        except Exception:
            pass

    def on_click(self):
        """Two clicks close together that picked nothing = double-click outside."""
        try:
            pt = _Point()
            _user32.GetCursorPos(ctypes.byref(pt))
            now = System.Environment.TickCount
            d = self._down
            if (d is not None and now - d[0] <= self._dbl and abs(pt.x - d[1]) <= 4
                    and abs(pt.y - d[2]) <= 4 and d[3] == self.picks):
                self._down = None
                self.approve()
            else:
                self._down = (now, pt.x, pt.y, self.picks)
        except Exception:
            pass

    def _tick(self, sender, args):
        try:
            hwnd = self._window_under_cursor()
            if hwnd and hwnd not in self._hooks:
                self._hooks[hwnd] = _CursorHook(hwnd, self)
            ctrl = _ctrl_down()
            if ctrl != self.active:
                self.active = ctrl
                if ctrl and hwnd and self.hcur:
                    _user32.SetCursor(self.hcur)
            enter = bool(_user32.GetAsyncKeyState(VK_RETURN) & 0x8000)
            if enter and not self._enter and self._ours(_user32.GetForegroundWindow()):
                self.approve()
            self._enter = enter
        except Exception:
            pass

    def stop(self):
        try:
            if self._timer is not None:
                self._timer.Stop()
        except Exception:
            pass
        self.active = False
        for hook in self._hooks.values():
            try:
                hook.ReleaseHandle()
            except Exception:
                pass
        self._hooks = {}


class Preview(object):
    """While several layers are being picked, greys out (halftone) the other
    layers of the DWG and draws the picked ones red. Everything runs in a
    transaction group that is rolled back at the end, so nothing is kept."""

    def __init__(self, uidoc):
        self._uidoc = uidoc
        self._doc = uidoc.Document
        self._view = uidoc.ActiveView
        self._group = None
        self._failed = False

    def update(self, found):
        if self._failed:
            return
        doc, view = self._doc, self._view
        try:
            if self._group is None:
                self._group = TransactionGroup(doc, TITLE + ' preview')
                self._group.Start()
            grey = OverrideGraphicSettings()
            grey.SetHalftone(True)
            grey.SetProjectionLineColor(Color(160, 160, 160))
            red = OverrideGraphicSettings()
            red.SetProjectionLineColor(Color(255, 0, 0))
            t = Transaction(doc, TITLE + ' preview')
            t.Start()
            for imp, picked, _blocks in found.values():
                # Block layers stay grey: their override does not reach the
                # objects inside, so only the picked layers turn red.
                keep = set(eid_int(c.Id) for c in picked)
                for sub in imp.Category.SubCategories:
                    try:
                        view.SetCategoryOverrides(sub.Id, red if eid_int(sub.Id) in keep else grey)
                    except Exception:
                        pass
            t.Commit()
            self._uidoc.RefreshActiveView()
        except Exception:
            self._failed = True
            try:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
            except Exception:
                pass

    def end(self):
        if self._group is not None:
            try:
                self._group.RollBack()
                self._uidoc.RefreshActiveView()
            except Exception:
                pass
            self._group = None


def pick_layers(uidoc, imports):
    """Pick a line/block inside the given DWGs. One click finishes; clicks made
    while holding Ctrl keep picking until a click without Ctrl, Enter or a
    double-click on empty space. Esc cancels everything.
    Returns [(import, [picked layers], [layers of the blocks around them])]
    or [] when cancelled."""
    doc = uidoc.Document
    view = uidoc.ActiveView
    ids = set(eid_int(i.Id) for i in imports)
    found = {}
    order = []
    log = []
    session = PickSession()
    session.start()
    preview = Preview(uidoc)
    try:
        ok = _pick_loop(uidoc, doc, view, ids, found, order, log, session, preview)
    finally:
        session.stop()
        preview.end()
    _write_log(log)
    if not ok:
        return []
    return [found[k] for k in order]


def _pick_loop(uidoc, doc, view, ids, found, order, log, session, preview):
    """Returns True to apply what was picked, False when cancelled."""
    while True:
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.PointOnElement, _ImportFilter(ids),
                'Click a layer to keep (Ctrl + click for more, Enter or double-click '
                'empty space to finish, Esc to cancel)')
        except OperationCanceledException:
            return session.approved
        more = _ctrl_down()
        session.picks += 1
        imp = doc.GetElement(ref.ElementId)
        cats, info = layer_of(doc, view, imp, ref)
        log.append(info)
        if cats:
            key = eid_int(imp.Id)
            if key not in found:
                found[key] = (imp, [], [])
                order.append(key)
            if eid_int(cats[0].Id) not in [eid_int(c.Id) for c in found[key][1]]:
                found[key][1].append(cats[0])
            for c in cats[1:]:
                if eid_int(c.Id) not in [eid_int(x.Id) for x in found[key][2]]:
                    found[key][2].append(c)
        else:
            forms.toast('No layer under that click (text and some hatches carry none). '
                        'Pick a line or block.', title=TITLE)
            continue
        if not more:
            return True
        preview.update(found)


def _write_log(log):
    try:
        folder = os.path.dirname(LOG_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(LOG_FILE, 'w') as f:
            json.dump(log, f, indent=1)
    except Exception:
        pass


def _style_category(doc, gobj):
    try:
        sid = gobj.GraphicsStyleId
    except Exception:
        return None
    if sid is None or sid == ElementId.InvalidElementId:
        return None
    style = doc.GetElement(sid)
    if style is None:
        return None
    try:
        return style.GraphicsStyleCategory
    except Exception:
        return None


def _seg_dist(p, a, b):
    ab = b - a
    ll = ab.DotProduct(ab)
    if ll < 1e-12:
        return p.DistanceTo(a)
    t = max(0.0, min(1.0, (p - a).DotProduct(ab) / ll))
    return p.DistanceTo(a + ab.Multiply(t))


def _transformed(g, tf):
    if tf.IsIdentity:
        return g
    if isinstance(g, Curve):
        return g.CreateTransformed(tf)
    if isinstance(g, PolyLine):
        return g.GetTransformed(tf)
    if isinstance(g, Solid):
        return SolidUtils.CreateTransformed(g, tf)
    return None


def _dist(g, p, flat):
    """Distance from point p to a geometry object (None if not measurable)."""
    if g is None:
        return None
    if isinstance(g, Curve):
        if not g.IsBound:
            return None
        q = XYZ(p.X, p.Y, g.GetEndPoint(0).Z) if flat else p
        res = g.Project(q)
        return res.Distance if res is not None else None
    if isinstance(g, PolyLine):
        pts = list(g.GetCoordinates())
        if not pts:
            return None
        q = XYZ(p.X, p.Y, pts[0].Z) if flat else p
        if len(pts) == 1:
            return q.DistanceTo(pts[0])
        return min(_seg_dist(q, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    if isinstance(g, Solid):
        best = None
        for e in g.Edges:
            d = _dist(e.AsCurve(), p, flat)
            if d is not None and (best is None or d < best):
                best = d
        return best
    return None


TIE = 0.003  # ft (about 1 mm): geometry this close counts as "under the cursor"


def _ref_category(doc, imp, ref):
    """Layer Revit itself reports for the pick, unless it only gives the block."""
    try:
        gobj = imp.GetGeometryObjectFromReference(ref)
    except Exception:
        return None
    if gobj is None or isinstance(gobj, GeometryInstance):
        return None
    return _style_category(doc, gobj)


def layer_of(doc, view, imp, ref):
    """Layer sub-category of the DWG geometry under a pick.

    Uses the geometry nearest to the picked point: for objects inside blocks the
    pick reference only gives the block. When several layers lie on top of each
    other at that spot, the layer Revit reports for the reference wins, then
    lines over hatches, and Defpoints last. Returns ([picked layer, layers of
    the blocks around it], log info) or (None, log info)."""
    parent = imp.Category
    point = ref.GlobalPoint
    info = {'point': [round(point.X, 4), round(point.Y, 4), round(point.Z, 4)]
            if point is not None else None}
    if parent is None or point is None:
        return None, info
    opt = Options()
    opt.View = view
    flat = isinstance(view, ViewPlan)
    cands = []

    # GetSymbolGeometry keeps the block nesting (and the layer each block is
    # inserted on); GetInstanceGeometry would flatten it away.
    def walk(geo, tf, chain):
        for g in geo:
            if isinstance(g, GeometryInstance):
                bcat = _style_category(doc, g)
                walk(g.GetSymbolGeometry(), tf.Multiply(g.Transform),
                     chain + ([bcat] if bcat is not None else []))
                continue
            try:
                d = _dist(_transformed(g, tf), point, flat)
            except Exception:
                continue
            if d is None:
                continue
            cat = _style_category(doc, g)
            if cat is not None:
                cands.append((d, isinstance(g, Solid), cat, chain))

    walk(imp.get_Geometry(opt), Transform.Identity, [])
    if not cands:
        return None, info
    best = min(c[0] for c in cands)
    near = [c for c in cands if c[0] <= best + TIE]
    rcat = _ref_category(doc, imp, ref)
    info['best_dist'] = round(best, 5)
    info['near'] = sorted(set(c[2].Name for c in near))
    info['ref_layer'] = rcat.Name if rcat is not None else None

    hit = None
    if rcat is not None:
        for c in near:
            if eid_int(c[2].Id) == eid_int(rcat.Id):
                hit = c
                break
    if hit is None:
        near.sort(key=lambda c: (c[1], c[2].Name.lower() == 'defpoints', c[0]))
        hit = near[0]
    info['chosen'] = hit[2].Name
    # Hiding the layer a block is inserted on hides the whole block, so the
    # layers of every block around the picked object must stay visible too.
    info['block_layers'] = [b.Name for b in hit[3]]
    subs = [_sub_of(parent, c) for c in [hit[2]] + hit[3]]
    if subs[0] is None:
        return None, info
    return [x for x in subs if x is not None], info


def _sub_of(parent, cat):
    for sub in parent.SubCategories:
        if eid_int(sub.Id) == eid_int(cat.Id):
            return sub
    for sub in parent.SubCategories:
        if sub.Name == cat.Name:
            return sub
    return None


# ------------------------------------------------------------------ isolate
def _set_hidden(view, ids, hidden):
    for n in ids:
        eid = ElementId(int(n))
        try:
            if view.CanCategoryBeHidden(eid):
                view.SetCategoryHidden(eid, hidden)
        except Exception:
            pass


def restore(doc, view, rec):
    _set_hidden(view, rec.get('hidden', []), False)
    _set_hidden(view, rec.get('shown', []), True)


def isolate(doc, view, imp, keeps):
    """Hide all layers of imp except the keeps, in view. Updates the saved state.
    Returns the number of layers hidden."""
    st = view_state(doc, view)
    uid = str(imp.UniqueId)
    parent = imp.Category

    keep_ids = set(eid_int(k.Id) for k in keeps)
    hidden, shown = [], []
    t = Transaction(doc, TITLE + ' isolate layer')
    t.Start()
    try:
        old = st['dwgs'].get(uid)
        if old:
            restore(doc, view, old)
        for sub in parent.SubCategories:
            sid = sub.Id
            n = eid_int(sid)
            if n in keep_ids:
                if view.GetCategoryHidden(sid):
                    view.SetCategoryHidden(sid, False)
                    shown.append(n)
            elif view.CanCategoryBeHidden(sid) and not view.GetCategoryHidden(sid):
                view.SetCategoryHidden(sid, True)
                hidden.append(n)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    st['dwgs'][uid] = {'hidden': hidden, 'shown': shown, 'layers': [k.Name for k in keeps]}
    if not in_temp_mode(view):
        try:
            enable_frame(doc, view, hidden)
            st['temp'] = True
        except Exception:
            pass
    save_view_state(doc, view, st)
    return len(hidden)


def reset(doc, view, imports):
    """Undo isolation in view for the given DWGs (None = all isolated ones).
    Returns the number of DWGs reset."""
    st = view_state(doc, view)
    if imports is None:
        uids = list(st['dwgs'].keys())
    else:
        uids = [str(i.UniqueId) for i in imports if str(i.UniqueId) in st['dwgs']]
    if not uids:
        return 0

    t = Transaction(doc, TITLE + ' reset')
    t.Start()
    try:
        for u in uids:
            restore(doc, view, st['dwgs'][u])
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    for u in uids:
        st['dwgs'].pop(u, None)
    if not st['dwgs'] and st.get('temp'):
        st['temp'] = False
        if in_temp_mode(view):
            disable_frame(doc, view)
    save_view_state(doc, view, st)
    return len(uids)
