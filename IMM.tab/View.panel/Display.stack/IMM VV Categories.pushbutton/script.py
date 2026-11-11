# -*- coding: utf-8 -*-
"""Dropdown-style check list of what is in the view: model categories, then linked
models and CAD imports grouped by file type. Unchecked items are hidden live."""
__title__ = 'Categories'
__author__ = 'IMM'

# Grab the mouse position first, before any slow work, so the list opens where you clicked.
import clr
clr.AddReference('System.Windows.Forms')
import System.Windows.Forms
CLICK_POS = System.Windows.Forms.Cursor.Position

import os
import json

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Drawing')
import System.Drawing
import System.Windows.Threading
import System.Windows
import System.Windows.Controls
from System.Collections.Generic import List
Visibility = System.Windows.Visibility
CheckBox = System.Windows.Controls.CheckBox
from Autodesk.Revit.DB import (CategoryType, Element, ElementId, FilteredElementCollector,
                               ElementCategoryFilter, RevitLinkInstance, ImportInstance)
from pyrevit import forms, revit

import imm_vv as vv

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
view = uidoc.ActiveView
XAML = os.path.join(os.path.dirname(__file__), 'categories.xaml')

vv.require_vg_view(view)

CACHE_KEY = 'IMM_VV_CAT_CACHE_V2'
CAD_EXTS = ('dwg', 'dxf', 'dgn', 'sat', 'skp', '3dm', 'axm')


def _domain_get(key):
    try:
        return System.AppDomain.CurrentDomain.GetData(key)
    except Exception:
        return None


def _domain_set(key, value):
    try:
        System.AppDomain.CurrentDomain.SetData(key, value)
    except Exception:
        pass


def _name(el):
    try:
        return el.Name
    except Exception:
        return Element.Name.GetValue(el)


def _ext(name):
    if '.' in name:
        ext = name.rsplit('.', 1)[1].strip().lower()
        if ext and len(ext) <= 4 and ' ' not in ext:
            return ext
    return ''


def _group_rank(group):
    """Order of the sections in the list: categories, Revit links, CAD files, IFC, anything else."""
    if group == '':
        return (0, '')
    if group == 'rvt':
        return (1, '')
    if group in CAD_EXTS:
        return (2, group)
    if group == 'ifc':
        return (3, '')
    return (4, group)


# --------------------------------------------------------------------- entries
class CategoryEntry(object):
    def __init__(self, cat, label=None, group=''):
        self.cat = cat
        self.key = 'c:{}'.format(vv.eid_int(cat.Id))
        self.label = label or cat.Name
        self.group = group

    def is_visible(self, v):
        return not v.GetCategoryHidden(self.cat.Id)

    def set_visible(self, v, visible):
        if v.GetCategoryHidden(self.cat.Id) == visible:
            v.SetCategoryHidden(self.cat.Id, not visible)


class LinkEntry(object):
    """All instances of one linked model (Revit or IFC), hidden as elements in the view."""
    def __init__(self, link_type, instances):
        self.key = 'l:{}'.format(vv.eid_int(link_type.Id))
        label = _name(link_type)
        if not _ext(label):
            label += '.rvt'
        self.label = label
        self.group = _ext(label)
        self.ids = [i.Id for i in instances]

    def _elements(self):
        return [e for e in (doc.GetElement(i) for i in self.ids) if e is not None]

    def is_visible(self, v):
        return any(not e.IsHidden(view) for e in self._elements())

    def set_visible(self, v, visible):
        # Element hiding always acts on the view itself, not on a view template.
        if visible:
            ids = [e.Id for e in self._elements() if e.IsHidden(view)]
            if ids:
                view.UnhideElements(List[ElementId](ids))
        else:
            ids = [e.Id for e in self._elements() if not e.IsHidden(view) and e.CanBeHidden(view)]
            if ids:
                view.HideElements(List[ElementId](ids))


def model_categories():
    cats = []
    seen = set()
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != CategoryType.Model or cat.IsTagCategory:
                continue
            if vv.eid_int(cat.Id) >= 0:  # imported CAD categories are listed separately
                continue
            if cat.Name in seen or not view.CanCategoryBeHidden(cat.Id):
                continue
            seen.add(cat.Name)
            cats.append(cat)
        except Exception:
            continue
    return cats


def link_groups():
    """{link type id: (type, [instances])} for the whole project (a cheap class filter)."""
    groups = {}
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        tid = inst.GetTypeId()
        key = vv.eid_int(tid)
        if key not in groups:
            groups[key] = (doc.GetElement(tid), [])
        groups[key][1].append(inst)
    return groups


