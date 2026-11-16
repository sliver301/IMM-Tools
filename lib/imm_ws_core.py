# -*- coding: utf-8 -*-
"""IMM Worksets: workset operations, category lists and auto-mapping."""
import re

from System import Enum
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, CategoryType, DeleteWorksetOption,
    DeleteWorksetSettings, ElementWorksetFilter, FilteredElementCollector,
    FilteredWorksetCollector, RelinquishOptions, SynchronizeWithCentralOptions,
    Transaction, TransactWithCentralOptions, Workset, WorksetId, WorksetKind,
    WorksetTable, WorksharingUtils
)

import imm_ws_common as common

TXN = common.TXN_PREFIX


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------
def run_in_transaction(doc, name, func):
    t = Transaction(doc, '{}: {}'.format(TXN, name))
    t.Start()
    try:
        result = func()
        t.Commit()
        return result
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise


def _flex(doc, name, func):
    """Some workset calls want a transaction and some refuse one. Try with a
    transaction first, then without."""
    try:
        return run_in_transaction(doc, name, func)
    except Exception as first:
        try:
            return func()
        except Exception as second:
            message = str(second)
            if str(first) != message:
                message = '{}\n{}'.format(first, second)
            raise Exception(message)


# --------------------------------------------------------------------------
# Worksets
# --------------------------------------------------------------------------
def user_worksets(doc):
    items = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    items.sort(key=lambda ws: ws.Name.lower())
    return items


def workset_by_id(doc, ws_id):
    try:
        ws = doc.GetWorksetTable().GetWorkset(WorksetId(int(ws_id)))
        if ws is not None and ws.Kind == WorksetKind.UserWorkset:
            return ws
    except Exception:
        pass
    return None


def workset_by_name(doc, name):
    wanted = (name or '').strip().lower()
    for ws in user_worksets(doc):
        if ws.Name.strip().lower() == wanted:
            return ws
    return None


def active_workset_id(doc):
    try:
        return doc.GetWorksetTable().GetActiveWorksetId().IntegerValue
    except Exception:
        return -1


def set_active(doc, ws_id):
    table = doc.GetWorksetTable()
    target = WorksetId(int(ws_id))
    try:
        table.SetActiveWorksetId(target)
    except Exception:
        run_in_transaction(doc, 'Set active workset',
                           lambda: table.SetActiveWorksetId(target))


def owned_by_other(ws, me):
    return bool(ws.Owner) and ws.Owner != me


def can_receive(ws, me):
    """Can this user put elements on the workset right now?"""
    return ws is not None and ws.Kind == WorksetKind.UserWorkset and not owned_by_other(ws, me)


def count_elements(doc, ws_id):
    try:
        flt = ElementWorksetFilter(WorksetId(int(ws_id)), False)
        return FilteredElementCollector(doc).WherePasses(flt) \
            .WhereElementIsNotElementType().GetElementCount()
    except Exception:
        return 0


def name_is_free(doc, name):
    try:
        return WorksetTable.IsWorksetNameUnique(doc, name)
    except Exception:
        return workset_by_name(doc, name) is None


def create_workset(doc, name):
    name = (name or '').strip()
    if not name:
        raise Exception('Type a name for the new workset.')
    if not name_is_free(doc, name):
        raise Exception('A workset called "{}" already exists.'.format(name))
    return run_in_transaction(doc, 'Create workset',
                              lambda: Workset.Create(doc, name))


def rename_workset(doc, ws_id, name):
    name = (name or '').strip()
    if not name:
        raise Exception('Type the new name.')
    if not name_is_free(doc, name):
        raise Exception('A workset called "{}" already exists.'.format(name))
    _flex(doc, 'Rename workset',
          lambda: WorksetTable.RenameWorkset(doc, WorksetId(int(ws_id)), name))


def delete_workset(doc, ws_id, move_to_id=None):
    if move_to_id is not None:
        settings = DeleteWorksetSettings(DeleteWorksetOption.MoveElementsToWorkset,
                                         WorksetId(int(move_to_id)))
    else:
        settings = DeleteWorksetSettings()
        settings.DeleteWorksetOption = DeleteWorksetOption.DeleteAllElements
    wid = WorksetId(int(ws_id))
    try:
        if not WorksetTable.CanDeleteWorkset(doc, wid, settings):
            raise Exception('Revit does not allow deleting this workset right now. '
                            'It must be editable by you (or free), it cannot be the '
                            'active workset, and nobody may have its elements borrowed.')
    except Exception as ex:
        if 'Revit does not allow' in str(ex):
            raise
    _flex(doc, 'Delete workset', lambda: WorksetTable.DeleteWorkset(doc, wid, settings))


