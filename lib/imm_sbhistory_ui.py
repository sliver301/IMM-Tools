# -*- coding: utf-8 -*-
"""The Section Box History window, shared by three buttons:

  History   - opens on the Recent tab
  Load Box  - opens on the Saved tab
  Save Box  - opens on the Saved tab with the name box ready for the
              view's current section box (closes after saving)

Recent tab: pinned boxes (up to 4) on the left, a divider, then the last 4
boxes, oldest to current. Saved tab: the named list, with search.
Hover a snapshot to see it large under the bar; click to go to the box;
right-click for pin / save / rename / delete.

Everything here runs inside ShowDialog. There are no timers, and every
handler returns at once when the window is closing: nothing of this module
may run after the button script ends (a late callback crashes Revit).
"""
import os
import re

# WPF assemblies first: the System.Windows imports below need them
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System import TimeSpan, Uri
from System.Windows import (CornerRadius, Duration, FontWeights, GridLength,
                            HorizontalAlignment, Point, PresentationSource, Rect,
                            TextTrimming, Thickness, UIElement, VerticalAlignment,
                            Visibility)
from System.Windows.Controls import (Border, Button, ColumnDefinition, ContextMenu,
                                     Grid, Image, MenuItem, Separator, StackPanel,
                                     TextBlock)
from System.Windows.Input import Key, Keyboard
from System.Windows.Media import RectangleGeometry, Stretch
from System.Windows.Media.Animation import DoubleAnimation
from System.Windows.Media.Imaging import (BitmapCacheOption, BitmapCreateOptions,
                                          BitmapImage)

import imm_sectionbox as sb
import imm_sbhistory as hist
import imm_ui as ui

XAML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'imm_sbhistory_ui.xaml')

MODE_RECENT = 'recent'
MODE_SAVED = 'saved'
MODE_SAVE = 'save'

RECENT_SLOTS = hist.MAX_RECENT
GAP = 10                 # space between tiles (DIPs)
DIVIDER = 9              # width of the line between pinned and recent tiles
BAR_PAD = 30             # bar padding + border, left and right together
TILE_PAD = 16            # tile padding + border, left and right together
TILE_TEXT = 56           # tile height below the snapshot (labels, padding)
SCROLL_W = 14            # saved list scroll bar + its gap
BAR_SHARE = 0.78         # 4-tile bar width as a share of the view width
BAR_MIN, BAR_MAX = 560, 1500

# Segoe MDL2 Assets glyphs
G_PIN = u'\ue840'
G_PINNED = u'\ue842'
G_UNPIN = u'\ue77a'
G_GO = u'\ue72a'
G_SAVE = u'\ue74e'
G_RENAME = u'\ue8ac'
G_DELETE = u'\ue74d'

DOT = u'  \u00b7  '


def run(uiapp, mode=MODE_RECENT):
    uidoc = uiapp.ActiveUIDocument
    if uidoc is None:
        return
    doc = uidoc.Document
    if doc.IsFamilyDocument:
        ui.alert('Section boxes work in project models.')
        return

    # Catch up before anything covers the view: a box made a moment ago may
    # not be recorded yet (the recorder waits for Revit to be idle), and Save
    # needs a snapshot of the view's box.
    view_entry = None
    view = sb.active_3d_view(uidoc)
    if view is not None:
        try:
            if view.IsSectionBoxActive and hist.is_enabled():
                hist.record(uiapp, doc, view)
            view_entry = hist.view_entry(uiapp, doc, view)
        except Exception:
            view_entry = None
    if mode == MODE_SAVE and view_entry is None:
        ui.alert('Open a 3D view with its section box on, then click Save Box.')
        return

    chosen = HistoryBar(uiapp, uidoc, doc, view_entry, mode).show()
    try:
        if chosen is not None:
            kind, item = chosen
            if kind == MODE_SAVED:
                hist.load_saved_box(uidoc, item)
            else:
                hist.go_to(uidoc, item)
    except Exception as ex:
        ui.alert('Could not go to that section box.\n\n{}'.format(ex))
    finally:
        # boxes unpinned while the window was open leave the list now
        try:
            hist.tidy(doc)
        except Exception:
            pass