def import_groups():
    """{import category id: (category, label)} for CAD files usable in this view."""
    groups = {}
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        try:
            if inst.ViewSpecific and inst.OwnerViewId != view.Id:
                continue
            cat = inst.Category
            if cat is None:
                continue
            key = vv.eid_int(cat.Id)
            if key in groups:
                continue
            tid = inst.GetTypeId()
            label = _name(doc.GetElement(tid)) if tid != ElementId.InvalidElementId else cat.Name
            if not _ext(label):
                label = cat.Name if _ext(cat.Name) else label + '.dwg'
            groups[key] = (cat, label)
        except Exception:
            continue
    return groups


def _any_in_view(cat_id):
    col = FilteredElementCollector(doc, view.Id).WherePasses(ElementCategoryFilter(cat_id))
    return col.WhereElementIsNotElementType().FirstElementId() != ElementId.InvalidElementId


def _any_in_project(cat_id):
    col = FilteredElementCollector(doc).OfCategoryId(cat_id).WhereElementIsNotElementType()
    return col.FirstElementId() != ElementId.InvalidElementId


def scan_keys(cats):
    """Keys of everything present in this view. Hidden items (not collected by the view)
    are kept when they exist in the project, so they can be turned back on."""
    keys = set()
    for cat in cats:
        try:
            if view.GetCategoryHidden(cat.Id):
                if _any_in_project(cat.Id):
                    keys.add('c:{}'.format(vv.eid_int(cat.Id)))
            elif _any_in_view(cat.Id):
                keys.add('c:{}'.format(vv.eid_int(cat.Id)))
        except Exception:
            continue
    try:
        in_view = set(vv.eid_int(i) for i in
                      FilteredElementCollector(doc, view.Id).OfClass(RevitLinkInstance).ToElementIds())
        for key, (ltype, insts) in link_groups().items():
            if any(vv.eid_int(i.Id) in in_view or i.IsHidden(view) for i in insts):
                keys.add('l:{}'.format(key))
    except Exception:
        pass
    try:
        in_view = set(vv.eid_int(i.Category.Id) for i in
                      FilteredElementCollector(doc, view.Id).OfClass(ImportInstance) if i.Category)
        for key, (cat, label) in import_groups().items():
            if key in in_view or view.GetCategoryHidden(cat.Id):
                keys.add('i:{}'.format(key))
    except Exception:
        pass
    return keys


def build_entries(cats, keys):
    entries = []
    for cat in cats:
        if 'c:{}'.format(vv.eid_int(cat.Id)) in keys:
            entries.append(CategoryEntry(cat))
    for key, (ltype, insts) in link_groups().items():
        if 'l:{}'.format(key) in keys and ltype is not None:
            entries.append(LinkEntry(ltype, insts))
    for key, (cat, label) in import_groups().items():
        if 'i:{}'.format(key) in keys:
            entries.append(CategoryEntry(cat, label, _ext(label)))
    return entries


# ---------------------------------------------------------------------- cache
CACHE_ID = '{}|{}'.format(doc.Title, vv.eid_int(view.Id))


def load_cache():
    try:
        raw = _domain_get(CACHE_KEY)
        return set(json.loads(raw).get(CACHE_ID, [])) if raw else set()
    except Exception:
        return set()


def save_cache(keys):
    try:
        raw = _domain_get(CACHE_KEY)
        data = json.loads(raw) if raw else {}
        data[CACHE_ID] = sorted(keys)
        _domain_set(CACHE_KEY, json.dumps(data))
    except Exception:
        pass


# --------------------------------------------------------------------- window
def safe(fn):
    """A WPF event handler must never raise inside Revit: swallow everything."""
    def wrapper(self, *args):
        try:
            return fn(self, *args)
        except Exception:
            pass
    return wrapper