def checkout(doc, ws_ids):
    wanted = List[WorksetId]([WorksetId(int(i)) for i in ws_ids])
    got = WorksharingUtils.CheckoutWorksets(doc, wanted)
    return set(w.IntegerValue for w in got)


def sync(doc, comment='', relinquish_everything=False):
    twc = TransactWithCentralOptions()
    swc = SynchronizeWithCentralOptions()
    swc.SetRelinquishOptions(RelinquishOptions(relinquish_everything))
    swc.SaveLocalBefore = False
    swc.SaveLocalAfter = True
    swc.Comment = comment or 'IMM Workset Manager'
    doc.SynchronizeWithCentral(twc, swc)


def relinquish_all(doc):
    return WorksharingUtils.RelinquishOwnership(
        doc, RelinquishOptions(True), TransactWithCentralOptions())


def owned_by_me(doc, me):
    return [ws for ws in user_worksets(doc) if ws.Owner == me]


# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
EXTRA_BICS = ['OST_Grids', 'OST_Levels', 'OST_RvtLinks', 'OST_VolumeOfInterest',
              'OST_CLines']

DATUM_BICS = set(EXTRA_BICS)

# model categories whose elements are not placed by hand on a user workset
SKIP_BICS = set([
    'OST_Materials', 'OST_Sheets', 'OST_ProjectInformation', 'OST_PipeSegments',
    'OST_HVAC_Zones', 'OST_ElectricalLoadClassifications', 'OST_PipeMaterials',
    'OST_ColorFillSchema', 'OST_SectionBox', 'OST_Viewers', 'OST_Views',
    'OST_AnalyticalNodes', 'OST_MEPSystemZone', 'OST_ElectricalDemandFactorDefinitions',
])

STRUCT_WORDS = ('Structural', 'Rebar', 'AreaRein', 'PathRein', 'FabricArea',
                'FabricReinforcement', 'StructConnection', 'Truss', 'Coupler',
                'Joist', 'FoundationSlab')
MEP_WORDS = ('Duct', 'Pipe', 'Conduit', 'CableTray', 'Sprinkler', 'Mechanical',
             'Electrical', 'Plumbing', 'Lighting', 'Fire', 'Communication',
             'Data', 'Security', 'NurseCall', 'Telephone', 'Fabrication',
             'AirTerminal', 'Wire', 'Switch', 'MEP', 'HVAC', 'Plumbing')

DISCIPLINES = ['Architecture', 'Structure', 'MEP', 'Datums & Links']


def bic_name(category):
    try:
        bic = category.BuiltInCategory
        if bic != BuiltInCategory.INVALID:
            return str(bic)
    except Exception:
        pass
    try:
        value = common.eid_int(category.Id)
        return str(Enum.ToObject(BuiltInCategory, value))
    except Exception:
        return ''


def discipline_of(bic):
    if bic in DATUM_BICS:
        return 'Datums & Links'
    name = bic.replace('OST_', '')
    for word in STRUCT_WORDS:
        if word in name:
            return 'Structure'
    for word in MEP_WORDS:
        if word in name:
            return 'MEP'
    return 'Architecture'


class CategoryInfo(object):
    def __init__(self, category):
        self.id = common.eid_int(category.Id)
        self.key = str(self.id)
        self.name = category.Name
        self.bic = bic_name(category)
        self.discipline = discipline_of(self.bic)
        self.category = category


def mappable_categories(doc):
    out = {}
    extras = set(EXTRA_BICS)
    for cat in doc.Settings.Categories:
        try:
            if cat.Parent is not None:
                continue
            # imported CAD files (one category per DWG) have non built-in ids
            if common.eid_int(cat.Id) > 0:
                continue
            bic = bic_name(cat)
            if not bic or bic in SKIP_BICS:
                continue
            if cat.CategoryType == CategoryType.Model or bic in extras:
                if cat.Name.startswith('<'):
                    continue
                info = CategoryInfo(cat)
                out[info.key] = info
        except Exception:
            continue
    return out


