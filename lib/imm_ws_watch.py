# -*- coding: utf-8 -*-
"""IMM Worksets: the live watcher. Started once from startup.py.

  * IUpdater (runs inside your own transaction, one undo step): puts each new
    or pasted element of a mapped category on its mapped workset.
  * DocumentChanged (read-only): first use of unmapped categories, the
    "N in a row" suggestion, work on worksets claimed by others.
  * Idling + ExternalEvent: everything that touches the UI or the active
    workset (notices, follow mode switching, sharing activity).

The Live Watcher button only flips a flag; the watcher checks it each time.
"""
import time
import traceback

from System import Action, Guid
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    ChangePriority, Element, ElementId, ElementMulticategoryFilter,
    IUpdater, UpdaterId, UpdaterRegistry, WorksetId, WorksetKind
)
from Autodesk.Revit.DB.Events import UndoOperation
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

import imm_ws_common as common
import imm_ws_core as core
import imm_ws_store as store
from imm_ws_notify import (Notice, Notifier, KIND_INFO, KIND_SUCCESS,
                           KIND_WARN)

UPDATER_GUID = Guid('b3e6a0f4-2d7c-4f5e-9a41-6c8d2e1f7b90')
FOLLOW_DELAY = 0.8          # seconds after the last placement before switching
WARN_REPEAT = 600           # same "others' workset" warning at most every 10 min
ACTIVITY_DEBOUNCE = 45      # seconds before sharing activity in the model
MAX_SCAN = 3000             # elements looked at per change event


def _log(message):
    try:
        common.shared_set('LAST_LOG', '{} {}'.format(common.now_iso(), message))
    except Exception:
        pass


class DocState(object):
    """Everything the watcher knows about one open model."""

    def __init__(self, key):
        self.key = key
        self.me = ''
        self.mapping = {}          # {cat int: ws int}
        self.type_map = {}         # {type id int: ws int}, wins over the category
        self.sources = {}
        self.conflicts = {}
        self.never = set()         # {cat int}
        self.claims = {}
        self.records = {}
        self.ws_names = {}
        self.last_active = None
        self.prev_active = None
        self.pending_switch = None
        self.switch_tries = 0
        self.last_add_time = 0.0
        self.streak_ws = None
        self.streak_count = 0
        self.streak_suppressed = None
        self.notified_cats = set()
        self.muted_ws = set()
        self.warned_ws = {}
        self.pending_activity = {}  # {(ws, kind): n}
        self.last_activity_time = 0.0
        self.blocked = []           # filled by the updater
        self.moved = []             # filled by the updater


# ==========================================================================
class WorksetUpdater(IUpdater):
    def __init__(self, watcher, addin_id):
        self.watcher = watcher
        self.uid = UpdaterId(addin_id, UPDATER_GUID)

    def Execute(self, data):
        try:
            self.watcher.updater_execute(data)
        except Exception:
            _log('updater: ' + traceback.format_exc())

    def GetUpdaterId(self):
        return self.uid

    def GetUpdaterName(self):
        return 'IMM Workset Watcher'

    def GetAdditionalInformation(self):
        return 'Puts new elements on their mapped workset (IMM pyRevit extension). Optional.'

    def GetChangePriority(self):
        return ChangePriority.FreeStandingComponents


class ActionHandler(IExternalEventHandler):
    def __init__(self, watcher):
        self.watcher = watcher

    def Execute(self, uiapp):
        try:
            self.watcher.run_api_queue(uiapp)
        except Exception:
            _log('event: ' + traceback.format_exc())

    def GetName(self):
        return 'IMM Workset Watcher actions'