class CategoriesWindow(forms.WPFWindow):
    def __init__(self, entries, target, refresh_fn):
        forms.WPFWindow.__init__(self, XAML)
        self.target = target
        self.refresh_fn = refresh_fn
        self.busy = False
        self.closing = False
        self.rows = []  # (entry, checkbox)
        for e in entries:
            self._add_row(e)
        self._layout()
        # Mouse position is in screen pixels, WPF wants device-independent units.
        g = System.Drawing.Graphics.FromHwnd(System.IntPtr.Zero)
        self.scale = g.DpiX / 96.0
        g.Dispose()
        self.Left = max(0, CLICK_POS.X / self.scale - 24)
        self.Top = CLICK_POS.Y / self.scale + 6
        self.ticks = 0
        self.timer = System.Windows.Threading.DispatcherTimer()
        self.timer.Interval = System.TimeSpan.FromMilliseconds(100)
        self.timer.Tick += self.timer_tick
        self.timer.Start()
        self.KeyDown += self.key_down
        self.refresh_timer = System.Windows.Threading.DispatcherTimer()
        self.refresh_timer.Interval = System.TimeSpan.FromMilliseconds(150)
        self.refresh_timer.Tick += self.refresh_tick
        self.refresh_timer.Start()

    def _add_row(self, entry):
        cb = CheckBox()
        cb.Content = entry.label
        try:
            cb.IsChecked = entry.is_visible(self.target)
        except Exception:
            cb.IsChecked = True
        cb.Click += self.box_clicked
        self.rows.append((entry, cb))

    def _layout(self):
        """Fill the list, with a separator line between sections."""
        self.rows.sort(key=lambda r: (_group_rank(r[0].group), r[0].label.lower()))
        self.CatPanel.Children.Clear()
        text = (self.SearchBox.Text or '').lower()
        last = None
        for entry, cb in self.rows:
            show = text in entry.label.lower()
            cb.Visibility = Visibility.Visible if show else Visibility.Collapsed
            if show:
                if last is not None and entry.group != last:
                    sep = System.Windows.Controls.Separator()
                    sep.Margin = System.Windows.Thickness(0, 5, 0, 5)
                    self.CatPanel.Children.Add(sep)
                last = entry.group
            self.CatPanel.Children.Add(cb)

    @safe
    def refresh_tick(self, sender, args):
        """After the list is on screen, re-scan the view and add items that appeared."""
        self.refresh_timer.Stop()
        self.busy = True
        try:
            fresh = self.refresh_fn()
        finally:
            self.busy = False
        known = set(e.key for e, _ in self.rows)
        new = [e for e in fresh if e.key not in known]
        if new:
            for e in new:
                self._add_row(e)
            self._layout()

    @safe
    def timer_tick(self, sender, args):
        """Close when the mouse is pressed anywhere outside the card."""
        self.ticks += 1
        if self.busy or self.closing or self.ticks < 4:
            return
        if int(System.Windows.Forms.Control.MouseButtons) == 0:
            return
        p = System.Windows.Forms.Cursor.Position
        s = self.scale
        inside = (self.Left * s + 8 <= p.X <= (self.Left + self.ActualWidth) * s - 8 and
                  self.Top * s + 8 <= p.Y <= (self.Top + self.ActualHeight) * s - 8)
        if not inside:
            self._close_later()

    def _close_later(self):
        if self.closing:
            return
        self.closing = True
        try:
            self.Dispatcher.BeginInvoke(System.Action(self._do_close))
        except Exception:
            self._do_close()

    def _do_close(self):
        try:
            self.timer.Stop()
        except Exception:
            pass
        try:
            self.Close()
        except Exception:
            pass

    @safe
    def key_down(self, sender, args):
        if args.Key == System.Windows.Input.Key.Escape:
            self._close_later()

    def _shown_rows(self):
        return [(e, cb) for e, cb in self.rows if cb.Visibility == Visibility.Visible]

    def _apply(self, rows):
        self.busy = True
        try:
            with revit.Transaction('IMM VV Categories'):
                for entry, cb in rows:
                    try:
                        entry.set_visible(self.target, bool(cb.IsChecked))
                    except Exception:
                        pass
            uidoc.RefreshActiveView()
        except Exception:
            pass
        self.busy = False

    @safe
    def box_clicked(self, sender, args):
        for entry, cb in self.rows:
            if cb is sender:
                self._apply([(entry, cb)])

    @safe
    def search_changed(self, sender, args):
        self._layout()

    @safe
    def select_all(self, sender, args):
        rows = self._shown_rows()
        for _, cb in rows:
            cb.IsChecked = True
        self._apply(rows)

    @safe
    def select_none(self, sender, args):
        rows = self._shown_rows()
        for _, cb in rows:
            cb.IsChecked = False
        self._apply(rows)

    @safe
    def select_invert(self, sender, args):
        rows = self._shown_rows()
        for _, cb in rows:
            cb.IsChecked = not cb.IsChecked
        self._apply(rows)


# ----------------------------------------------------------------------- main
all_cats = model_categories()
cached = load_cache()
if cached:
    entries = build_entries(all_cats, cached)  # instant: the window refreshes itself once open
else:
    keys = scan_keys(all_cats)
    save_cache(keys)
    entries = build_entries(all_cats, keys)


def refresh():
    keys = scan_keys(all_cats)
    save_cache(keys)
    return build_entries(all_cats, keys)


if not entries and not cached:
    forms.alert('Nothing to list in this view.', exitscript=True)

mode = vv.pick_target(doc, view)
target = view
try:
    with revit.Transaction('IMM VV Categories (prepare)'):
        target = vv.prepare_target(doc, view, mode)
        try:
            if target.AreModelCategoriesHidden:
                target.AreModelCategoriesHidden = False
        except Exception:
            pass
except Exception as ex:
    forms.alert('Could not prepare the view.\n\n{}'.format(ex), exitscript=True)

CategoriesWindow(entries, target, refresh).ShowDialog()