def category_counts(doc, categories):
    counts = {}
    for key, info in categories.items():
        try:
            counts[key] = FilteredElementCollector(doc).OfCategoryId(info.category.Id) \
                .WhereElementIsNotElementType().GetElementCount()
        except Exception:
            counts[key] = 0
    return counts


def is_mappable_element(doc, el):
    """Elements whose workset the user can choose (no views, annotations,
    types or sub-components)."""
    try:
        if el is None or el.ViewSpecific or el.Category is None:
            return False
        ws = doc.GetWorksetTable().GetWorkset(el.WorksetId)
        if ws is None or ws.Kind != WorksetKind.UserWorkset:
            return False
        return True
    except Exception:
        return False


def partition_param(el):
    try:
        param = el.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if param is not None and not param.IsReadOnly:
            return param
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# Auto-mapping
# --------------------------------------------------------------------------
def learn_from_model(doc, categories, counts, progress=None):
    """For every used category, the workset most of its elements are on.
    {cat: (ws_id, percent)}"""
    proposals = {}
    uids = set(w.Id.IntegerValue for w in user_worksets(doc))
    used = [k for k in categories if counts.get(k, 0) > 0]
    for index, key in enumerate(used):
        if progress:
            progress(index, len(used))
        tally = {}
        total = 0
        try:
            collector = FilteredElementCollector(doc).OfCategoryId(categories[key].category.Id) \
                .WhereElementIsNotElementType()
            for el in collector:
                if el.ViewSpecific:
                    continue
                ws = el.WorksetId.IntegerValue
                tally[ws] = tally.get(ws, 0) + 1
                total += 1
        except Exception:
            continue
        tally = dict((ws, n) for ws, n in tally.items() if ws in uids)
        if not tally or total == 0:
            continue
        best = max(tally.items(), key=lambda item: item[1])
        proposals[key] = (best[0], int(round(100.0 * best[1] / total)))
    return proposals


