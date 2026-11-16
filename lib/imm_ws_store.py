# -*- coding: utf-8 -*-
"""IMM Worksets: data stored inside the model (Extensible Storage).

Every user who runs the plugin owns ONE DataStorage element holding a JSON
record: their mapping, their claims and the activity they want others to see.
One element per user means nobody is ever blocked by somebody else's checkout.
Everything travels with the model and reaches others on Sync. Nothing is ever
written beside the central file.

Record layout (JSON):
{
  "v": 1, "user": "karim", "saved": "2026-11-11T08:30:00",
  "mapping":  {"<category id>": <workset id>, ...},
  "never":    [<category id>, ...],
  "acked":    {"<category id>": [<their workset id>, ...]},
  "claims":   {"<workset id>": "private" | "shared"},
  "activity": [{"t": iso, "ws": <workset id>, "n": 12, "k": "add"|"edit"}]
}
"""
import json

import clr
from System import Guid, String

from Autodesk.Revit.DB import (
    BuiltInParameter, FilteredElementCollector, FilteredWorksetCollector,
    WorksetKind
)
from Autodesk.Revit.DB.ExtensibleStorage import (
    AccessLevel, DataStorage, Entity, Schema, SchemaBuilder
)

import imm_ws_common as common

SCHEMA_GUID = Guid('6f1d3c52-8a7e-4b8e-9d1a-3c4b5e6f7a81')
SCHEMA_NAME = 'IMMWorksetsUserData'
F_USER = 'User'
F_JSON = 'Json'

CONFIG_WORKSET = 'IMM_Config'
MAX_SHARED_ACTIVITY = 100

CLAIM_PRIVATE = 'private'
CLAIM_SHARED = 'shared'

STATUS_MINE = 'mine'
STATUS_SHARED = 'shared'
STATUS_OTHERS = 'others'
STATUS_FREE = 'free'


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def lookup_schema():
    try:
        return Schema.Lookup(SCHEMA_GUID)
    except Exception:
        return None


def get_schema():
    schema = lookup_schema()
    if schema is not None:
        return schema
    builder = SchemaBuilder(SCHEMA_GUID)
    builder.SetSchemaName(SCHEMA_NAME)
    builder.SetDocumentation('IMM Workset Manager: per-user mapping, claims and activity.')
    builder.SetReadAccessLevel(AccessLevel.Public)
    builder.SetWriteAccessLevel(AccessLevel.Public)
    builder.AddSimpleField(F_USER, clr.GetClrType(String))
    builder.AddSimpleField(F_JSON, clr.GetClrType(String))
    return builder.Finish()


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
def empty_record(user):
    return {
        'v': 1, 'user': user, 'saved': '',
        'mapping': {}, 'never': [], 'acked': {}, 'claims': {}, 'activity': [],
    }


def _normalize(data, user):
    rec = empty_record(user)
    if isinstance(data, dict):
        for key in rec:
            if key in data and data[key] is not None:
                rec[key] = data[key]
    # keys as strings, values as ints
    mapping = {}
    for key, value in (rec.get('mapping') or {}).items():
        try:
            mapping[str(int(key))] = int(value)
        except Exception:
            pass
    rec['mapping'] = mapping
    never = []
    for value in rec.get('never') or []:
        try:
            never.append(str(int(value)))
        except Exception:
            pass
    rec['never'] = sorted(set(never))
    acked = {}
    for key, values in (rec.get('acked') or {}).items():
        try:
            acked[str(int(key))] = [int(v) for v in values]
        except Exception:
            pass
    rec['acked'] = acked
    claims = {}
    for key, value in (rec.get('claims') or {}).items():
        if value in (CLAIM_PRIVATE, CLAIM_SHARED):
            try:
                claims[str(int(key))] = value
            except Exception:
                pass
    rec['claims'] = claims
    if not isinstance(rec.get('activity'), list):
        rec['activity'] = []
    rec['user'] = user
    return rec


def _storages(doc):
    schema = lookup_schema()
    if schema is None:
        return []
    out = []
    for ds in FilteredElementCollector(doc).OfClass(DataStorage):
        try:
            ent = ds.GetEntity(schema)
        except Exception:
            continue
        if ent is None or not ent.IsValid():
            continue
        try:
            user = ent.Get[String](F_USER)
            raw = ent.Get[String](F_JSON)
        except Exception:
            continue
        out.append((ds, user or '', raw or ''))
    return out