# ==========================================================================
class Watcher(object):
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.app = uiapp.Application
        common.bump('GEN')
        self.gen = common.shared_get('GEN', 0)
        self.settings = common.load_settings()
        self.cfg_ver = common.shared_get('CFG_VER', 0)
        self.map_ver = common.shared_get('MAP_VER', 0)
        self.docs = {}
        self.api_queue = []      # callables(uiapp) that need the Revit API
        self.ui_queue = []       # Notice objects
        self.activity_buffer = []
        self.notifier = Notifier(self._main_hwnd(),
                                 lambda: self.settings.get('notice_seconds', 5))
        self.updater = None
        self.ext_event = None
        self.handlers = []

    # ------------------------------------------------------------------
    # start / stop
    # ------------------------------------------------------------------
    def start(self):
        if common.shared_get('LIVE') is None:
            common.shared_set('LIVE', bool(self.settings.get('live', True)))

        self.updater = WorksetUpdater(self, self._addin_id())
        uid = self.updater.GetUpdaterId()
        try:
            if UpdaterRegistry.IsUpdaterRegistered(uid):
                UpdaterRegistry.UnregisterUpdater(uid)
        except Exception:
            pass
        UpdaterRegistry.RegisterUpdater(self.updater, True)

        try:
            self.ext_event = ExternalEvent.Create(ActionHandler(self))
        except Exception:
            self.ext_event = None

        self._hook(self.app, 'DocumentChanged', self.on_doc_changed)
        self._hook(self.app, 'DocumentOpened', self.on_doc_opened)
        self._hook(self.app, 'DocumentClosing', self.on_doc_closing)
        self._hook(self.app, 'DocumentSynchronizedWithCentral', self.on_synced)
        self._hook(self.app, 'FamilyLoadedIntoDocument', self.on_family_loaded)
        self._hook(self.uiapp, 'Idling', self.on_idling)

        common.shared_set('STOP', Action(self.stop))
        common.shared_set('RUNNING', True)
        common.shared_set('ERROR', '')

    def _addin_id(self):
        for getter in (lambda: self.app.ActiveAddInId,
                       lambda: self.uiapp.ActiveAddInId):
            try:
                value = getter()
                if value is not None:
                    return value
            except Exception:
                pass
        from pyrevit import HOST_APP
        return HOST_APP.addin_id

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
        try:
            if self.updater is not None:
                UpdaterRegistry.UnregisterUpdater(self.updater.GetUpdaterId())
        except Exception:
            pass
        try:
            self.notifier.close_all()
        except Exception:
            pass
        common.shared_set('RUNNING', False)

    def alive(self):
        return common.shared_get('GEN', 0) == self.gen

    def live(self):
        return common.is_live()

    def _main_hwnd(self):
        try:
            return self.uiapp.MainWindowHandle
        except Exception:
            return None

    # ------------------------------------------------------------------
    # model state
    # ------------------------------------------------------------------
    def state_for(self, doc, create=True):
        if not common.eligible(doc):
            return None
        key = common.doc_key(doc)
        state = self.docs.get(key)
        if state is None and create:
            state = self.refresh_doc(doc)
        return state

    def refresh_doc(self, doc, announce=False):
        """Reload mappings and claims from the model and reset triggers."""
        if not common.eligible(doc):
            return None
        key = common.doc_key(doc)
        state = self.docs.get(key) or DocState(key)
        self.docs[key] = state
        me = common.username(doc)
        state.me = me
        records = store.read_all(doc)
        state.records = records
        effective, sources, conflicts = store.merge_mappings(records, me)
        mapping = {}
        type_map = {}
        trigger_cats = set()
        for key, ws in effective.items():
            try:
                if core.is_type_key(key):
                    tid = core.type_id_of(key)
                    el_type = doc.GetElement(common.make_eid(tid))
                    if el_type is None or el_type.Category is None:
                        continue
                    type_map[tid] = int(ws)
                    trigger_cats.add(common.eid_int(el_type.Category.Id))
                else:
                    mapping[int(key)] = int(ws)
                    trigger_cats.add(int(key))
            except Exception:
                pass
        state.mapping = mapping
        state.type_map = type_map
        state.sources = sources
        state.conflicts = conflicts
        mine = records.get(me) or store.empty_record(me)
        state.never = set(int(c) for c in mine['never'])
        state.claims = store.claim_table(records)
        state.ws_names = dict((ws.Id.IntegerValue, ws.Name) for ws in core.user_worksets(doc))
        self._set_triggers(doc, trigger_cats)
        self._compare_with_seen(doc, state, announce)
        return state

    def _set_triggers(self, doc, cats):
        if self.updater is None:
            return
        uid = self.updater.GetUpdaterId()
        try:
            UpdaterRegistry.RemoveDocumentTriggers(uid, doc)
        except Exception:
            pass
        if not cats:
            return
        ids = List[ElementId]([common.make_eid(cat) for cat in cats])
        try:
            UpdaterRegistry.AddTrigger(uid, doc, ElementMulticategoryFilter(ids),
                                       Element.GetChangeTypeElementAddition())
        except Exception:
            _log('triggers: ' + traceback.format_exc())

    def target_for(self, state, el, cat):
        """The workset an element belongs on: its type's rule first, then
        its category's."""
        if state.type_map:
            try:
                target = state.type_map.get(common.eid_int(el.GetTypeId()))
                if target is not None:
                    return target
            except Exception:
                pass
        return state.mapping.get(cat)

    def ws_name(self, state, ws_id):
        return state.ws_names.get(ws_id) or 'workset #{}'.format(ws_id)

    # ------------------------------------------------------------------
    # IUpdater: reassign new elements (inside the user's transaction)
    # ------------------------------------------------------------------
    def updater_execute(self, data):
        if not self.alive() or not self.live():
            return
        doc = data.GetDocument()
        state = self.state_for(doc, create=False)
        if state is None or not (state.mapping or state.type_map):
            return
        table = doc.GetWorksetTable()
        cache = {}
        for eid in data.GetAddedElementIds():
            el = doc.GetElement(eid)
            if el is None or el.ViewSpecific or el.Category is None:
                continue
            cat = common.eid_int(el.Category.Id)
            target = self.target_for(state, el, cat)
            if target is None:
                continue
            current = el.WorksetId.IntegerValue
            if current == target:
                continue
            if target not in cache:
                ws = None
                try:
                    ws = table.GetWorkset(WorksetId(target))
                except Exception:
                    ws = None
                cache[target] = ws
            ws = cache[target]
            if ws is None or ws.Kind != WorksetKind.UserWorkset:
                continue
            if core.owned_by_other(ws, state.me):
                state.blocked.append((cat, target, ws.Owner))
                continue
            param = core.partition_param(el)
            if param is None:
                continue
            try:
                param.Set(target)
                state.moved.append((cat, target))
            except Exception:
                state.blocked.append((cat, target, ''))

    # ------------------------------------------------------------------
    # DocumentChanged (read only)
    # ------------------------------------------------------------------
    def on_doc_changed(self, sender, args):
        if not self.alive():
            return
        try:
            self._doc_changed(args)
        except Exception:
            _log('changed: ' + traceback.format_exc())

    def _doc_changed(self, args):
        if not self.live():
            return
        if args.Operation != UndoOperation.TransactionCommitted:
            return
        for name in args.GetTransactionNames():
            if name.startswith(common.TXN_PREFIX):
                return
        doc = args.GetDocument()
        state = self.state_for(doc)
        if state is None:
            return

        moved, state.moved = state.moved, []
        blocked, state.blocked = state.blocked, []

        added_ids = list(args.GetAddedElementIds())[:MAX_SCAN]
        added_set = set(common.eid_int(i) for i in added_ids)
        modified_ids = [i for i in list(args.GetModifiedElementIds())[:MAX_SCAN]
                        if common.eid_int(i) not in added_set]

        table = doc.GetWorksetTable()
        placed_targets = set()
        foreign = {}
        unmapped = {}
        log = []

        for eid in added_ids:
            el = doc.GetElement(eid)
            if not core.is_mappable_element(doc, el):
                continue
            cat = common.eid_int(el.Category.Id)
            ws = el.WorksetId.IntegerValue
            target = self.target_for(state, el, cat)
            if target is not None:
                placed_targets.add(target)
            elif cat not in state.never and cat not in state.notified_cats:
                unmapped.setdefault(cat, (el.Category.Name, ws))
            status = store.ws_status(state.claims, ws, state.me)
            if status[0] == store.STATUS_OTHERS:
                foreign.setdefault(ws, [0, 0, status])[0] += 1

        for eid in modified_ids:
            el = doc.GetElement(eid)
            if not core.is_mappable_element(doc, el):
                continue
            ws = el.WorksetId.IntegerValue
            status = store.ws_status(state.claims, ws, state.me)
            if status[0] == store.STATUS_OTHERS:
                foreign.setdefault(ws, [0, 0, status])[1] += 1

        # log what the updater moved
        if moved:
            counts = {}
            for cat, target in moved:
                counts[target] = counts.get(target, 0) + 1
            for target, n in counts.items():
                log.append({'t': common.now_iso(), 'kind': 'moved',
                            'text': '{} element(s) put on {}'.format(n, self.ws_name(state, target)),
                            'model': doc.Title})

        for cat, target, owner in blocked[:3]:
            text = 'Workset "{}" is owned by {}. The new element stayed on your active workset.'.format(
                self.ws_name(state, target), owner or 'another user')
            self.ui_queue.append(Notice('Could not move the element', text, KIND_WARN,
                                        key='blocked-{}'.format(target)))
            log.append({'t': common.now_iso(), 'kind': 'blocked', 'text': text, 'model': doc.Title})

        # first use of unmapped categories
        if unmapped and self.settings.get('warn_unmapped', True):
            for cat, (cat_name, ws) in list(unmapped.items())[:3]:
                state.notified_cats.add(cat)
                self.ui_queue.append(self._unmapped_notice(doc, state, cat, cat_name, ws, False))

        # streak / follow
        active = table.GetActiveWorksetId().IntegerValue
        if len(placed_targets) == 1:
            target = list(placed_targets)[0]
            self._after_placement(doc, state, target, active)
        elif len(placed_targets) > 1:
            state.streak_ws, state.streak_count = None, 0

        # others' worksets
        if foreign:
            now = time.time()
            for ws, (n_add, n_edit, status) in foreign.items():
                if n_add:
                    key = (ws, 'add')
                    state.pending_activity[key] = state.pending_activity.get(key, 0) + n_add
                if n_edit:
                    key = (ws, 'edit')
                    state.pending_activity[key] = state.pending_activity.get(key, 0) + n_edit
                state.last_activity_time = now
                if not self.settings.get('warn_others', True) or ws in state.muted_ws:
                    continue
                if now - state.warned_ws.get(ws, 0) < WARN_REPEAT:
                    continue
                state.warned_ws[ws] = now
                self.ui_queue.append(self._others_notice(doc, state, ws, status, n_add, n_edit))

        if log:
            self.activity_buffer.extend(log)

    def _after_placement(self, doc, state, target, active):
        mode = self.settings.get('mode', common.MODE_REASSIGN)
        if mode == common.MODE_FOLLOW:
            if active != target:
                state.pending_switch = target
                state.switch_tries = 0
                state.last_add_time = time.time()
            return
        if target == state.streak_ws:
            state.streak_count += 1
        else:
            state.streak_ws = target
            state.streak_count = 1
            state.streak_suppressed = None
        if not self.settings.get('nudge_enabled', True):
            return
        if (state.streak_count >= self.settings.get('nudge_threshold', 5)
                and active != target and state.streak_suppressed != target):
            state.streak_suppressed = target
            self.ui_queue.append(self._nudge_notice(doc, state, target))

    # ------------------------------------------------------------------
    # Notices
    # ------------------------------------------------------------------
    def _nudge_notice(self, doc, state, target):
        name = self.ws_name(state, target)
        key = state.key

        def switch(checked):
            if checked:
                self._disable_nudge()
            self.queue_api(lambda uiapp: self._switch_active(uiapp, key, target, announce=True))

        def cancel(checked):
            if checked:
                self._disable_nudge()

        return Notice(
            'Switch your active workset to "{}"?'.format(name),
            'You placed {} elements in a row that went to "{}". Switching makes '
            'the next ones land there directly.'.format(state.streak_count, name),
            KIND_INFO,
            buttons=[('Switch', switch, True), ('Cancel', cancel, False)],
            check_text="Don't suggest this again",
            key='nudge-{}'.format(target), seconds=max(8, self.settings.get('notice_seconds', 5)))

    def _unmapped_notice(self, doc, state, cat, cat_name, ws, from_family, family_name=''):
        key = state.key
        ws_name = self.ws_name(state, ws)

        def map_here(checked):
            self.queue_api(lambda uiapp: self._save_mapping(uiapp, key, cat, ws))

        def never(checked):
            self.queue_api(lambda uiapp: self._save_never(uiapp, key, cat))

        if from_family:
            title = 'Loaded family "{}" has no workset mapping'.format(family_name)
            body = 'Category "{}" is not mapped. Map it to your active workset "{}"?'.format(cat_name, ws_name)
            label = 'Map to "{}"'.format(ws_name)
        else:
            title = 'First "{}" placed, no workset mapped'.format(cat_name)
            body = 'It went on "{}". Use that workset for this category from now on?'.format(ws_name)
            label = 'Map to "{}"'.format(ws_name)
        return Notice(title, body, KIND_WARN,
                      buttons=[(label, map_here, True), ('Never map', never, False),
                               ('Later', lambda c: None, False)],
                      key='unmapped-{}'.format(cat), seconds=max(10, self.settings.get('notice_seconds', 5)))

    def _others_notice(self, doc, state, ws, status, n_add, n_edit, switched=False):
        name = self.ws_name(state, ws)
        owners = ', '.join(status[1]) or 'someone else'
        key = state.key
        buttons = []
        if switched and state.prev_active is not None and state.prev_active != ws:
            prev = state.prev_active
            buttons.append(('Switch back', lambda c: self.queue_api(
                lambda uiapp: self._switch_active(uiapp, key, prev)), True))
        if status[2]:
            buttons.append(('I work here too', lambda c: self.queue_api(
                lambda uiapp: self._save_claim(uiapp, key, ws, store.CLAIM_SHARED)), not buttons))

        def mute(checked):
            state.muted_ws.add(ws)
        buttons.append(('Ignore', mute, False))

        if switched:
            title = 'You are on {}\'s workset "{}"'.format(owners, name)
            body = 'Your active workset now belongs to {}.'.format(owners)
        else:
            parts = []
            if n_add:
                parts.append('placed {}'.format(n_add))
            if n_edit:
                parts.append('changed {}'.format(n_edit))
            title = 'You are working on {}\'s workset'.format(owners)
            body = 'You {} element(s) on "{}".'.format(' and '.join(parts), name)
        if status[2]:
            body += ' It is shared, so you can join it.'
        return Notice(title, body, KIND_WARN, buttons=buttons,
                      key='others-{}-{}'.format(ws, 'switch' if switched else 'work'))

    def _disable_nudge(self):
        settings = common.load_settings()
        settings['nudge_enabled'] = False
        common.save_settings(settings)
        self.settings = settings
        self.cfg_ver = common.shared_get('CFG_VER', 0)

    # ------------------------------------------------------------------
    # Actions that need the API (run from Idling or the ExternalEvent)
    # ------------------------------------------------------------------
    def queue_api(self, func):
        self.api_queue.append(func)
        try:
            if self.ext_event is not None:
                self.ext_event.Raise()
        except Exception:
            pass

    def run_api_queue(self, uiapp):
        while self.api_queue:
            func = self.api_queue.pop(0)
            try:
                func(uiapp)
            except Exception as ex:
                self.notifier.show(Notice('IMM Worksets', str(ex), KIND_WARN))
                _log('action: ' + traceback.format_exc())

    def _doc_by_key(self, uiapp, key):
        try:
            for doc in uiapp.Application.Documents:
                if common.eligible(doc) and common.doc_key(doc) == key:
                    return doc
        except Exception:
            pass
        return None

    def _switch_active(self, uiapp, key, ws_id, announce=False):
        doc = self._doc_by_key(uiapp, key)
        state = self.docs.get(key)
        if doc is None or state is None:
            return
        ws = core.workset_by_id(doc, ws_id)
        if ws is None:
            return
        if core.owned_by_other(ws, state.me):
            self.notifier.show(Notice('Cannot switch workset',
                                      '"{}" is owned by {}.'.format(ws.Name, ws.Owner), KIND_WARN))
            return
        core.set_active(doc, ws_id)
        state.streak_ws, state.streak_count = None, 0
        if announce:
            self.notifier.show(Notice('Active workset: {}'.format(ws.Name), '', KIND_SUCCESS,
                                      key='switched-{}'.format(ws_id), seconds=3))

    def _edit_my_record(self, uiapp, key, name, change):
        doc = self._doc_by_key(uiapp, key)
        if doc is None:
            return None
        me = common.username(doc)

        def work():
            record = store.read_user(doc, me)
            change(record)
            store.write_user(doc, me, record)
        core.run_in_transaction(doc, name, work)
        common.mapping_changed()
        self.map_ver = common.shared_get('MAP_VER', 0)
        return self.refresh_doc(doc)

    def _save_mapping(self, uiapp, key, cat, ws):
        def change(record):
            record['mapping'][str(cat)] = int(ws)
            if str(cat) in record['never']:
                record['never'].remove(str(cat))
        state = self._edit_my_record(uiapp, key, 'Map category', change)
        if state is not None:
            self.notifier.show(Notice('Mapping saved', 'Sync to share it with the team.',
                                      KIND_SUCCESS, seconds=3))

    def _save_never(self, uiapp, key, cat):
        def change(record):
            if str(cat) not in record['never']:
                record['never'].append(str(cat))
        self._edit_my_record(uiapp, key, 'Never map category', change)

    def _save_claim(self, uiapp, key, ws, kind):
        def change(record):
            record['claims'][str(ws)] = kind
        state = self._edit_my_record(uiapp, key, 'Claim workset', change)
        if state is not None:
            state.muted_ws.add(ws)
            self.notifier.show(Notice('You now share "{}"'.format(self.ws_name(state, ws)),
                                      'The others are told after you sync.', KIND_SUCCESS, seconds=4))

    def _share_activity(self, uiapp, state):
        """Write my work on others' worksets into my record, so the owners
        see it after the next sync."""
        if not state.pending_activity:
            return
        doc = self._doc_by_key(uiapp, state.key)
        if doc is None or doc.IsReadOnly:
            return
        pending = dict(state.pending_activity)
        now = common.now_iso()

        def change(record):
            for (ws, kind), n in pending.items():
                record['activity'].append({'t': now, 'ws': int(ws), 'n': int(n), 'k': kind})
        try:
            self._edit_my_record(uiapp, state.key, 'Share activity', change)
            state.pending_activity = {}
        except Exception:
            # model busy (edit mode, element owned by someone...): try later
            state.last_activity_time = time.time()

    # ------------------------------------------------------------------
    # Idling
    # ------------------------------------------------------------------
    def on_idling(self, sender, args):
        if not self.alive():
            return
        try:
            more = self._idle(sender)
            if more:
                args.SetRaiseWithoutDelay()
        except Exception:
            _log('idling: ' + traceback.format_exc())

    def _idle(self, uiapp):
        more = False
        # settings / mapping changed by a button
        cfg_ver = common.shared_get('CFG_VER', 0)
        if cfg_ver != self.cfg_ver:
            self.cfg_ver = cfg_ver
            self.settings = common.load_settings()
        map_ver = common.shared_get('MAP_VER', 0)
        if map_ver != self.map_ver:
            self.map_ver = map_ver
            try:
                for doc in uiapp.Application.Documents:
                    if common.eligible(doc):
                        self.refresh_doc(doc)
            except Exception:
                _log('refresh: ' + traceback.format_exc())

        if self.api_queue:
            self.run_api_queue(uiapp)

        while self.ui_queue:
            self.notifier.show(self.ui_queue.pop(0))

        if self.activity_buffer:
            common.append_activity(self.activity_buffer)
            self.activity_buffer = []

        if not self.live():
            return more

        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document if uidoc is not None else None
        state = self.state_for(doc) if doc is not None else None
        if state is None:
            return more

        now = time.time()
        # follow mode: switch once the placing pauses
        if state.pending_switch is not None:
            if now - state.last_add_time >= FOLLOW_DELAY:
                target = state.pending_switch
                state.pending_switch = None
                try:
                    ws = core.workset_by_id(doc, target)
                    if ws is not None and core.owned_by_other(ws, state.me):
                        self.notifier.show(Notice(
                            'Kept your active workset',
                            '"{}" is owned by {}.'.format(ws.Name, ws.Owner), KIND_WARN,
                            key='follow-blocked-{}'.format(target)))
                    elif ws is not None and core.active_workset_id(doc) != target:
                        core.set_active(doc, target)
                        if self.settings.get('follow_notice'):
                            self.notifier.show(Notice('Active workset: {}'.format(ws.Name), '',
                                                      KIND_SUCCESS, seconds=2,
                                                      key='follow-{}'.format(target)))
                except Exception:
                    # a command is still running: try again shortly (give up after a while)
                    state.switch_tries += 1
                    if state.switch_tries < 15:
                        state.pending_switch = target
                        state.last_add_time = now
                        more = True
            else:
                more = True

        # active workset changed: warn if it belongs to someone else
        active = core.active_workset_id(doc)
        if active != state.last_active:
            state.prev_active = state.last_active
            state.last_active = active
            if state.prev_active is not None and self.settings.get('warn_others', True):
                status = store.ws_status(state.claims, active, state.me)
                if status[0] == store.STATUS_OTHERS and active not in state.muted_ws:
                    state.warned_ws[active] = now
                    self.notifier.show(self._others_notice(doc, state, active, status, 0, 0, True))
            if state.streak_ws == active:
                state.streak_count = 0

        # share activity on others' worksets
        if state.pending_activity and now - state.last_activity_time >= ACTIVITY_DEBOUNCE:
            self._share_activity(uiapp, state)
        return more

    # ------------------------------------------------------------------
    # Other events
    # ------------------------------------------------------------------
    def on_doc_opened(self, sender, args):
        if not self.alive():
            return
        try:
            doc = args.Document
            if common.eligible(doc):
                self.refresh_doc(doc, announce=True)
        except Exception:
            _log('opened: ' + traceback.format_exc())

    def on_doc_closing(self, sender, args):
        if not self.alive():
            return
        try:
            doc = args.Document
            key = common.doc_key(doc)
            if key in self.docs:
                del self.docs[key]
            if self.updater is not None:
                UpdaterRegistry.RemoveDocumentTriggers(self.updater.GetUpdaterId(), doc)
        except Exception:
            pass

    def on_synced(self, sender, args):
        if not self.alive():
            return
        try:
            doc = args.Document
            common.shared_set('LAST_SYNC', common.now_iso())
            if common.eligible(doc):
                self.refresh_doc(doc, announce=True)
        except Exception:
            _log('synced: ' + traceback.format_exc())

    def on_family_loaded(self, sender, args):
        if not self.alive() or not self.live():
            return
        if not self.settings.get('warn_family_load', True):
            return
        try:
            doc = args.Document
            state = self.state_for(doc)
            if state is None:
                return
            family = doc.GetElement(args.NewFamilyId)
            category = family.FamilyCategory if family is not None else None
            if category is None:
                return
            cat = common.eid_int(category.Id)
            if cat in state.mapping or cat in state.never or cat in state.notified_cats:
                return
            infos = core.mappable_categories(doc)
            if str(cat) not in infos:
                return
            state.notified_cats.add(cat)
            active = core.active_workset_id(doc)
            self.ui_queue.append(self._unmapped_notice(doc, state, cat, category.Name, active,
                                                       True, args.FamilyName))
        except Exception:
            _log('family: ' + traceback.format_exc())

    # ------------------------------------------------------------------
    # After open / sync: what changed since I last looked
    # ------------------------------------------------------------------
    def _compare_with_seen(self, doc, state, announce):
        me = state.me
        seen = common.get_seen(state.key)
        first_time = seen is None
        seen = seen or {}
        mine_ws = set(store.my_worksets(state.claims, me))

        # others' activity on my worksets
        last_t = seen.get('activity_t', '')
        newest = last_t
        work = {}
        for user, rec in state.records.items():
            if user == me:
                continue
            for item in rec.get('activity') or []:
                t = item.get('t') or ''
                if t > newest:
                    newest = t
                if t <= last_t:
                    continue
                try:
                    ws = int(item.get('ws'))
                except Exception:
                    continue
                if ws not in mine_ws:
                    continue
                work_key = (user, ws)
                work[work_key] = work.get(work_key, 0) + int(item.get('n') or 0)

        # new co-owners of my worksets
        old_co = seen.get('co', {})
        new_co = {}
        joined = []
        for ws in mine_ws:
            entry = state.claims.get(str(ws)) or {}
            users = sorted(set((entry.get(store.CLAIM_PRIVATE) or []) +
                               (entry.get(store.CLAIM_SHARED) or [])) - set([me]))
            new_co[str(ws)] = users
            for user in users:
                if user not in (old_co.get(str(ws)) or []):
                    joined.append((user, ws))

        adopted = sorted(c for c, src in state.sources.items() if src[0] == 'adopted')
        old_adopted = set(seen.get('adopted', []))
        new_adopted = [c for c in adopted if c not in old_adopted]
        new_conflicts = sorted(c for c, info in state.conflicts.items() if info.get('new'))
        old_conflicts = set(seen.get('conflicts', []))

        common.set_seen(state.key, {
            'activity_t': newest, 'co': new_co, 'adopted': adopted,
            'conflicts': new_conflicts,
        })
        if not announce or not self.live():
            return

        if self.settings.get('notify_owner', True) and not first_time:
            for (user, ws), n in sorted(work.items())[:4]:
                self.ui_queue.append(Notice(
                    '{} worked on your workset'.format(user),
                    '{} element(s) on "{}" since your last sync.'.format(n, self.ws_name(state, ws)),
                    KIND_WARN, key='owner-{}-{}'.format(user, ws)))
                self.activity_buffer.append({
                    't': common.now_iso(), 'kind': 'others',
                    'text': '{} worked on {} element(s) of "{}"'.format(user, n, self.ws_name(state, ws)),
                    'model': doc.Title})
            for user, ws in joined[:4]:
                self.ui_queue.append(Notice(
                    '{} now works on "{}" too'.format(user, self.ws_name(state, ws)),
                    'They marked your workset as theirs as well.', KIND_INFO,
                    key='joined-{}-{}'.format(user, ws)))
                self.activity_buffer.append({
                    't': common.now_iso(), 'kind': 'claims',
                    'text': '{} joined "{}"'.format(user, self.ws_name(state, ws)),
                    'model': doc.Title})

        if self.settings.get('notify_mapping', True):
            if new_adopted and not first_time:
                users = set()
                for c in new_adopted:
                    users.update(state.sources[c][1])
                self.ui_queue.append(Notice(
                    '{} mapping(s) adopted'.format(len(new_adopted)),
                    'From {}. Categories you had not mapped now follow theirs.'.format(
                        ', '.join(sorted(users))), KIND_INFO, key='adopted'))
            fresh = [c for c in new_conflicts if c not in old_conflicts]
            if fresh:
                self.ui_queue.append(Notice(
                    '{} mapping conflict(s)'.format(len(fresh)),
                    'Someone maps these categories to a different workset than you. '
                    'Open Workset Manager > Mapping to keep yours or use theirs.',
                    KIND_WARN, key='conflicts'))


# ==========================================================================
def start(uiapp):
    """Called from startup.py. Stops a watcher left by a pyRevit reload."""
    old_stop = common.shared_get('STOP')
    if old_stop is not None:
        try:
            old_stop.Invoke()
        except Exception:
            pass
        common.shared_set('STOP', None)
    try:
        watcher = Watcher(uiapp)
        watcher.start()
        return watcher
    except Exception:
        common.shared_set('RUNNING', False)
        common.shared_set('ERROR', traceback.format_exc())
        raise