# Name matching -----------------------------------------------------------
# Words and abbreviations people use in workset names, per category.
ABBREVIATIONS = {
    'OST_Walls': ['wall', 'wal', 'wl', 'wll', 'wls'],
    'OST_Doors': ['door', 'dor', 'dr', 'drs', 'dors', 'doo'],
    'OST_Windows': ['window', 'win', 'wn', 'wnd', 'wdw', 'wind', 'wins'],
    'OST_Floors': ['floor', 'flr', 'fl', 'slab', 'slb', 'sb', 'flooring', 'screed', 'topping'],
    'OST_Ceilings': ['ceiling', 'clg', 'ceil', 'cei', 'soffit'],
    'OST_Roofs': ['roof', 'rf', 'rof', 'roofing'],
    'OST_Columns': ['column', 'col', 'clm', 'clmn', 'cols', 'clms'],
    'OST_StructuralColumns': ['column', 'col', 'clm', 'clmn', 'cols', 'clms', 'sc'],
    'OST_StructuralFraming': ['beam', 'bm', 'bms', 'framing', 'frm', 'frame', 'girder', 'purlin', 'bracing'],
    'OST_StructuralFoundation': ['foundation', 'fdn', 'fnd', 'fdtn', 'found', 'footing', 'ftg',
                                 'raft', 'pile', 'pilecap', 'pc', 'mat'],
    'OST_Stairs': ['stair', 'stairs', 'stairway', 'staircase', 'stc'],
    'OST_StairsRailing': ['railing', 'rail', 'rlg', 'rails', 'handrail', 'hr', 'balustrade', 'guardrail'],
    'OST_Ramps': ['ramp', 'rmp'],
    'OST_CurtainWallPanels': ['curtain', 'cw', 'cwall', 'facade', 'fcd', 'fac', 'glazing', 'cladding', 'envelope'],
    'OST_CurtainWallMullions': ['curtain', 'cw', 'cwall', 'facade', 'fcd', 'fac', 'mullion', 'mull',
                                'glazing', 'cladding', 'envelope'],
    'OST_Furniture': ['furniture', 'furn', 'fur', 'ffe', 'ff'],
    'OST_FurnitureSystems': ['furniture', 'furn', 'fur', 'ffe'],
    'OST_Casework': ['casework', 'cwk', 'joinery', 'millwork', 'cabinet', 'kitchen'],
    'OST_GenericModel': ['generic', 'gm', 'gen'],
    'OST_Mass': ['mass', 'massing'],
    'OST_Toposolid': ['topo', 'toposolid', 'topography', 'terrain', 'site'],
    'OST_Topography': ['topo', 'topography', 'terrain', 'site'],
    'OST_Site': ['site'],
    'OST_Parking': ['parking', 'park', 'prk'],
    'OST_Planting': ['planting', 'plant', 'landscape', 'landscaping', 'lsc', 'trees', 'tree'],
    'OST_Entourage': ['entourage', 'ent', 'people'],
    'OST_SpecialityEquipment': ['specialty', 'speciality', 'spec', 'equipment', 'eqp', 'equip'],
    'OST_PlumbingFixtures': ['plumbing', 'plumb', 'plb', 'sanitary', 'san', 'fixture', 'wc'],
    'OST_LightingFixtures': ['lighting', 'light', 'ltg', 'lgt', 'lights'],
    'OST_LightingDevices': ['lighting', 'light', 'ltg', 'switch'],
    'OST_ElectricalFixtures': ['electrical', 'elec', 'ele', 'power', 'socket'],
    'OST_ElectricalEquipment': ['electrical', 'elec', 'ele', 'power', 'panel', 'db'],
    'OST_MechanicalEquipment': ['mechanical', 'mech', 'mec', 'hvac', 'equipment', 'eqp', 'equip', 'plant'],
    'OST_DuctCurves': ['duct', 'dct', 'ducts', 'ductwork', 'hvac'],
    'OST_DuctFitting': ['duct', 'dct', 'ductwork', 'hvac'],
    'OST_DuctAccessory': ['duct', 'dct', 'ductwork', 'hvac'],
    'OST_DuctTerminal': ['duct', 'dct', 'hvac', 'diffuser', 'grille', 'terminal', 'air'],
    'OST_FlexDuctCurves': ['duct', 'dct', 'ductwork', 'hvac'],
    'OST_PipeCurves': ['pipe', 'pp', 'pipes', 'piping', 'plumbing', 'plb', 'drainage', 'water'],
    'OST_PipeFitting': ['pipe', 'pp', 'piping', 'plumbing', 'plb'],
    'OST_PipeAccessory': ['pipe', 'pp', 'piping', 'plumbing', 'plb', 'valve'],
    'OST_FlexPipeCurves': ['pipe', 'pp', 'piping', 'plumbing'],
    'OST_Sprinklers': ['sprinkler', 'spr', 'sprk', 'fire', 'fp', 'ff', 'firefighting'],
    'OST_CableTray': ['cable', 'tray', 'ct', 'cabletray', 'containment'],
    'OST_CableTrayFitting': ['cable', 'tray', 'ct', 'cabletray', 'containment'],
    'OST_Conduit': ['conduit', 'cnd', 'cdt', 'containment'],
    'OST_ConduitFitting': ['conduit', 'cnd', 'cdt', 'containment'],
    'OST_FireAlarmDevices': ['fire', 'alarm', 'fa'],
    'OST_Grids': ['grid', 'grd', 'datum', 'datums'],
    'OST_Levels': ['level', 'lvl', 'lev', 'datum', 'datums'],
    'OST_CLines': ['reference', 'ref', 'rp', 'datum', 'datums'],
    'OST_VolumeOfInterest': ['scope', 'scopebox', 'datum', 'datums'],
    'OST_RvtLinks': ['link', 'links', 'lnk', 'rvt', 'linked'],
    'OST_Rooms': ['room', 'rm', 'rooms'],
    'OST_Lines': ['line', 'lines', 'ln', 'detail'],
    'OST_ShaftOpening': ['shaft', 'opening', 'opn'],
    'OST_Rebar': ['rebar', 'reinforcement', 'reinf', 'rft', 'rbr'],
    'OST_AreaRein': ['rebar', 'reinforcement', 'reinf', 'rft'],
    'OST_PathRein': ['rebar', 'reinforcement', 'reinf', 'rft'],
    'OST_FabricAreas': ['rebar', 'reinforcement', 'reinf', 'rft', 'fabric', 'mesh'],
    'OST_FabricReinforcement': ['rebar', 'reinforcement', 'reinf', 'rft', 'fabric', 'mesh'],
    'OST_StructConnections': ['connection', 'conn', 'steel'],
}

