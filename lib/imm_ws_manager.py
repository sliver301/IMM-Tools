# -*- coding: utf-8 -*-
"""IMM Worksets: the Workset Manager window (modal).

Layout: a sidebar with three pages (Worksets, Category mapping, Activity)
and the model status, and on each page a list on the left with a details
panel on the right that only shows what you can do with the selection.
"""
import os
import copy
import json

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
from System.Windows import FontWeights, Visibility
from System.Windows.Input import Cursors, Key, Mouse
from System.Windows.Media import BrushConverter, VisualTreeHelper
from System.Windows.Controls.Primitives import ScrollBar

from Autodesk.Revit.DB import FilteredElementCollector, ElementWorksetFilter, WorksetId
from Autodesk.Revit.DB import WorksharingUtils

from pyrevit import forms

import imm_ws_common as common
import imm_ws_core as core
import imm_ws_store as store

XAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'imm_ws_manager.xaml')

VISIBLE = Visibility.Visible
HIDDEN = Visibility.Collapsed

DARK_BRUSHES = {
    'Bg': '#1E2228', 'Side': '#181B20', 'Card': '#2B2F36', 'Line': '#3D434C',
    'Fg': '#F0F3F6', 'Fg2': '#B3BCC6', 'Accent': '#4C8DFF', 'AccentSoft': '#24324A',
    'Hover': '#353B44', 'Select': '#2F4466', 'WarnBg': '#3A2A12', 'WarnLine': '#B7791F',
    'WarnFg': '#F6D9A8', 'WarnButton': '#E8590C', 'Danger': '#FF8A80',
}

# claim chip colours (background, text)
CHIP_LIGHT = {
    store.STATUS_MINE: ('#E6F4EA', '#1F7A43'),
    store.STATUS_SHARED: ('#E8F0FE', '#1F4FB8'),
    store.STATUS_OTHERS: ('#FDECEC', '#B42318'),
    store.STATUS_FREE: ('#F0F2F5', '#8C959F'),
}
CHIP_DARK = {
    store.STATUS_MINE: ('#1E3A2A', '#7EE2A8'),
    store.STATUS_SHARED: ('#22324D', '#9EC2FF'),
    store.STATUS_OTHERS: ('#4A2224', '#FFA8A8'),
    store.STATUS_FREE: ('#33383F', '#8C959F'),
}
# mapping status dots
DOTS = {'mine': '#1F9D55', 'adopted': '#2F6FEB', 'conflict': '#E8590C',
        'needed': '#E8590C', 'none': '#D0D5DB', 'never': '#A0A8B0'}

PAGES = [
    ('Worksets',
     'Every user workset in this model. Select one to make it active, check it out, '
     'claim it, rename or delete it.'),
    ('Category mapping',
     'Tell the plugin which workset each category belongs to. When you place or paste an '
     'element, the live watcher puts it on that workset for you.'),
    ('Activity',
     'Elements the watcher moved for you, and what teammates did on the worksets you claimed.'),
]

FILTERS = ['Used in this model', 'Needs a workset', 'All categories', 'Mapped',
           'From teammates', 'Conflicts', 'Has a suggestion', 'Never moved']
TEMPLATE_FORMAT = 'IMM worksets mapping'


class Row(object):
    pass