def read_all(doc):
    """{user: record} for every user who saved data in this model."""
    records = {}
    for ds, user, raw in _storages(doc):
        if not user:
            continue
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        rec = _normalize(data, user)
        rec['_eid'] = common.eid_int(ds.Id)
        old = records.get(user)
        if old is None or (rec.get('saved') or '') >= (old.get('saved') or ''):
            records[user] = rec
    return records


def read_user(doc, user):
    return read_all(doc).get(user) or empty_record(user)


def _config_workset_id(doc, me):
    for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
        if ws.Name == CONFIG_WORKSET:
            if not ws.Owner or ws.Owner == me:
                return ws.Id.IntegerValue
            return None
    return None


def write_user(doc, user, record):
    """Save a user's record. MUST be called inside an open transaction."""
    schema = get_schema()
    target = None
    for ds, owner, raw in _storages(doc):
        if owner == user:
            target = ds
            break
    if target is None:
        target = DataStorage.Create(doc)
        ws_id = _config_workset_id(doc, user)
        if ws_id is not None:
            try:
                param = target.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                if param is not None and not param.IsReadOnly:
                    param.Set(ws_id)
            except Exception:
                pass
    clean = {}
    for key, value in record.items():
        if not key.startswith('_'):
            clean[key] = value
    clean['user'] = user
    clean['saved'] = common.now_iso()
    clean['activity'] = (clean.get('activity') or [])[-MAX_SHARED_ACTIVITY:]
    ent = Entity(schema)
    ent.Set[String](F_USER, user)
    ent.Set[String](F_JSON, json.dumps(clean, sort_keys=True))
    target.SetEntity(ent)
    return target


# --------------------------------------------------------------------------
# Mapping merge between users
# --------------------------------------------------------------------------
def merge_mappings(records, me):
    """Combine everybody's mapping into the one this user works with.

    Returns (effective, sources, conflicts):
      effective  {cat: ws}
      sources    {cat: ('mine', []) | ('adopted', [users])}
      conflicts  {cat: {'mine': ws or None, 'theirs': {ws: [users]}, 'new': bool}}
    A category only I mapped -> mine. Mapped only by others, all agreeing ->
    adopted automatically. Mapped differently -> conflict, nothing changes.
    """
    mine = records.get(me) or empty_record(me)
    effective = {}
    sources = {}
    conflicts = {}
    for cat, ws in mine['mapping'].items():
        effective[cat] = ws
        sources[cat] = ('mine', [])

    others = {}
    for user, rec in records.items():
        if user == me:
            continue
        for cat, ws in rec['mapping'].items():
            others.setdefault(cat, {}).setdefault(ws, []).append(user)

    never = set(mine['never'])
    for cat, options in others.items():
        if cat in effective:
            theirs = dict((ws, users) for ws, users in options.items() if ws != effective[cat])
            if theirs:
                acked = set(mine['acked'].get(cat) or [])
                conflicts[cat] = {
                    'mine': effective[cat], 'theirs': theirs,
                    'new': any(ws not in acked for ws in theirs),
                }
        elif cat in never:
            continue
        elif len(options) == 1:
            ws, users = list(options.items())[0]
            effective[cat] = ws
            sources[cat] = ('adopted', sorted(users))
        else:
            conflicts[cat] = {'mine': None, 'theirs': options, 'new': True}
    return effective, sources, conflicts


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def claim_table(records):
    """{ws: {'private': [users], 'shared': [users]}}"""
    table = {}
    for user, rec in records.items():
        for ws, kind in rec['claims'].items():
            entry = table.setdefault(ws, {CLAIM_PRIVATE: [], CLAIM_SHARED: []})
            entry[kind].append(user)
    return table


def ws_status(table, ws, me):
    """(status, claimers, open_to_share) for a workset id (int or str)."""
    entry = table.get(str(ws))
    if not entry:
        return STATUS_FREE, [], False
    claimers = sorted(set(entry[CLAIM_PRIVATE] + entry[CLAIM_SHARED]))
    if not claimers:
        return STATUS_FREE, [], False
    open_to_share = bool(entry[CLAIM_SHARED])
    if me in claimers:
        if len(claimers) > 1:
            return STATUS_SHARED, claimers, open_to_share
        return STATUS_MINE, claimers, open_to_share
    return STATUS_OTHERS, claimers, open_to_share


def my_worksets(table, me):
    out = []
    for ws, entry in table.items():
        if me in entry[CLAIM_PRIVATE] or me in entry[CLAIM_SHARED]:
            try:
                out.append(int(ws))
            except Exception:
                pass
    return out


STATUS_LABELS = {
    STATUS_MINE: 'Mine',
    STATUS_SHARED: 'Shared',
    STATUS_OTHERS: 'Others',
    STATUS_FREE: 'Free',
}