# words in a workset name that say which discipline it belongs to
DISCIPLINE_WORDS = {
    'Architecture': ['arc', 'arch', 'architecture', 'architectural', 'ar', 'archi', 'int', 'interior', 'finish', 'fin'],
    'Structure': ['str', 'st', 'stl', 'struct', 'structure', 'structural', 'conc', 'concrete', 'rc'],
    'MEP': ['mep', 'mech', 'elec', 'plumb', 'hvac', 'services', 'fp', 'me'],
}
# categories that belong to more than one discipline
SHARED_DISCIPLINES = {
    'OST_Floors': ('Architecture', 'Structure'),
    'OST_Walls': ('Architecture', 'Structure'),
    'OST_Stairs': ('Architecture', 'Structure'),
    'OST_Roofs': ('Architecture', 'Structure'),
    'OST_Ramps': ('Architecture', 'Structure'),
    'OST_GenericModel': ('Architecture', 'Structure', 'MEP'),
    'OST_Columns': ('Architecture',),
}


def _singular(word):
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 4 and word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word


def name_tokens(text):
    """'BES_STR_CLM' -> ['bes', 'str', 'clm']; 'FinishFloor' -> ['finish', 'floor']."""
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text or '')
    text = re.sub(r'([A-Za-z])([0-9])', r'\1 \2', text)
    out = []
    for word in re.split(r'[^A-Za-z0-9&]+', text.lower()):
        word = word.replace('&', '')
        if word:
            out.append(_singular(word))
    return out


def _norm(text):
    return ' '.join(name_tokens(text))


def _ws_discipline(tokens):
    found = set()
    for disc, words in DISCIPLINE_WORDS.items():
        if any(t in words for t in tokens):
            found.add(disc)
    return found


def _match(info, ws_tokens, ws_disc):
    """Score how well a workset name fits a category, with the reason.
    0 means no real match."""
    cat_words = set(name_tokens(info.name))
    keys = set(_singular(k) for k in ABBREVIATIONS.get(info.bic, []))
    score = 0.0
    why = None
    if ws_tokens and ws_tokens == name_tokens(info.name):
        return 5.0, 'same name'
    for token in ws_tokens:
        if len(token) >= 4 and token in cat_words and (token in keys or not keys):
            if score < 3:
                score, why = 3.0, '"{}" is in the name'.format(token)
        elif token in keys:
            if score < 2:
                if len(token) <= 4:
                    why = '{} = {}'.format(token.upper(), info.name)
                else:
                    why = '"{}" fits {}'.format(token, info.name)
                score = 2.0
    if not score:
        return 0, None
    allowed = SHARED_DISCIPLINES.get(info.bic, (info.discipline,))
    if ws_disc:
        if ws_disc & set(allowed):
            score += 0.5
        else:
            score -= 1.5
    return score, why


# --------------------------------------------------------------------------
# Types: a category can be split over several worksets by type
# --------------------------------------------------------------------------
TYPE_PREFIX = 't'


def type_key(type_id):
    return '{}{}'.format(TYPE_PREFIX, int(type_id))


def is_type_key(key):
    return str(key).startswith(TYPE_PREFIX)


def type_id_of(key):
    return int(str(key)[len(TYPE_PREFIX):])


WALL_FUNCTIONS = {0: 'Interior', 1: 'Exterior', 2: 'Foundation', 3: 'Retaining',
                  4: 'Soffit', 5: 'Core-shaft'}


class TypeInfo(object):
    def __init__(self, key, cat_key, family, name, function=''):
        self.key = key
        self.id = type_id_of(key)
        self.cat_key = cat_key
        self.family = family or ''
        self.name = name or ''
        self.label = u'{}: {}'.format(self.family, self.name) if self.family else self.name
        self.function = function
        self.count = 0
        self.concepts = set()


def _type_names(el_type):
    family = ''
    try:
        family = el_type.FamilyName or ''
    except Exception:
        pass
    name = ''
    try:
        p = el_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        name = p.AsString() if p is not None else ''
    except Exception:
        pass
    if not name:
        try:
            name = el_type.Name
        except Exception:
            name = ''
    return family, name


def _type_function(el_type):
    """Wall function (Interior, Exterior, Retaining...), curtain walls and
    structural floors, read from the type itself."""
    words = []
    try:
        p = el_type.get_Parameter(BuiltInParameter.FUNCTION_PARAM)
        if p is not None and p.HasValue:
            words.append(WALL_FUNCTIONS.get(p.AsInteger(), ''))
    except Exception:
        pass
    try:
        if str(el_type.Kind) == 'Curtain':
            words.append('Curtain')
    except Exception:
        pass
    try:
        if el_type.IsFoundationSlab:
            words.append('Foundation')
    except Exception:
        pass
    return ' '.join(w for w in words if w)