def _view_rect(uiapp, uidoc):
    try:
        uiview = hist.find_uiview(uidoc, uidoc.ActiveView)
        if uiview is not None:
            r = uiview.GetWindowRectangle()
            if r.Right - r.Left > 200 and r.Bottom - r.Top > 150:
                return r
    except Exception:
        pass
    return uiapp.MainWindowExtents


def _bitmap(path, decode_width=0):
    """Loaded fully into memory so the file is never locked. Thumbnails are
    decoded small, which keeps opening the window quick."""
    if not path:
        return None
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.CreateOptions = BitmapCreateOptions.IgnoreImageCache
        if decode_width:
            bmp.DecodePixelWidth = int(decode_width)
        bmp.UriSource = Uri(path)
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def _natural_key(name):
    """'Box 2' before 'Box 10'."""
    parts = re.split(r'(\d+)', (name or '').lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _age_label(steps_back):
    if steps_back == 0:
        return 'Current'
    if steps_back == 1:
        return 'Previous'
    return '{} boxes ago'.format(steps_back)


class HistoryBar(object):
    def __init__(self, uiapp, uidoc, doc, view_entry, mode):
        self.uiapp = uiapp
        self.uidoc = uidoc
        self.doc = doc
        self.view_entry = view_entry
        self.mode = mode
        self.colors = ui.palette()
        self.chosen = None
        self.closing = False
        self.loaded = False
        self.focus_name = False
        self.name_action = None
        self.close_after_name = (mode == MODE_SAVE)
        self.thumbs = {}
        self.fulls = {}
        self.session_unpinned = set()
        self.entries = hist.load(doc)
        self.saved = None            # loaded when the Saved tab first opens

        self.win = ui.load_window(XAML_FILE, self.colors)
        for name in ('Overlay', 'CanvasArea', 'Bar', 'Tiles', 'Preview', 'PreviewImage',
                     'PreviewLabel', 'RecordCheck', 'SaveButton', 'StatusText', 'HintText',
                     'CloseButton', 'TabRecent', 'TabSaved', 'NameRow', 'NameLabel', 'NameBox',
                     'NameOk', 'NameCancel', 'SavedPanel', 'SearchBox', 'SearchHint',
                     'SavedScroll', 'SavedTiles', 'SavedEmpty'):
            setattr(self, name, self.win.FindName(name))

        self._place()
        self._build_recent()
        self._header()

        self.Tiles.MouseLeave += self._hide_preview
        self.SavedScroll.MouseLeave += self._hide_preview
        self.win.KeyDown += self._on_key
        self.win.MouseDown += self._on_mouse_down
        self.win.Deactivated += lambda s, e: self._close()
        self.win.Loaded += self._on_loaded
        self.CloseButton.Click += lambda s, e: self._close()
        self.SaveButton.Click += lambda s, e: self._save_current()
        self.TabRecent.Checked += lambda s, e: self._show_tab(False)
        self.TabSaved.Checked += lambda s, e: self._show_tab(True)
        self.NameOk.Click += lambda s, e: self._name_ok()
        self.NameCancel.Click += lambda s, e: self._name_cancel()
        self.NameBox.KeyDown += self._on_name_key
        self.SearchBox.TextChanged += lambda s, e: self._on_search()

        if mode in (MODE_SAVED, MODE_SAVE):
            self.TabSaved.IsChecked = True
        else:
            self.TabRecent.IsChecked = True
        if mode == MODE_SAVE:
            self._ask_name('Save current box as', hist.next_saved_name(doc),
                           self._save_view_entry)

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _place(self):
        """Cover the Revit window (and the view, if it floats outside it);
        CanvasArea = the view's rectangle inside the window."""
        sx, sy = ui.attach(self.win, self.uiapp.MainWindowHandle)
        main = self.uiapp.MainWindowExtents
        view = _view_rect(self.uiapp, self.uidoc)
        left, top = min(main.Left, view.Left), min(main.Top, view.Top)
        right, bottom = max(main.Right, view.Right), max(main.Bottom, view.Bottom)
        self.win.Left = left * sx
        self.win.Top = top * sy
        self.win.Width = (right - left) * sx
        self.win.Height = (bottom - top) * sy
        self.CanvasArea.Margin = Thickness((view.Left - left) * sx, (view.Top - top) * sy,
                                           (right - view.Right) * sx, (bottom - view.Bottom) * sy)

        cw = max(400, (view.Right - view.Left) * sx)
        self.canvas_scale = sx
        aspect = (view.Bottom - view.Top) / float(max(1, view.Right - view.Left))
        self.aspect = min(0.75, max(0.42, aspect))
        # tile size of the plain 4-tile bar; pinned tiles make the bar longer
        # and only shrink the tiles once it would leave the view
        bar = max(min(cw * BAR_SHARE, BAR_MAX), min(BAR_MIN, cw - 24))
        self.std_tile = (bar - BAR_PAD - GAP * (RECENT_SLOTS - 1)) / float(RECENT_SLOTS)
        self.max_inner = cw - 24 - BAR_PAD

    def _size_for(self, tiles, divider):
        extra = (DIVIDER + GAP) if divider else 0
        gaps = GAP * (tiles - 1) + extra
        tile = self.std_tile
        if tiles * tile + gaps > self.max_inner:
            tile = (self.max_inner - gaps) / float(tiles)
        self.tile_width = tile
        self.image_width = tile - TILE_PAD
        self.image_height = round(self.image_width * self.aspect)
        self.bar_width = tiles * tile + gaps + BAR_PAD
        self.Bar.Width = self.bar_width
        self.Preview.Width = self.bar_width
        # pin button scales with the snapshot
        self.pin_size = max(16, min(26, int(round(self.image_width * 0.13))))
        self.pin_font = max(8, int(round(self.pin_size * 0.46)))
        self.pin_margin = 8 + int(round(self.pin_size * 0.25))

    def _fit_preview(self):
        """The preview may use the rest of the view under the bar."""
        try:
            self.win.UpdateLayout()
            bottom = self.Bar.TranslatePoint(Point(0, self.Bar.ActualHeight), self.CanvasArea).Y
            room = self.CanvasArea.ActualHeight - bottom - 8 - 16 - 12
            self.PreviewImage.MaxHeight = max(120, room)
            self.PreviewImage.MaxWidth = self.bar_width - 16
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Recent tab
    # ------------------------------------------------------------------
    def _left_group(self, entry):
        return hist.is_pinned(entry) or entry['id'] in self.session_unpinned

    def _build_recent(self):
        self.Tiles.Children.Clear()
        self.Tiles.ColumnDefinitions.Clear()

        total = len(self.entries)
        steps = dict((e['id'], total - 1 - i) for i, e in enumerate(self.entries))
        left = [e for e in self.entries if self._left_group(e)]
        recent = [e for e in self.entries if not self._left_group(e)][-RECENT_SLOTS:]

        # left to right: pinned, divider, empty slots, recent (current last)
        cells = [('tile', e) for e in left]
        if left:
            cells.append(('divider', None))
        cells.extend([('empty', None)] * (RECENT_SLOTS - len(recent)))
        cells.extend([('tile', e) for e in recent])

        self._size_for(len(left) + RECENT_SLOTS, bool(left))

        col = 0
        for i, (kind, entry) in enumerate(cells):
            if i:
                self._add_column(GAP)
                col += 1
            if kind == 'divider':
                self._add_column(DIVIDER)
                cell = self._divider()
            elif kind == 'empty':
                self._add_column(self.tile_width)
                cell = self._empty_tile()
            else:
                self._add_column(self.tile_width)
                cell = self._recent_tile(entry, steps[entry['id']])
            Grid.SetColumn(cell, col)
            self.Tiles.Children.Add(cell)
            col += 1

    def _add_column(self, width):
        c = ColumnDefinition()
        c.Width = GridLength(width)
        self.Tiles.ColumnDefinitions.Add(c)

    def _recent_tile(self, entry, steps_back):
        pinned = hist.is_pinned(entry)
        path = hist.image_path(self.doc, entry)
        label = _age_label(steps_back) + (DOT + 'Pinned' if pinned else '')
        info = DOT.join(x for x in (entry.get('view_name', ''), hist.time_text(entry),
                                    hist.box_size_text(entry)) if x)
        preview = DOT.join(x for x in (_age_label(steps_back), 'Pinned' if pinned else '',
                                       entry.get('view_name', ''), hist.time_text(entry),
                                       hist.box_size_text(entry)) if x)
        cell, btn = self._tile(path, label, steps_back == 0, info, preview)
        if steps_back == 0:
            btn.BorderBrush = ui.brush(self.colors['ACCENT'])
        btn.Click += lambda s, e: self._choose(MODE_RECENT, entry)

        # pin button over the snapshot's top-right corner: always shown when
        # pinned, otherwise only while the tile is hovered
        pin = Button()
        pin.Style = self.win.FindResource('Pin')
        pin.Width = pin.Height = self.pin_size
        pin.FontSize = self.pin_font
        pin.HorizontalAlignment = HorizontalAlignment.Right
        pin.VerticalAlignment = VerticalAlignment.Top
        pin.Margin = Thickness(0, self.pin_margin, self.pin_margin, 0)
        if pinned:
            pin.Content = G_PINNED
            pin.Background = ui.brush(self.colors['ACCENT'])
            pin.ToolTip = 'Unpin'
        else:
            pin.Content = G_PIN
            pin.ToolTip = 'Pin: keep this box, it never drops off the list'
            pin.Opacity = 0.0
        pin.Click += lambda s, e: self._toggle_pin(entry)
        cell.Children.Add(pin)
        cell.MouseEnter += lambda s, e: self._pin_hover(pin, True, pinned)
        cell.MouseLeave += lambda s, e: self._pin_hover(pin, False, pinned)

        full = len([e for e in self.entries if hist.is_pinned(e)]) >= hist.MAX_PINNED
        if pinned:
            pin_item = (G_UNPIN, 'Unpin', lambda: self._toggle_pin(entry), True)
        elif full:
            pin_item = (G_PIN, 'Pin ({} pinned already)'.format(hist.MAX_PINNED), None, False)
        else:
            pin_item = (G_PIN, 'Pin', lambda: self._toggle_pin(entry), True)
        cell.ContextMenu = self._menu([
            (G_GO, 'Go to this box', lambda: self._choose(MODE_RECENT, entry), True),
            None,
            pin_item,
            (G_SAVE, u'Save to list\u2026', lambda: self._ask_name(
                'Save box as', hist.next_saved_name(self.doc),
                lambda name: self._save_entry(entry, name)), True),
        ])
        return cell

    def _tile(self, path, label_text, accent, info_text, preview_text, img_w=None, img_h=None):
        """A snapshot tile: (cell grid, button). Hover shows the preview."""
        c = self.colors
        img_w = img_w or self.image_width
        img_h = img_h or self.image_height
        key = path or ''
        if key not in self.thumbs:
            self.thumbs[key] = _bitmap(path, img_w * 2)
        bmp = self.thumbs[key]

        frame = Border()
        frame.Width = img_w
        frame.Height = img_h
        frame.Background = ui.brush(c['IMGBG'])
        frame.CornerRadius = CornerRadius(6)
        if bmp is not None:
            img = Image()
            img.Source = bmp
            img.Stretch = Stretch.UniformToFill
            img.HorizontalAlignment = HorizontalAlignment.Center
            img.VerticalAlignment = VerticalAlignment.Center
            frame.Child = img
            frame.ClipToBounds = True
            frame.Clip = RectangleGeometry(Rect(0, 0, img_w, img_h), 6, 6)
        else:
            frame.Child = self._center_text('No snapshot')

        label = TextBlock()
        label.Text = label_text
        label.FontSize = 12
        label.FontWeight = FontWeights.SemiBold
        label.Foreground = ui.brush(c['ACCENT'] if accent else c['FG'])
        label.Margin = Thickness(2, 7, 2, 0)
        label.TextTrimming = TextTrimming.CharacterEllipsis

        info = TextBlock()
        info.Text = info_text
        info.FontSize = 11
        info.Foreground = ui.brush(c['FG2'])
        info.TextTrimming = TextTrimming.CharacterEllipsis
        info.Margin = Thickness(2, 1, 2, 0)
        info.ToolTip = info_text

        stack = StackPanel()
        stack.Children.Add(frame)
        stack.Children.Add(label)
        stack.Children.Add(info)

        btn = Button()
        btn.Style = self.win.FindResource('Tile')
        btn.Content = stack

        cell = Grid()
        cell.Children.Add(btn)
        cell.MouseEnter += lambda s, e: self._show_preview(path, preview_text)
        return cell, btn

    def _empty_tile(self):
        frame = Border()
        frame.MinHeight = self.image_height + TILE_TEXT
        frame.Background = ui.brush(self.colors['TILE'])
        frame.CornerRadius = CornerRadius(9)
        frame.Opacity = 0.55
        frame.Child = self._center_text('Empty')
        return frame

    def _divider(self):
        line = Border()
        line.Width = 1
        line.HorizontalAlignment = HorizontalAlignment.Center
        line.Margin = Thickness(0, 8, 0, 8)
        line.Background = ui.brush(self.colors['FG2'])
        line.Opacity = 0.35
        line.ToolTip = 'Pinned boxes on the left'
        return line

    def _center_text(self, text):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = 12
        tb.Foreground = ui.brush(self.colors['FG2'])
        tb.HorizontalAlignment = HorizontalAlignment.Center
        tb.VerticalAlignment = VerticalAlignment.Center
        return tb

    def _menu(self, items):
        """Right-click menu. items: (glyph, text, callback, enabled) or None
        for a separator line."""
        menu = ContextMenu()
        menu.Style = self.win.FindResource('Menu')
        for item in items:
            if item is None:
                sep = Separator()
                sep.Style = self.win.FindResource('MenuSep')
                menu.Items.Add(sep)
                continue
            glyph, text, callback, enabled = item
            mi = MenuItem()
            mi.Style = self.win.FindResource('MenuItem')
            mi.Header = text
            mi.Tag = glyph
            mi.IsEnabled = bool(enabled and callback)
            if callback is not None:
                mi.Click += self._menu_handler(callback)
            menu.Items.Add(mi)
        return menu

    def _menu_handler(self, callback):
        @ui.guard
        def handler(sender, args):
            if self.closing:
                return
            callback()
        return handler

    # ------------------------------------------------------------------
    # Saved tab
    # ------------------------------------------------------------------
    def _saved_items(self):
        if self.saved is None:
            self.saved = sorted(hist.load_saved(self.doc), key=lambda i: _natural_key(i['name']))
        return self.saved

    def _reload_saved(self):
        self.saved = None
        self._update_saved_tab_label()
        if self.TabSaved.IsChecked:
            self._build_saved()

    def _update_saved_tab_label(self):
        n = len(self._saved_items())
        self.TabSaved.Content = 'Saved ({})'.format(n) if n else 'Saved'

    def _build_saved(self):
        items = self._saved_items()
        query = (self.SearchBox.Text or '').strip().lower()
        shown = [i for i in items if query in i['name'].lower()]

        self.SavedTiles.Children.Clear()
        # as many columns as the Recent row, a little narrower so the row
        # plus the scroll bar fits the bar exactly
        inner = self.bar_width - BAR_PAD
        per_row = max(1, int((inner + GAP) // (self.tile_width + GAP)))
        tile = (inner - SCROLL_W - GAP * (per_row - 1)) / float(per_row)
        img_w = tile - TILE_PAD
        img_h = round(img_w * self.aspect)
        self.SavedTiles.Width = per_row * (tile + GAP)
        # two and a half rows: the cut-off row shows there is more to scroll
        self.SavedScroll.MaxHeight = 2.5 * (img_h + TILE_TEXT + GAP)
        for item in shown:
            cell = self._saved_tile(item, img_w, img_h)
            cell.Width = tile
            cell.Margin = Thickness(0, 0, GAP, GAP)
            self.SavedTiles.Children.Add(cell)

        if not items:
            self.SavedEmpty.Text = (u'No saved boxes yet.\nUse \u201cSave current box\u201d, or '
                                    u'right-click a recent box > Save to list.')
        elif not shown:
            self.SavedEmpty.Text = u'No saved box matches \u201c{}\u201d.'.format(query)
        self.SavedEmpty.Visibility = Visibility.Collapsed if shown else Visibility.Visible

    def _saved_tile(self, item, img_w, img_h):
        path = hist.saved_image_path(self.doc, item)
        info = DOT.join(x for x in (item.get('view_name', ''), hist.time_text(item),
                                    hist.box_size_text(item)) if x)
        preview = DOT.join(x for x in (item['name'], item.get('view_name', ''),
                                       hist.time_text(item), hist.box_size_text(item)) if x)
        cell, btn = self._tile(path, item['name'], False, info, preview, img_w, img_h)
        btn.Click += lambda s, e: self._choose(MODE_SAVED, item)
        cell.ContextMenu = self._menu([
            (G_GO, 'Load (make current)', lambda: self._choose(MODE_SAVED, item), True),
            (G_RENAME, u'Rename\u2026', lambda: self._ask_name(
                'Rename to', item['name'],
                lambda name: self._rename_saved(item, name)), True),
            None,
            (G_DELETE, 'Delete', lambda: self._delete_saved(item), True),
        ])
        return cell

    @ui.guard
    def _on_search(self):
        if self.closing:
            return
        self.SearchHint.Visibility = (Visibility.Collapsed if self.SearchBox.Text
                                      else Visibility.Visible)
        self._build_saved()

    def _save_entry(self, entry, name):
        hist.add_saved(self.doc, entry, name, image_src=hist.image_path(self.doc, entry))
        self._reload_saved()
        self._status(u'Saved as \u201c{}\u201d'.format(name.strip()))

    def _save_view_entry(self, name):
        hist.add_saved(self.doc, self.view_entry, name)
        self._reload_saved()
        self._status(u'Saved as \u201c{}\u201d'.format(name.strip()))

    def _rename_saved(self, item, name):
        hist.rename_saved(self.doc, item['id'], name)
        self._reload_saved()

    def _delete_saved(self, item):
        hist.delete_saved(self.doc, item['id'])
        self._reload_saved()
        self._status(u'Deleted \u201c{}\u201d'.format(item['name']))

    # ------------------------------------------------------------------
    # header, tabs, name editor
    # ------------------------------------------------------------------
    def _header(self):
        self.RecordCheck.IsChecked = hist.is_enabled()
        self.RecordCheck.Checked += lambda s, e: self._set_recording(True)
        self.RecordCheck.Unchecked += lambda s, e: self._set_recording(False)
        if self.view_entry is None:
            self.SaveButton.IsEnabled = False
            self.SaveButton.ToolTip = 'Open a 3D view with its section box on to save it'
        self._update_saved_tab_label()
        if not hist.recorder_running():
            error = hist.recorder_error().strip().splitlines()
            self._status('Recorder not running: reload pyRevit', warn=True,
                         tip=error[-1] if error else 'Boxes are only recorded when you open this window.')

    def _status(self, text, warn=False, tip=None):
        self.StatusText.Text = text
        self.StatusText.ToolTip = tip
        self.StatusText.Foreground = ui.brush(self.colors['WARN' if warn else 'FG2'])
        self.StatusText.Visibility = Visibility.Visible

    @ui.guard
    def _show_tab(self, saved):
        if self.closing:
            return
        self.Preview.Visibility = Visibility.Collapsed
        # no usage hints in the header; it only speaks up when there is nothing to show
        if saved:
            self.Tiles.Visibility = Visibility.Collapsed
            self.SavedPanel.Visibility = Visibility.Visible
            self.HintText.Text = ''
            self._build_saved()
        else:
            self.SavedPanel.Visibility = Visibility.Collapsed
            self.Tiles.Visibility = Visibility.Visible
            self.HintText.Text = ('' if self.entries else
                                  'No section boxes recorded in this model yet. '
                                  'Make or change one and it shows up here.')
        self.HintText.Visibility = Visibility.Visible if self.HintText.Text else Visibility.Collapsed
        if self.loaded:
            self._fit_preview()

    @ui.guard
    def _save_current(self):
        if self.closing:
            return
        if self.view_entry is None:
            self._status('Open a 3D view with its section box on to save it', warn=True)
            return
        self._ask_name('Save current box as', hist.next_saved_name(self.doc), self._save_view_entry)

    @ui.guard
    def _ask_name(self, label, default, action):
        if self.closing:
            return
        self.name_action = action
        self.NameLabel.Text = label
        self.NameBox.Text = default
        self.NameRow.Visibility = Visibility.Visible
        if self.loaded:
            self._focus_name_box()
            self._fit_preview()
        else:
            self.focus_name = True

    def _focus_name_box(self):
        self.NameBox.Focus()
        Keyboard.Focus(self.NameBox)
        self.NameBox.SelectAll()

    @ui.guard
    def _name_ok(self):
        if self.closing or self.name_action is None:
            return
        try:
            self.name_action(self.NameBox.Text)
        except Exception as ex:
            self._status(str(ex), warn=True)
            self._focus_name_box()
            return
        self._hide_name()
        if self.close_after_name:
            self._close()

    @ui.guard
    def _name_cancel(self):
        if self.closing:
            return
        self._hide_name()
        if self.close_after_name:
            self._close()

    def _hide_name(self):
        self.name_action = None
        self.NameRow.Visibility = Visibility.Collapsed
        if self.loaded:
            self._fit_preview()

    @ui.guard
    def _on_name_key(self, sender, args):
        if self.closing:
            return
        if args.Key in (Key.Enter, Key.Return):
            args.Handled = True
            self._name_ok()

    # ------------------------------------------------------------------
    # hover / click / pin
    # ------------------------------------------------------------------
    @ui.guard
    def _pin_hover(self, pin, inside, pinned):
        if self.closing:
            return
        pin.Opacity = 1.0 if (inside or pinned) else 0.0

    @ui.guard
    def _show_preview(self, path, text):
        if self.closing:
            return
        if not path:
            self.Preview.Visibility = Visibility.Collapsed
            return
        if path not in self.fulls:
            self.fulls[path] = _bitmap(path)
        bmp = self.fulls[path]
        if bmp is None:
            self.Preview.Visibility = Visibility.Collapsed
            return
        self.PreviewImage.Source = bmp
        self.PreviewLabel.Text = text
        self.Preview.Visibility = Visibility.Visible

    @ui.guard
    def _hide_preview(self, sender=None, args=None):
        if self.closing:
            return
        self.Preview.Visibility = Visibility.Collapsed

    @ui.guard
    def _toggle_pin(self, entry):
        """Pin or unpin without closing the window. A box unpinned here stays
        where it is (so it can be pinned again) until the window closes."""
        if self.closing:
            return
        was_pinned = hist.is_pinned(entry)
        problem = hist.set_pinned(self.doc, entry['id'], not was_pinned)
        if problem:
            self._status(problem, warn=True)
            return
        if was_pinned:
            self.session_unpinned.add(entry['id'])
        else:
            self.session_unpinned.discard(entry['id'])
        self.entries = hist.load(self.doc)
        self.Preview.Visibility = Visibility.Collapsed
        self._build_recent()
        if self.loaded:
            self._fit_preview()

    @ui.guard
    def _set_recording(self, state):
        if self.closing:
            return
        hist.set_enabled(state)

    @ui.guard
    def _choose(self, kind, item):
        if self.closing:
            return
        self.chosen = (kind, item)
        self._close()

    @ui.guard
    def _on_key(self, sender, args):
        if self.closing:
            return
        if args.Key == Key.Escape:
            args.Handled = True
            if self.NameRow.Visibility == Visibility.Visible and not self.close_after_name:
                self._hide_name()
            else:
                self._close()

    @ui.guard
    def _on_mouse_down(self, sender, args):
        # a click anywhere outside the bar (view, ribbon, browser...) closes it
        if self.closing:
            return
        try:
            # ignore clicks that come from the right-click menu (its own popup)
            source = PresentationSource.FromDependencyObject(args.OriginalSource)
            if source is None or not source.RootVisual.Equals(self.win):
                return
        except Exception:
            return
        if not self.Bar.IsMouseOver:
            self._close()

    @ui.guard
    def _on_loaded(self, sender, args):
        if self.closing:
            return
        self.loaded = True
        self._fit_preview()
        anim = DoubleAnimation(0.0, 1.0, Duration(TimeSpan.FromMilliseconds(90)))
        self.win.BeginAnimation(UIElement.OpacityProperty, anim)
        # no Activate() here: it throws if Loaded fires before the window is shown
        if self.focus_name:
            self.focus_name = False
            self._focus_name_box()

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
        return self.chosen