class ManagerWindow(forms.WPFWindow):
    def __init__(self, uiapp, start_tab=0):
        try:
            # our own Esc handling: clear the selection first, close last
            forms.WPFWindow.__init__(self, XAML, handle_esc=False)
        except TypeError:
            forms.WPFWindow.__init__(self, XAML)
        self.uiapp = uiapp
        self.doc = uiapp.ActiveUIDocument.Document
        self.me = common.username(self.doc)
        self.dark = common.is_dark_theme()
        self.conv = BrushConverter()
        self._brushes = {}
        self._apply_theme()
        self.dirty = False
        self.allow_close = False
        self.filling = False
        self.proposals = {}
        self.map_offset = 0
        self.types_by_cat, self.types = {}, {}
        self.bar_actions = {}
        self.categories = {}
        self.counts = {}
        self.ws_rows = []
        self.all_ws_rows = []
        self.cat_rows = []
        self.effective, self.sources, self.conflicts, self.claims = {}, {}, {}, {}
        self.work = store.empty_record(self.me)

        self._wire()
        self.filling = True
        self.cbFilter.ItemsSource = FILTERS
        self.cbFilter.SelectedIndex = 0
        self.cbDiscipline.ItemsSource = ['All disciplines'] + core.DISCIPLINES
        self.cbDiscipline.SelectedIndex = 0
        self.filling = False

        if not common.eligible(self.doc):
            self._header()
            self.show_page(0)
            self._disable_all()
            self.bar('This model is not workshared, so there are no worksets to manage. '
                     'Open a central model or a local copy of one.')
            return

        self._busy(True)
        try:
            self.categories = core.mappable_categories(self.doc)
            self.counts = core.category_counts(self.doc, self.categories)
            self.types_by_cat, self.types = core.type_inventory(self.doc, self.categories, self.counts)
            self.reload_model_data()
            self.refresh_all()
        finally:
            self._busy(False)
        self.show_page(start_tab)
        self._startup_bars()

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _apply_theme(self):
        if not self.dark:
            return
        for key, value in DARK_BRUSHES.items():
            self.Resources[key] = self.conv.ConvertFromString(value)

    def brush(self, hex_color):
        b = self._brushes.get(hex_color)
        if b is None:
            b = self.conv.ConvertFromString(hex_color)
            try:
                b.Freeze()
            except Exception:
                pass
            self._brushes[hex_color] = b
        return b

    def _wire(self):
        pairs = [
            ('btnNew', self.on_new), ('btnRename', self.on_rename), ('btnDelete', self.on_delete),
            ('btnActive', self.on_set_active), ('btnEditable', self.on_editable),
            ('btnSync', self.on_sync), ('btnRelinquish', self.on_relinquish),
            ('btnClaim', self.on_claim), ('btnShare', self.on_share), ('btnUnclaim', self.on_unclaim),
            ('btnRefresh', self.on_refresh), ('btnNameOk', self.on_name_ok),
            ('btnNameCancel', self.on_name_cancel),
            ('btnAuto', self.on_auto),
            ('btnApplyProposals', self.on_apply_proposals), ('btnAcceptSuggest', self.on_accept_one),
            ('btnImport', self.on_import), ('btnExport', self.on_export),
            ('btnClearMap', self.on_clear_map),
            ('btnKeepMine', self.on_keep_mine), ('btnUseTheirs', self.on_use_theirs),
            ('btnSaveMap', self.on_save_map), ('btnRevertMap', self.on_revert_map),
            ('btnActRefresh', self.on_act_refresh), ('btnScan', self.on_scan),
            ('btnActClear', self.on_act_clear), ('btnClose', self.on_close),
            ('btnWarnYes', self.on_bar_yes), ('btnWarnAlt', self.on_bar_alt),
            ('btnWarnNo', self.on_bar_no),
        ]
        for name, handler in pairs:
            getattr(self, name).Click += handler
        self.navWs.Checked += lambda s, e: self.show_page(0)
        self.navMap.Checked += lambda s, e: self.show_page(1)
        self.navAct.Checked += lambda s, e: self.show_page(2)
        self.tbWsSearch.TextChanged += self.on_ws_search
        self.btnWsClear.Click += lambda s, e: self._clear_box(self.tbWsSearch)
        self.btnMapClear.Click += lambda s, e: self._clear_box(self.tbSearch)
        self.PreviewKeyDown += self.on_key
        self.Loaded += lambda s, e: self._theme_scrollbars()
        self.gridWs.SelectionChanged += lambda s, e: self.update_ws_detail()
        self.tbSearch.TextChanged += self.on_map_search
        self.cbFilter.SelectionChanged += lambda s, e: self._refill_map()
        self.cbDiscipline.SelectionChanged += lambda s, e: self._refill_map()
        self.chkTypes.Click += lambda s, e: self._refill_map()
        self.gridMap.SelectionChanged += lambda s, e: self.update_cat_detail()
        self.cbMapTo.SelectionChanged += self.on_map_to_changed
        self.chkNever.Click += self.on_never_clicked
        self.chkDeleteElements.Checked += lambda s, e: self._move_enabled(False)
        self.chkDeleteElements.Unchecked += lambda s, e: self._move_enabled(True)
        self.tbName.KeyDown += self.on_name_key
        self.Closing += self.on_closing

    def _disable_all(self):
        for name in ('btnNew', 'btnSync', 'btnRelinquish', 'btnAuto', 'btnImport',
                     'btnExport', 'btnSaveMap', 'btnRevertMap', 'btnScan', 'navMap'):
            getattr(self, name).IsEnabled = False

    def _busy(self, on):
        Mouse.OverrideCursor = Cursors.Wait if on else None

    def status(self, text):
        self.txtStatus.Text = text or ''

    # ------------------------------------------------------------------
    # search boxes and keyboard
    # ------------------------------------------------------------------
    def _search_chrome(self, box, placeholder, clear):
        empty = not (box.Text or '')
        placeholder.Visibility = VISIBLE if empty else HIDDEN
        clear.Visibility = HIDDEN if empty else VISIBLE

    def on_ws_search(self, sender, args):
        self._search_chrome(self.tbWsSearch, self.phWs, self.btnWsClear)
        self.fill_ws_grid()

    def on_map_search(self, sender, args):
        self._search_chrome(self.tbSearch, self.phMap, self.btnMapClear)
        self._refill_map()

    def _clear_box(self, box):
        box.Text = ''
        box.Focus()

    def _theme_scrollbars(self):
        """pyRevit's own theme restyles scroll bars inside lists; put ours back."""
        try:
            style = self.Resources[clr.GetClrType(ScrollBar)]
        except Exception:
            return
        stack = [self]
        while stack:
            node = stack.pop()
            if isinstance(node, ScrollBar) and node.Style is not style:
                node.Style = style
            try:
                for i in range(VisualTreeHelper.GetChildrenCount(node)):
                    stack.append(VisualTreeHelper.GetChild(node, i))
            except Exception:
                pass

    def _page(self):
        if self.pageMap.Visibility == VISIBLE:
            return 1
        if self.pageAct.Visibility == VISIBLE:
            return 2
        return 0

    def on_key(self, sender, args):
        """Esc: the first press unselects whatever is selected, the next
        press closes the window. With nothing selected, Esc closes."""
        if args.Key != Key.Escape:
            return
        for combo in (self.cbFilter, self.cbDiscipline, self.cbMapTo, self.cbMoveTo):
            if combo.IsDropDownOpen:
                return
        args.Handled = True
        page = self._page()
        if self.pnlName.Visibility == VISIBLE:
            self.pnlName.Visibility = HIDDEN
            return
        grid = (self.gridWs, self.gridMap, self.gridAct)[page]
        if grid.SelectedItems.Count:
            grid.UnselectAll()
            return
        self.Close()

    # ------------------------------------------------------------------
    # pages
    # ------------------------------------------------------------------
    def show_page(self, index):
        index = max(0, min(2, int(index or 0)))
        pages = (self.pageWs, self.pageMap, self.pageAct)
        navs = (self.navWs, self.navMap, self.navAct)
        for i, page in enumerate(pages):
            page.Visibility = VISIBLE if i == index else HIDDEN
        if not navs[index].IsChecked:
            navs[index].IsChecked = True
        try:
            self.UpdateLayout()
            self._theme_scrollbars()
        except Exception:
            pass
        title, hint = PAGES[index]
        self.txtPageTitle.Text = title
        self.txtPageHint.Text = hint

    # ------------------------------------------------------------------
    # message bar
    # ------------------------------------------------------------------
    def bar(self, text, yes=None, yes_text='OK', alt=None, alt_text=None,
            no_text='Dismiss', extra=False):
        self.txtWarn.Text = text
        self.bar_actions = {'yes': yes, 'alt': alt}
        self.btnWarnYes.Content = yes_text
        self.btnWarnYes.Visibility = VISIBLE if yes else HIDDEN
        self.btnWarnAlt.Content = alt_text or ''
        self.btnWarnAlt.Visibility = VISIBLE if alt else HIDDEN
        self.btnWarnNo.Content = no_text
        self.pnlWarnExtra.Visibility = VISIBLE if extra else HIDDEN
        self.barWarn.Visibility = VISIBLE

    def hide_bar(self):
        self.barWarn.Visibility = HIDDEN
        self.pnlWarnExtra.Visibility = HIDDEN
        self.bar_actions = {}

    def on_bar_yes(self, sender, args):
        action = self.bar_actions.get('yes')
        self.hide_bar()
        if action:
            self._safe(action)

    def on_bar_alt(self, sender, args):
        action = self.bar_actions.get('alt')
        self.hide_bar()
        if action:
            self._safe(action)

    def on_bar_no(self, sender, args):
        self.hide_bar()

    def _safe(self, func, *a):
        self._busy(True)
        try:
            return func(*a)
        except Exception as ex:
            self.bar(str(ex).strip() or 'Something went wrong.')
        finally:
            self._busy(False)

    def _startup_bars(self):
        if not common.watcher_running():
            error = common.watcher_error().strip().splitlines()
            reason = error[-1] if error else 'it did not start in this Revit session'
            self.bar('The live watcher is not running ({}). Close and reopen Revit to start it. '
                     'Everything in this window still works.'.format(reason))
            return
        open_conflicts = [c for c, info in self.conflicts.items() if info.get('new')]
        if open_conflicts:
            self.bar('{} categories are mapped to a different workset by a teammate. '
                     'Decide which one to keep.'.format(len(open_conflicts)),
                     yes=self._show_conflicts, yes_text='Show me')
            return
        if not self.effective and self._needs_workset():
            self.bar('No categories are mapped yet, so the watcher has nothing to do. '
                     'Start on the Category mapping page; it can suggest a mapping for you.',
                     yes=self._show_mapping, yes_text='Open Category mapping')

    def _show_conflicts(self):
        self.show_page(1)
        self.cbFilter.SelectedIndex = FILTERS.index('Conflicts')

    def _show_mapping(self):
        self.show_page(1)

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def reload_model_data(self):
        self.records = store.read_all(self.doc)
        mine = self.records.get(self.me) or store.empty_record(self.me)
        self.saved = copy.deepcopy(mine)
        self.work = copy.deepcopy(mine)
        self.dirty = False
        self.recompute()

    def recompute(self):
        records = dict(self.records)
        records[self.me] = self.work
        effective, sources, conflicts = store.merge_mappings(records, self.me)
        self.effective = effective
        self.sources = sources
        self.conflicts = conflicts
        self.claims = store.claim_table(records)

    def refresh_all(self):
        self._header()
        self.fill_ws_grid()
        self.fill_map_grid()
        self.fill_activity()

    def _header(self):
        doc = self.doc
        kind = 'cloud model' if common.is_cloud(doc) else (
            'central model' if doc.IsWorkshared else 'not workshared')
        self.txtModel.Text = u'{}  ·  {}'.format(doc.Title, kind)
        self.txtModel.ToolTip = doc.Title
        self.txtUser.Text = self.me or '?'
        running = common.watcher_running()
        live = common.is_live() and running
        if live:
            self.txtLive.Text = 'Live'
            self.txtLiveHint.Text = 'Watching new elements'
        elif running:
            self.txtLive.Text = 'Offline'
            self.txtLiveHint.Text = 'Paused from the ribbon'
        else:
            self.txtLive.Text = 'Not running'
            self.txtLiveHint.Text = 'Restart Revit to start it'
        self.dotLive.Fill = self.brush('#1F9D55' if live else ('#8C959F' if running else '#D1242F'))
        name = '-'
        if doc.IsWorkshared:
            ws = core.workset_by_id(doc, core.active_workset_id(doc))
            if ws is not None:
                name = ws.Name
        self.txtActive.Text = name
        self._map_badge()

    def ws_name(self, ws_id):
        ws = core.workset_by_id(self.doc, ws_id)
        return ws.Name if ws is not None else 'workset #{} (deleted)'.format(ws_id)

    def _my_claim(self, ws_id):
        return (self.work.get('claims') or {}).get(str(ws_id))

    # ------------------------------------------------------------------
    # Worksets page
    # ------------------------------------------------------------------
    def fill_ws_grid(self):
        if not common.eligible(self.doc):
            return
        keep = set(r.id for r in self.gridWs.SelectedItems)
        chips = CHIP_DARK if self.dark else CHIP_LIGHT
        active = core.active_workset_id(self.doc)
        mapped = {}
        for cat, ws in self.effective.items():
            mapped[ws] = mapped.get(ws, 0) + 1
        rows = []
        for ws in core.user_worksets(self.doc):
            wid = ws.Id.IntegerValue
            status, claimers, open_share = store.ws_status(self.claims, wid, self.me)
            row = Row()
            row.id = wid
            row.ws = ws
            row.name = ws.Name
            row.is_active = wid == active
            row.active_vis = VISIBLE if row.is_active else HIDDEN
            row.status = status
            row.claimers = claimers
            row.open_share = open_share
            names = ['You' if c == self.me else c for c in claimers]
            if not names:
                row.claim_text = 'Nobody'
            else:
                row.claim_text = ', '.join(names)
                if open_share and status != store.STATUS_MINE:
                    row.claim_text += '  (shared)'
            bg, fg = chips[status]
            row.claim_bg = self.brush(bg)
            row.claim_fg = self.brush(fg)
            if not ws.Owner:
                row.owner = ''
            elif ws.Owner == self.me:
                row.owner = 'You'
            else:
                row.owner = ws.Owner
            row.elements_n = core.count_elements(self.doc, wid)
            row.elements = str(row.elements_n)
            row.mapped_n = mapped.get(wid, 0)
            rows.append(row)
        rows.sort(key=lambda r: r.name.lower())
        self.all_ws_rows = rows
        search = (self.tbWsSearch.Text or '').strip().lower()
        shown = [r for r in rows if not search or search in r.name.lower()]
        self.ws_rows = shown
        self.filling = True
        try:
            self.gridWs.ItemsSource = shown
            for r in shown:
                if r.id in keep:
                    self.gridWs.SelectedItems.Add(r)
            self.cbMapTo.ItemsSource = [r.name for r in rows]
        finally:
            self.filling = False
        self.update_ws_detail()

    def selected_ws(self):
        return [r for r in self.gridWs.SelectedItems]

    def update_ws_detail(self):
        if self.filling:
            return
        rows = self.selected_ws()
        if not rows:
            self.txtWsEmpty.Visibility = VISIBLE
            self.pnlWsDetail.Visibility = HIDDEN
            return
        self.txtWsEmpty.Visibility = HIDDEN
        self.pnlWsDetail.Visibility = VISIBLE
        single = len(rows) == 1
        for name in ('btnActive', 'btnRename', 'btnDelete'):
            getattr(self, name).Visibility = VISIBLE if single else HIDDEN

        if single:
            row = rows[0]
            ws = row.ws
            self.txtWsName.Text = row.name
            bits = ['{} element(s)'.format(row.elements_n)]
            if row.mapped_n:
                bits.append('{} categor{} mapped here'.format(
                    row.mapped_n, 'y' if row.mapped_n == 1 else 'ies'))
            if row.is_active:
                bits.append('your active workset')
            self.txtWsSummary.Text = u'  ·  '.join(bits)

            if not ws.Owner:
                owner = 'Nobody has it checked out.'
            elif ws.Owner == self.me:
                owner = 'You have it checked out (editable).'
            else:
                owner = '{} has it checked out. You cannot edit its elements until they relinquish it.'.format(ws.Owner)
            vis = 'Visible' if ws.IsVisibleByDefault else 'Hidden'
            self.txtWsRevit.Text = '{}\n{} in new views by default.'.format(owner, vis)
            taken = core.owned_by_other(ws, self.me)
            self.btnActive.IsEnabled = not row.is_active and not taken
            self.btnActive.Content = ('This is your active workset' if row.is_active
                                      else 'Make it my active workset')
            self.btnEditable.IsEnabled = not taken and ws.Owner != self.me
            self.btnEditable.Content = ('You can already edit it' if ws.Owner == self.me
                                        else 'Make editable (check out)')
            self.txtWsClaim.Text = self._claim_sentence(row)
            mine = self._my_claim(row.id)
            self.btnClaim.Visibility = HIDDEN if mine == store.CLAIM_PRIVATE else VISIBLE
            self.btnShare.Visibility = HIDDEN if mine == store.CLAIM_SHARED else VISIBLE
            self.btnUnclaim.Visibility = VISIBLE if mine else HIDDEN
        else:
            self.txtWsName.Text = '{} worksets selected'.format(len(rows))
            self.txtWsSummary.Text = ', '.join(r.name for r in rows[:5]) + (
                ' ...' if len(rows) > 5 else '')
            free = [r for r in rows if not core.owned_by_other(r.ws, self.me) and r.ws.Owner != self.me]
            self.txtWsRevit.Text = '{} of them can be checked out by you.'.format(len(free))
            self.btnEditable.IsEnabled = bool(free)
            self.btnEditable.Content = 'Make all editable (check out)'
            claimed = [r for r in rows if self._my_claim(r.id)]
            self.txtWsClaim.Text = 'You claim {} of them.'.format(len(claimed))
            self.btnClaim.Visibility = VISIBLE
            self.btnShare.Visibility = VISIBLE
            self.btnUnclaim.Visibility = VISIBLE if claimed else HIDDEN

    def _claim_sentence(self, row):
        mine = self._my_claim(row.id)
        others = [c for c in row.claimers if c != self.me]
        if not row.claimers:
            return 'Nobody has claimed it.'
        if mine == store.CLAIM_PRIVATE and not others:
            return 'Claimed by you. Teammates get a notice if they place elements on it.'
        if mine == store.CLAIM_SHARED and not others:
            return 'Claimed by you as shared: teammates may work on it without a warning.'
        if mine and others:
            return 'Shared between you and {}.'.format(', '.join(others))
        if row.open_share:
            return 'Claimed by {} and open to share.'.format(', '.join(others))
        return 'Claimed by {}. You get a notice if you place elements on it.'.format(', '.join(others))

    def _one_ws(self):
        rows = self.selected_ws()
        if len(rows) != 1:
            self.bar('Select one workset first.')
            return None
        return rows[0]

    def on_refresh(self, sender, args):
        if self.dirty:
            self.bar('Refreshing reads the model again and drops your unsaved mapping changes.',
                     yes=self._do_refresh, yes_text='Refresh anyway', no_text='Cancel')
            return
        self._safe(self._do_refresh)

    def _do_refresh(self):
        self.counts = core.category_counts(self.doc, self.categories)
        self.types_by_cat, self.types = core.type_inventory(self.doc, self.categories, self.counts)
        self.reload_model_data()
        self.refresh_all()
        self.status('Refreshed.')

    # name panel (new / rename)
    def on_new(self, sender, args):
        self.show_page(0)
        self.name_mode = 'new'
        self.txtNameLabel.Text = 'New workset name'
        self.btnNameOk.Content = 'Create'
        self.chkClaimNew.Visibility = VISIBLE
        self.chkClaimNew.IsChecked = True
        self.tbName.Text = ''
        self.pnlName.Visibility = VISIBLE
        self.tbName.Focus()

    def on_rename(self, sender, args):
        row = self._one_ws()
        if row is None:
            return
        self.name_mode = 'rename'
        self.name_target = row
        self.txtNameLabel.Text = 'New name'
        self.btnNameOk.Content = 'Rename'
        self.chkClaimNew.Visibility = HIDDEN
        self.tbName.Text = row.name
        self.pnlName.Visibility = VISIBLE
        self.tbName.Focus()
        self.tbName.SelectAll()

    def on_name_cancel(self, sender, args):
        self.pnlName.Visibility = HIDDEN

    def on_name_key(self, sender, args):
        key = str(args.Key)
        if key in ('Return', 'Enter'):
            args.Handled = True
            self.on_name_ok(None, None)
        elif key == 'Escape':
            args.Handled = True
            self.on_name_cancel(None, None)

    def on_name_ok(self, sender, args):
        name = (self.tbName.Text or '').strip()

        def work():
            if self.name_mode == 'new':
                ws = core.create_workset(self.doc, name)
                if self.chkClaimNew.IsChecked:
                    self._write_claims({str(ws.Id.IntegerValue): store.CLAIM_PRIVATE})
                self.status('Created "{}". Sync so the team gets it.'.format(name))
            else:
                old = self.name_target.name
                core.rename_workset(self.doc, self.name_target.id, name)
                self.status('Renamed "{}" to "{}".'.format(old, name))
            self.pnlName.Visibility = HIDDEN
            self._reload_keep_work()
        self._safe(work)

    def _reload_keep_work(self):
        """Re-read the model but keep unsaved mapping edits."""
        work, dirty = self.work, self.dirty
        self.reload_model_data()
        if dirty:
            self.work, self.dirty = work, True
            self.recompute()
        self.refresh_all()

    # delete
    def _move_enabled(self, enabled):
        self.cbMoveTo.IsEnabled = enabled

    def on_delete(self, sender, args):
        row = self._one_ws()
        if row is None:
            return
        others = [r for r in self.all_ws_rows if r.id != row.id]
        if not others:
            self.bar('A model needs at least one user workset.')
            return
        self.cbMoveTo.ItemsSource = [r.name for r in others]
        self.cbMoveTo.SelectedIndex = 0
        self.chkDeleteElements.IsChecked = False
        self._move_enabled(True)
        self.delete_target = row
        self.delete_others = others
        text = 'Delete the workset "{}"? It holds {} element(s).'.format(row.name, row.elements)
        self.bar(text, yes=self._do_delete, yes_text='Delete workset', no_text='Cancel', extra=True)

    def _do_delete(self):
        row = self.delete_target
        move_to = None
        if not self.chkDeleteElements.IsChecked:
            index = self.cbMoveTo.SelectedIndex
            if index < 0:
                raise Exception('Pick the workset that receives the elements.')
            move_to = self.delete_others[index].id
        core.delete_workset(self.doc, row.id, move_to)
        changed = False
        for cat, ws in list(self.work['mapping'].items()):
            if ws == row.id:
                if move_to is not None:
                    self.work['mapping'][cat] = move_to
                else:
                    del self.work['mapping'][cat]
                changed = True
        if str(row.id) in self.work['claims']:
            del self.work['claims'][str(row.id)]
            changed = True
        if changed:
            self._write_work('Update after delete')
        self.status('Deleted "{}".'.format(row.name))
        self.reload_model_data()
        self.refresh_all()

    # active / editable
    def on_set_active(self, sender, args):
        row = self._one_ws()
        if row is None:
            return

        def work():
            if core.owned_by_other(row.ws, self.me):
                raise Exception('"{}" is checked out by {}. Ask them to relinquish it first.'
                                .format(row.name, row.ws.Owner))
            core.set_active(self.doc, row.id)
            self.status('Your active workset is now "{}".'.format(row.name))
            self._header()
            self.fill_ws_grid()
        self._safe(work)

    def on_editable(self, sender, args):
        rows = self.selected_ws()
        if not rows:
            return

        def work():
            got = core.checkout(self.doc, [r.id for r in rows])
            missed = [r.name for r in rows if r.id not in got]
            if missed:
                self.bar('Could not check out: {}. Someone else has it, or the central model '
                         'was not reachable.'.format(', '.join(missed)))
            self.status('{} workset(s) are now editable by you.'.format(len(got)))
            self.fill_ws_grid()
        self._safe(work)

    # sync / relinquish (sidebar)
    def on_sync(self, sender, args):
        def work():
            self.status('Synchronizing with central...')
            if self.dirty:
                self._write_work('Save mapping')
            core.sync(self.doc, 'IMM Workset Manager')
            self.reload_model_data()
            self.refresh_all()
            self.status('Synchronized. Your worksets stay checked out to you.')
        self._safe(work)

    def on_relinquish(self, sender, args):
        owned = core.owned_by_me(self.doc, self.me)
        if owned:
            names = ', '.join(w.Name for w in owned[:6]) + (' ...' if len(owned) > 6 else '')
            text = 'Relinquish everything you have checked out ({}: {})?'.format(len(owned), names)
        else:
            text = 'Relinquish everything you have checked out in this model?'
        text += ' Recommended: Sync, Relinquish, Sync, so nothing is lost.'
        self.bar(text, yes=self._sync_relinquish_sync, yes_text=u'Sync · Relinquish · Sync',
                 alt=self._relinquish_only, alt_text='Relinquish only', no_text='Cancel')

    def _sync_relinquish_sync(self):
        if self.dirty:
            self._write_work('Save mapping')
        self.status('Step 1 of 3: synchronizing...')
        try:
            core.sync(self.doc, 'IMM: before relinquish')
        except Exception as ex:
            raise Exception('The first sync failed, so nothing was relinquished.\n{}'.format(ex))
        self.status('Step 2 of 3: relinquishing...')
        core.relinquish_all(self.doc)
        self.status('Step 3 of 3: synchronizing...')
        core.sync(self.doc, 'IMM: after relinquish')
        self.reload_model_data()
        self.refresh_all()
        self.status('Done: synced, relinquished everything you had, synced again.')

    def _relinquish_only(self):
        core.relinquish_all(self.doc)
        self._reload_keep_work()
        self.status('Relinquished everything you had checked out.')

    # claims
    def _write_claims(self, changes):
        record = store.read_user(self.doc, self.me)
        for ws, kind in changes.items():
            if kind is None:
                record['claims'].pop(str(ws), None)
            else:
                record['claims'][str(ws)] = kind
        core.run_in_transaction(self.doc, 'Claim worksets',
                                lambda: store.write_user(self.doc, self.me, record))
        common.mapping_changed()
        # keep the working copy in step without losing unsaved mapping edits
        self.work['claims'] = copy.deepcopy(record['claims'])
        self.saved['claims'] = copy.deepcopy(record['claims'])

    def _claim(self, kind):
        rows = self.selected_ws()
        if not rows:
            return

        def work():
            taken = [r.name for r in rows if r.status == store.STATUS_OTHERS]
            self._write_claims(dict((str(r.id), kind) for r in rows))
            note = ''
            if kind == store.CLAIM_PRIVATE and common.load_settings().get('checkout_on_claim'):
                got = core.checkout(self.doc, [r.id for r in rows])
                note = ' {} checked out to you.'.format(len(got))
            self._reload_keep_work()
            label = 'mine' if kind == store.CLAIM_PRIVATE else 'shared'
            self.status('{} workset(s) claimed as {}.{} Sync so the team sees it.'
                        .format(len(rows), label, note))
            if taken:
                self.bar('Already claimed by someone else: {}. They now show as shared, and both '
                         'of you get a notice after the next sync.'.format(', '.join(taken)))
        self._safe(work)

    def on_claim(self, sender, args):
        self._claim(store.CLAIM_PRIVATE)

    def on_share(self, sender, args):
        self._claim(store.CLAIM_SHARED)

    def on_unclaim(self, sender, args):
        rows = self.selected_ws()
        if not rows:
            return

        def work():
            self._write_claims(dict((str(r.id), None) for r in rows))
            self._reload_keep_work()
            self.status('Removed your claim on {} workset(s).'.format(len(rows)))
        self._safe(work)

    # ------------------------------------------------------------------
    # Category mapping page
    # ------------------------------------------------------------------
    def _needs_workset(self):
        never = set(self.work['never'])
        return [k for k in self.categories if self.counts.get(k, 0) > 0
                and k not in self.effective and k not in never]

    def _open_conflicts(self):
        return [k for k, info in self.conflicts.items() if info.get('new')]

    def _map_badge(self):
        n = len(self._needs_workset()) + len(self._open_conflicts())
        self.txtBadgeMap.Text = str(n)
        self.badgeMap.Visibility = VISIBLE if n else HIDDEN

    def _refill_map(self):
        if not self.filling:
            self.fill_map_grid()

    def _cat_kind(self, key, never):
        if key in self.conflicts:
            return 'conflict'
        if key in never:
            return 'never'
        if self.effective.get(key) is None:
            return 'needed' if self.counts.get(key, 0) else 'none'
        if self.sources.get(key, ('mine', []))[0] == 'adopted':
            return 'adopted'
        return 'mine'

    def _type_kind(self, key):
        if key in self.conflicts:
            return 'conflict'
        if self.effective.get(key) is None:
            return 'inherit'
        if self.sources.get(key, ('mine', []))[0] == 'adopted':
            return 'adopted'
        return 'mine'

    @staticmethod
    def _passes(flt, kind, count, ws, prop):
        if flt == 'Used in this model':
            return bool(count)
        if flt == 'Needs a workset':
            return kind == 'needed'
        if flt == 'Mapped':
            return ws is not None
        if flt == 'From teammates':
            return kind == 'adopted'
        if flt == 'Conflicts':
            return kind == 'conflict'
        if flt == 'Has a suggestion':
            return bool(prop)
        if flt == 'Never moved':
            return kind == 'never'
        return True

    def _row_text(self, row, kind, ws, prop, fallback=None):
        fg = self.brush('#F0F3F6' if self.dark else '#1F2328')
        fg2 = self.brush('#8C959F')
        accent = self.brush('#4C8DFF' if self.dark else '#2F6FEB')
        if kind == 'never':
            row.ws_text, row.ws_fg = 'stays on the active workset', fg2
        elif ws is not None:
            row.ws_text, row.ws_fg = self.ws_name(ws), fg
        elif prop:
            row.ws_text, row.ws_fg = u'suggested: {}'.format(self.ws_name(prop[0])), accent
        elif fallback is not None:
            row.ws_text, row.ws_fg = fallback, fg2
        else:
            row.ws_text, row.ws_fg = u'—', fg2
        if kind == 'conflict':
            row.source = 'Conflict'
        elif kind == 'never':
            row.source = 'Never'
        elif kind == 'adopted':
            row.source = 'From {}'.format(', '.join(self.sources[row.key][1]))
        elif kind == 'mine':
            row.source = 'You'
        elif kind == 'needed':
            row.source = 'Missing'
        else:
            row.source = ''

    def _make_row(self, key, name, count, kind, ws, prop, is_type, cat_key, discipline):
        row = Row()
        row.key = key
        row.is_type = is_type
        row.cat_key = cat_key
        row.name = name
        row.discipline = discipline
        row.count_n = count
        row.count = str(count) if count else ''
        row.ws_id = ws
        row.kind = kind
        row.dot = self.brush(DOTS.get(kind, '#00000000'))
        row.weight = FontWeights.Normal if is_type else FontWeights.SemiBold
        row.proposed_ws = prop[0] if prop else None
        row.proposed_pct = prop[1] if prop else 0
        row.proposed_why = prop[2] if prop and len(prop) > 2 else ''
        return row

    def fill_map_grid(self, keep=None):
        if not self.categories:
            return
        if keep is None:
            keep = set(r.key for r in self.gridMap.SelectedItems)
        search = (self.tbSearch.Text or '').strip().lower()
        flt = FILTERS[max(0, self.cbFilter.SelectedIndex)]
        disc_index = max(0, self.cbDiscipline.SelectedIndex)
        discipline = None if disc_index == 0 else core.DISCIPLINES[disc_index - 1]
        show_types = bool(self.chkTypes.IsChecked)
        never = set(self.work['never'])
        rows = []
        for key, info in sorted(self.categories.items(), key=lambda kv: kv[1].name.lower()):
            if discipline and info.discipline != discipline:
                continue
            kind = self._cat_kind(key, never)
            count = self.counts.get(key, 0)
            ws = self.effective.get(key)
            prop = self.proposals.get(key)
            cat_match = not search or search in info.name.lower()

            # its types: shown when asked, or when they have a rule or a suggestion
            type_rows = []
            for t in self.types_by_cat.get(key, []):
                t_ws = self.effective.get(t.key)
                t_prop = self.proposals.get(t.key)
                if t_prop and t_ws == t_prop[0]:
                    t_prop = None
                if not (show_types or t_ws is not None or t_prop or t.key in self.conflicts):
                    continue
                if search and not cat_match and search not in t.label.lower():
                    continue
                t_kind = self._type_kind(t.key)
                if kind == 'never' and t_ws is None:
                    continue
                type_rows.append((t, t_kind, t_ws, t_prop))

            if search and not cat_match and not type_rows:
                continue
            passes = self._passes(flt, kind, count, ws, prop)
            if not passes and flt != 'Used in this model':
                matching = [tr for tr in type_rows
                            if self._passes(flt, tr[1], tr[0].count, tr[2], tr[3])]
                if not matching:
                    continue
                type_rows = matching
            elif not passes:
                continue

            row = self._make_row(key, info.name, count, kind, ws, prop, False, key, info.discipline)
            self._row_text(row, kind, ws, prop)
            rows.append(row)

            cat_ws_text = self.ws_name(ws) if ws is not None else (
                self.ws_name(prop[0]) if prop else None)
            for t, t_kind, t_ws, t_prop in type_rows:
                trow = self._make_row(t.key, u'      ↳ ' + t.label, t.count, t_kind, t_ws,
                                      t_prop, True, key, info.discipline)
                trow.label = t.label
                trow.function = t.function
                fallback = u'same as category' + (u' ({})'.format(cat_ws_text) if cat_ws_text else '')
                self._row_text(trow, t_kind, t_ws, t_prop, fallback)
                rows.append(trow)

        self.cat_rows = rows
        self.filling = True
        try:
            self.gridMap.ItemsSource = rows
            for r in rows:
                if r.key in keep:
                    self.gridMap.SelectedItems.Add(r)
        finally:
            self.filling = False
        self._map_status()
        self._map_badge()
        self.update_cat_detail()

    def _map_status(self):
        needed = len(self._needs_workset())
        cats = len([k for k in self.effective if not core.is_type_key(k)])
        types = len([k for k in self.effective if core.is_type_key(k)])
        text = '{} categories mapped'.format(cats)
        if types:
            text += u'  ·  {} type rule(s)'.format(types)
        if needed:
            text += u'  ·  {} used but without a workset'.format(needed)
        if self.conflicts:
            text += u'  ·  {} conflict(s)'.format(len(self.conflicts))
        if self.dirty:
            text = u'Unsaved changes  ·  ' + text
        self.txtMapStatus.Text = text
        self.btnSaveMap.IsEnabled = self.dirty
        self.btnRevertMap.IsEnabled = self.dirty
        open_props = self._open_proposals()
        if open_props:
            self.btnApplyProposals.Content = 'Use all {} suggestions'.format(len(open_props))
            self.btnApplyProposals.Visibility = VISIBLE
        else:
            self.btnApplyProposals.Visibility = HIDDEN

    def _open_proposals(self):
        out = []
        for k, p in self.proposals.items():
            if self.effective.get(k) is not None:
                continue
            if core.is_type_key(k):
                t = self.types.get(k)
                if t is None or t.cat_key in self.work['never']:
                    continue
            elif k in self.work['never']:
                continue
            out.append(k)
        return out

    def selected_cats(self):
        return [r for r in self.gridMap.SelectedItems]

    def update_cat_detail(self):
        if self.filling:
            return
        rows = self.selected_cats()
        if not rows:
            self.txtCatEmpty.Visibility = VISIBLE
            self.pnlCatDetail.Visibility = HIDDEN
            return
        self.txtCatEmpty.Visibility = HIDDEN
        self.pnlCatDetail.Visibility = VISIBLE
        only_types = all(r.is_type for r in rows)
        any_type = any(r.is_type for r in rows)
        names = [r.name for r in self.all_ws_rows]
        self.filling = True
        try:
            if len(rows) == 1:
                row = rows[0]
                if row.is_type:
                    cat = self.categories.get(row.cat_key)
                    self.txtCatName.Text = row.label
                    bits = ['Type of {}'.format(cat.name if cat else 'category'),
                            '{} element(s)'.format(row.count_n)]
                    if row.function:
                        bits.append(row.function)
                    self.txtCatSummary.Text = u'  ·  '.join(bits)
                else:
                    self.txtCatName.Text = row.name
                    used = ('{} element(s) in this model'.format(row.count_n) if row.count_n
                            else 'not used in this model yet')
                    n_types = len(self.types_by_cat.get(row.key, []))
                    extra = u'  ·  {} type(s)'.format(n_types) if n_types else ''
                    self.txtCatSummary.Text = u'{}  ·  {}{}'.format(row.discipline, used, extra)
            else:
                what = 'types' if only_types else ('items' if any_type else 'categories')
                self.txtCatName.Text = '{} {} selected'.format(len(rows), what)
                self.txtCatSummary.Text = 'Changes apply to all of them.'

            # the workset dropdown; types can also follow their category
            if only_types:
                cat_names = sorted(set(self.categories[r.cat_key].name for r in rows
                                       if r.cat_key in self.categories))
                self.map_offset = 1
                self.cbMapTo.ItemsSource = [u'Same as {}'.format(', '.join(cat_names))] + names
                self.txtMapToLabel.Text = 'THIS TYPE GOES TO' if len(rows) == 1 else 'THESE TYPES GO TO'
            else:
                self.map_offset = 0
                self.cbMapTo.ItemsSource = names
                self.txtMapToLabel.Text = 'GOES TO WORKSET'
            targets = set(r.ws_id for r in rows if r.kind != 'never')
            index = -1
            if only_types and targets == set([None]):
                index = 0
            elif len(targets) == 1:
                target = list(targets)[0]
                for i, r in enumerate(self.all_ws_rows):
                    if r.id == target:
                        index = i + self.map_offset
            self.cbMapTo.SelectedIndex = index
            self.chkNever.Visibility = HIDDEN if any_type else VISIBLE
            self.txtNeverHint.Visibility = HIDDEN if any_type else VISIBLE
            never = [r for r in rows if r.kind == 'never']
            self.chkNever.IsChecked = len(never) == len(rows)
            self.btnClearMap.Content = 'Remove type rule' if only_types else 'Remove mapping'
            self.btnClearMap.Visibility = HIDDEN if only_types else VISIBLE
            self.btnClearMap.IsEnabled = any(r.key in self.work['mapping'] for r in rows)
            if not any_type and len(rows) == 1 and self.types_by_cat.get(rows[0].key) \
                    and not self.chkTypes.IsChecked:
                self.txtTypesHint.Visibility = VISIBLE
            else:
                self.txtTypesHint.Visibility = HIDDEN
        finally:
            self.filling = False

        # suggestion
        row = rows[0]
        if len(rows) == 1 and row.proposed_ws is not None and row.ws_id != row.proposed_ws \
                and row.kind != 'never':
            why = row.proposed_why or 'the names match'
            self.txtSuggest.Text = u'Suggested: "{}" ({}).'.format(self.ws_name(row.proposed_ws), why)
            self.pnlSuggest.Visibility = VISIBLE
        else:
            self.pnlSuggest.Visibility = HIDDEN

        # conflict
        if len(rows) == 1 and row.key in self.conflicts:
            info = self.conflicts[row.key]
            parts = []
            for ws, users in info['theirs'].items():
                parts.append(u'{} use "{}"'.format(', '.join(users), self.ws_name(ws)))
            if info['mine'] is not None:
                text = u'You use "{}". {}.'.format(self.ws_name(info['mine']), '; '.join(parts))
                self.btnKeepMine.Visibility = VISIBLE
            else:
                text = u'{}.'.format('; '.join(parts))
                self.btnKeepMine.Visibility = HIDDEN
            self.txtConflict.Text = text
            self.pnlConflict.Visibility = VISIBLE
        else:
            self.pnlConflict.Visibility = HIDDEN

    def _changed(self, message=None):
        self.dirty = True
        self.recompute()
        self.fill_ws_grid()
        self.fill_map_grid()
        if message:
            self.status(message + ' Click "Save mapping" to keep it.')

    def _short(self, rows):
        if len(rows) == 1:
            return rows[0].label if rows[0].is_type else rows[0].name
        return '{} items'.format(len(rows))

    def on_map_to_changed(self, sender, args):
        if self.filling:
            return
        index = self.cbMapTo.SelectedIndex
        rows = self.selected_cats()
        if index < 0 or not rows:
            return
        if self.map_offset and index == 0:
            for row in rows:
                self.work['mapping'].pop(row.key, None)
            self._changed(u'{} follow their category again.'.format(self._short(rows)))
            return
        ws = self.all_ws_rows[index - self.map_offset]
        for row in rows:
            self.work['mapping'][row.key] = ws.id
            if row.key in self.work['never']:
                self.work['never'].remove(row.key)
        self._changed(u'{} now go to "{}".'.format(self._short(rows), ws.name))

    def on_clear_map(self, sender, args):
        rows = self.selected_cats()
        removed = 0
        for row in rows:
            if row.key in self.work['mapping']:
                del self.work['mapping'][row.key]
                removed += 1
        adopted = [r for r in rows if r.kind == 'adopted']
        self._changed('Removed {} mapping(s).'.format(removed))
        if adopted:
            self.bar('{} of these still follow a teammate\'s mapping. Tick "Never move this '
                     'category" to stop following it.'.format(len(adopted)))

    def on_never_clicked(self, sender, args):
        if self.filling:
            return
        rows = [r for r in self.selected_cats() if not r.is_type]
        on = bool(self.chkNever.IsChecked)
        for row in rows:
            if on:
                self.work['mapping'].pop(row.key, None)
                if row.key not in self.work['never']:
                    self.work['never'].append(row.key)
            elif row.key in self.work['never']:
                self.work['never'].remove(row.key)
        self._changed('Never move: {} for {} categor{}.'.format(
            'on' if on else 'off', len(rows), 'y' if len(rows) == 1 else 'ies'))

    def on_auto(self, sender, args):
        def work():
            self.proposals = core.auto_map_by_name(
                self.doc, self.categories, self.counts, self.types_by_cat, self.effective)
            self._after_proposals()
        self._safe(work)

    def _after_proposals(self):
        n_types = len([k for k in self.proposals if core.is_type_key(k)])
        n_cats = len(self.proposals) - n_types
        self.filling = True
        self.cbFilter.SelectedIndex = FILTERS.index('Has a suggestion')
        self.filling = False
        self.fill_map_grid()
        if self.proposals:
            self.status(u'{} category and {} type suggestion(s) from the workset names. They show '
                        u'in blue; nothing changes until you accept them.'.format(n_cats, n_types))
        else:
            self.status('No suggestions: no workset name fits the categories or types in use.')

    def on_accept_one(self, sender, args):
        rows = self.selected_cats()
        if len(rows) != 1 or rows[0].proposed_ws is None:
            return
        row = rows[0]
        self.work['mapping'][row.key] = row.proposed_ws
        if row.key in self.work['never']:
            self.work['never'].remove(row.key)
        self._changed(u'{} now go to "{}".'.format(self._short(rows), self.ws_name(row.proposed_ws)))

    def on_apply_proposals(self, sender, args):
        keys = self._open_proposals()
        if not keys:
            return
        for key in keys:
            self.work['mapping'][key] = self.proposals[key][0]
        self._changed('Accepted {} suggestions.'.format(len(keys)))

    def on_keep_mine(self, sender, args):
        rows = self.selected_cats()
        if len(rows) != 1 or rows[0].key not in self.conflicts:
            return
        key = rows[0].key
        theirs = list(self.conflicts[key]['theirs'].keys())
        acked = set(self.work['acked'].get(key) or [])
        acked.update(theirs)
        self.work['acked'][key] = sorted(acked)
        self._changed('Keeping your mapping. Teammates see the conflict after you sync.')

    def on_use_theirs(self, sender, args):
        rows = self.selected_cats()
        if len(rows) != 1 or rows[0].key not in self.conflicts:
            return
        key = rows[0].key
        options = self.conflicts[key]['theirs']
        best = max(options.items(), key=lambda item: len(item[1]))[0]
        self.work['mapping'][key] = best
        self.work['acked'].pop(key, None)
        self._changed(u'Using "{}" like your teammates.'.format(self.ws_name(best)))

    def _write_work(self, name):
        work = copy.deepcopy(self.work)

        def write():
            latest = store.read_user(self.doc, self.me)
            latest['mapping'] = work['mapping']
            latest['never'] = work['never']
            latest['acked'] = work['acked']
            store.write_user(self.doc, self.me, latest)
        core.run_in_transaction(self.doc, name, write)
        common.mapping_changed()
        self.dirty = False

    def on_save_map(self, sender, args):
        def work():
            self._write_work('Save mapping')
            self.reload_model_data()
            self.refresh_all()
            self.status('Mapping saved. The watcher uses it now; sync to share it with the team.')
        self._safe(work)

    def on_revert_map(self, sender, args):
        self.reload_model_data()
        self.fill_ws_grid()
        self.fill_map_grid()
        self.status('Unsaved mapping changes were undone.')

    # templates
    def on_export(self, sender, args):
        path = forms.save_file(file_ext='json', default_name='IMM worksets mapping')
        if not path:
            return
        items = []
        for key, ws in sorted(self.effective.items()):
            if core.is_type_key(key):
                # a type rule: saved by category plus "Family : Type" label
                t = self.types.get(key)
                info = self.categories.get(t.cat_key) if t is not None else None
                if info is None:
                    continue
                items.append({'category': info.name, 'bic': info.bic, 'type': t.label,
                              'workset': self.ws_name(ws)})
                continue
            info = self.categories.get(key)
            if info is None:
                continue
            items.append({'category': info.name, 'bic': info.bic, 'workset': self.ws_name(ws)})
        data = {'format': TEMPLATE_FORMAT, 'v': 1, 'mapping': items,
                'never': [self.categories[k].bic for k in self.work['never'] if k in self.categories]}
        with open(path, 'w') as f:
            json.dump(data, f, indent=1)
        self.status('Exported {} mappings to {}'.format(len(items), path))

    def on_import(self, sender, args):
        path = forms.pick_file(file_ext='json')
        if not path:
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            items = data.get('mapping') or []
        except Exception:
            self.bar('That file is not an IMM mapping template.')
            return
        by_bic = dict((info.bic, key) for key, info in self.categories.items())
        by_name = dict((info.name.lower(), key) for key, info in self.categories.items())
        plan = []
        missing = set()
        for item in items:
            key = by_bic.get(item.get('bic')) or by_name.get((item.get('category') or '').lower())
            if key is None:
                continue
            type_label = (item.get('type') or '').strip().lower()
            if type_label:
                # a type rule: find the type with the same label in this model
                match = [t.key for t in self.types_by_cat.get(key, [])
                         if t.label.strip().lower() == type_label]
                if not match:
                    continue
                key = match[0]
            name = (item.get('workset') or '').strip()
            if not name:
                continue
            plan.append((key, name))
            if core.workset_by_name(self.doc, name) is None:
                missing.add(name)
        never = [by_bic[b] for b in data.get('never') or [] if b in by_bic]
        self.import_plan = (plan, never)
        if missing:
            names = sorted(missing)
            self.bar('The template uses {} workset(s) that this model does not have: {}.'.format(
                len(names), ', '.join(names[:8]) + (' ...' if len(names) > 8 else '')),
                yes=lambda: self._apply_import(True), yes_text='Create them',
                alt=lambda: self._apply_import(False), alt_text='Skip those', no_text='Cancel')
        else:
            self._safe(self._apply_import, False)

    def _apply_import(self, create_missing):
        plan, never = self.import_plan
        created = 0
        if create_missing:
            for name in sorted(set(n for k, n in plan)):
                if core.workset_by_name(self.doc, name) is None:
                    core.create_workset(self.doc, name)
                    created += 1
        applied = 0
        for key, name in plan:
            ws = core.workset_by_name(self.doc, name)
            if ws is None:
                continue
            self.work['mapping'][key] = ws.Id.IntegerValue
            if key in self.work['never']:
                self.work['never'].remove(key)
            applied += 1
        for key in never:
            if key not in self.work['never'] and key not in self.work['mapping']:
                self.work['never'].append(key)
        self._changed('Template: {} mappings applied, {} worksets created.'.format(applied, created))

    # ------------------------------------------------------------------
    # Activity page
    # ------------------------------------------------------------------
    def fill_activity(self, extra=None):
        rows = []
        for item in common.read_activity():
            row = Row()
            row.t = item.get('t') or ''
            row.when = common.local_time_text(row.t)
            row.who = 'You' if item.get('kind') in ('moved', 'blocked') else ''
            row.what = item.get('text') or ''
            row.model = item.get('model') or ''
            rows.append(row)
        mine_ws = set(store.my_worksets(self.claims, self.me))
        for user, rec in self.records.items():
            for item in rec.get('activity') or []:
                try:
                    ws = int(item.get('ws'))
                except Exception:
                    continue
                if user != self.me and ws not in mine_ws:
                    continue
                row = Row()
                row.t = item.get('t') or ''
                row.when = common.local_time_text(row.t)
                row.who = 'You' if user == self.me else user
                verb = 'placed' if item.get('k') == 'add' else 'changed'
                row.what = u'{} {} element(s) on "{}"'.format(verb, item.get('n'), self.ws_name(ws))
                row.model = self.doc.Title
                rows.append(row)
        rows.extend(extra or [])
        rows.sort(key=lambda r: r.t, reverse=True)
        self.gridAct.ItemsSource = rows

    def on_act_refresh(self, sender, args):
        def work():
            self._reload_keep_work()
            self.status('Activity refreshed.')
        self._safe(work)

    def on_act_clear(self, sender, args):
        common.clear_activity()
        self.fill_activity()
        self.status('Your local log was cleared.')

    def on_scan(self, sender, args):
        def work():
            mine = store.my_worksets(self.claims, self.me)
            if not mine:
                raise Exception('You have not claimed any worksets yet. Claim them on the '
                                'Worksets page first.')
            found = {}
            looked = 0
            for wid in mine:
                flt = ElementWorksetFilter(WorksetId(int(wid)), False)
                collector = FilteredElementCollector(self.doc).WherePasses(flt) \
                    .WhereElementIsNotElementType()
                for index, el in enumerate(collector):
                    if index >= 5000:
                        break
                    looked += 1
                    try:
                        info = WorksharingUtils.GetWorksharingTooltipInfo(self.doc, el.Id)
                    except Exception:
                        continue
                    who = info.LastChangedBy
                    if who and who != self.me:
                        found[(who, wid)] = found.get((who, wid), 0) + 1
            extra = []
            for (who, wid), n in found.items():
                row = Row()
                row.t = '9999'
                row.when = 'Just checked'
                row.who = who
                row.what = u'last changed {} element(s) on "{}"'.format(n, self.ws_name(wid))
                row.model = self.doc.Title
                extra.append(row)
            self.fill_activity(extra)
            self.status('Checked {} element(s) on your worksets. {} were last changed by '
                        'someone else.'.format(looked, sum(found.values())))
        self._safe(work)

    # ------------------------------------------------------------------
    # closing
    # ------------------------------------------------------------------
    def on_close(self, sender, args):
        self.Close()

    def on_closing(self, sender, args):
        if self.dirty and not self.allow_close:
            args.Cancel = True
            self.show_page(1)
            self.bar('You have mapping changes that are not saved yet.',
                     yes=self._save_and_close, yes_text='Save and close',
                     alt=self._discard_and_close, alt_text='Discard', no_text='Keep editing')

    def _save_and_close(self):
        self._write_work('Save mapping')
        self.allow_close = True
        self.Close()

    def _discard_and_close(self):
        self.allow_close = True
        self.Close()


def show(uiapp, start_tab=0):
    window = ManagerWindow(uiapp, start_tab)
    window.ShowDialog()