def type_inventory(doc, categories, counts):
    """Types in use, per category: {cat_key: [TypeInfo, ...]} (most used
    first) and {type_key: TypeInfo}."""
    by_cat = {}
    by_key = {}
    for cat_key, info in categories.items():
        if not counts.get(cat_key):
            continue
        tally = {}
        try:
            collector = FilteredElementCollector(doc).OfCategoryId(info.category.Id) \
                .WhereElementIsNotElementType()
            for el in collector:
                try:
                    if el.ViewSpecific:
                        continue
                    tid = common.eid_int(el.GetTypeId())
                except Exception:
                    continue
                if tid > 0:
                    tally[tid] = tally.get(tid, 0) + 1
        except Exception:
            continue
        if len(tally) < 1:
            continue
        items = []
        for tid, n in tally.items():
            el_type = doc.GetElement(common.make_eid(tid))
            if el_type is None:
                continue
            family, name = _type_names(el_type)
            t = TypeInfo(type_key(tid), cat_key, family, name, _type_function(el_type))
            t.count = n
            t.concepts = type_concepts(info, t)
            items.append(t)
            by_key[t.key] = t
        items.sort(key=lambda t: (-t.count, t.label.lower()))
        by_cat[cat_key] = items
    return by_cat, by_key


# --------------------------------------------------------------------------
# Concepts: what a name means, whatever abbreviation it uses
# --------------------------------------------------------------------------
CONCEPTS = {
    'interior': ['int', 'interior', 'internal', 'inside', 'id', 'inner'],
    'exterior': ['ext', 'exterior', 'external', 'outside', 'outer'],
    'structure': ['str', 'stl', 'struct', 'structure', 'structural', 'rc', 'conc', 'concrete',
                  'shear', 'bearing', 'loadbearing', 'lb', 'reinforced'],
    'retaining': ['ret', 'retaining', 'retain', 'rtw', 'rw'],
    'foundation': ['fdn', 'fnd', 'fdtn', 'foundation', 'footing', 'ftg', 'raft', 'pile'],
    'finish': ['fin', 'finish', 'finishing', 'finishes', 'plaster', 'cladding', 'clad', 'tile',
               'tiling', 'paint', 'render', 'skim', 'stone', 'marble', 'granite', 'ceramic',
               'porcelain', 'screed', 'veneer', 'lining'],
    'partition': ['part', 'partition', 'prt', 'drywall', 'gyp', 'gypsum', 'stud', 'board'],
    'skirting': ['skirting', 'skirt', 'skt', 'baseboard', 'plinth'],
    'curtain': ['cw', 'curtain', 'glazing', 'glazed', 'glass', 'storefront', 'facade', 'fcd', 'mullion'],
    'masonry': ['blk', 'block', 'brick', 'masonry', 'cmu', 'aac', 'hollow'],
    'parapet': ['parapet', 'ppt'],
    'core': ['core', 'shaft', 'lift', 'elevator', 'stair'],
    'soffit': ['soffit', 'sof'],
    'insulation': ['insulation', 'ins', 'insul', 'thermal'],
    'fire': ['fire', 'fr', 'firerated', 'rated'],
    'wet': ['wet', 'toilet', 'wc', 'bath', 'kitchen'],
}
_CONCEPT_OF = {}
for _concept, _words in CONCEPTS.items():
    for _w in _words:
        _CONCEPT_OF.setdefault(_w, _concept)
_FUZZY_WORDS = [w for w in _CONCEPT_OF if len(w) >= 5]

# concepts a category already implies (no penalty, no evidence)
CATEGORY_CONCEPTS = {
    'Structure': set(['structure']),
}


def _close_word(token):
    """Typo-tolerant lookup: 'srtking' -> 'skirting'."""
    if len(token) < 5:
        return None
    import difflib
    best = difflib.get_close_matches(token, _FUZZY_WORDS, n=1, cutoff=0.78)
    return best[0] if best else None


def concepts_of(tokens):
    found = set()
    for t in tokens:
        c = _CONCEPT_OF.get(t)
        if c is None:
            near = _close_word(t)
            c = _CONCEPT_OF.get(near) if near else None
        if c:
            found.add(c)
    return found


def type_concepts(cat_info, t):
    tokens = name_tokens(t.family) + name_tokens(t.name) + name_tokens(t.function)
    found = concepts_of(tokens)
    found |= CATEGORY_CONCEPTS.get(cat_info.discipline, set())
    return found


def _workset_profiles(doc):
    out = []
    for ws in user_worksets(doc):
        tokens = name_tokens(ws.Name)
        out.append({'id': ws.Id.IntegerValue, 'name': ws.Name, 'tokens': tokens,
                    'disc': _ws_discipline(tokens), 'concepts': concepts_of(tokens)})
    return out


def _implied(info):
    """Concepts the category itself carries: Structure categories mean
    structure, Curtain Panels mean curtain, and so on."""
    implied = set(CATEGORY_CONCEPTS.get(info.discipline, set()))
    try:
        implied |= concepts_of(name_tokens(info.name))
    except Exception:
        pass
    return implied


def _category_score(info, ws):
    """How well a workset fits the category as a whole. Worksets with extra
    meaning (retaining, finish...) are kept for the types that need them."""
    score, why = _match(info, ws['tokens'], ws['disc'])
    if not score:
        return 0, None
    implied = _implied(info)
    extra = ws['concepts'] - implied
    return score - 1.0 * len(extra), why


def _type_score(info, t, ws, cat_score):
    shared = (t.concepts & ws['concepts'])
    implied = _implied(info)
    evidence = shared - implied
    missing = ws['concepts'] - t.concepts - implied
    score = max(cat_score, 0) + 3.0 * len(evidence) - 3.0 * len(missing)
    if evidence:
        score += 1.0
    if not cat_score and not evidence:
        return 0, None
    if evidence:
        why = 'type says {}'.format(', '.join(sorted(evidence)))
    else:
        why = None
    return score, why


def auto_map_by_name(doc, categories, counts=None, types_by_cat=None, current=None):
    """Suggest worksets from their names.

    Categories get the workset whose name fits the category best (DOR =
    Doors, CLM = Columns...). Types get their own workset when their name or
    function points somewhere more specific (an interior plaster wall type
    -> INT_WAL_FINISH, a retaining wall type -> STR_RETAINING_WALLS).
    Only real matches, and only what is used in the model when counts are
    given. Returns {key: (ws_id, percent, reason)} where key is a category
    key or a type key."""
    worksets = _workset_profiles(doc)
    current = current or {}
    proposals = {}
    # worksets whose name clearly spells out a category ("Finish Floor" ->
    # Floors) are kept for that category's types; a Mass type called
    # "FIN RIBBON" must not land on a floor finish workset.
    named = {}
    for key, info in categories.items():
        for ws in worksets:
            base, _why = _match(info, ws['tokens'], ws['disc'])
            if base >= 3:
                named.setdefault(ws['id'], set()).add(key)
    for key, info in categories.items():
        if counts is not None and not counts.get(key, 0):
            continue
        scored = []
        raw = {}
        for ws in worksets:
            base, why = _match(info, ws['tokens'], ws['disc'])
            score, why2 = _category_score(info, ws)
            raw[ws['id']] = base if base else 0
            if score >= 2:
                scored.append((score, ws['id'], why2 or why))
        scored.sort(key=lambda item: -item[0])
        cat_target = None
        if scored and not (len(scored) > 1 and scored[1][0] == scored[0][0]):
            score, ws_id, why = scored[0]
            proposals[key] = (ws_id, int(min(99, score * 20)), why)
            cat_target = ws_id
        if current.get(key) is not None:
            cat_target = current.get(key)

        # types of this category
        for t in (types_by_cat or {}).get(key, []):
            best = []
            for ws in worksets:
                owners = named.get(ws['id'])
                if owners and key not in owners:
                    continue
                score, why = _type_score(info, t, ws, raw.get(ws['id'], 0))
                if score >= 2.5:
                    best.append((score, ws['id'], why))
            if not best:
                continue
            best.sort(key=lambda item: -item[0])
            if len(best) > 1 and best[1][0] == best[0][0]:
                continue
            score, ws_id, why = best[0]
            if not why or ws_id == cat_target:
                continue
            proposals[t.key] = (ws_id, int(min(99, score * 12)), why)
    return proposals
