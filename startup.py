# -*- coding: utf-8 -*-
"""IMM startup.
1. Cleanup: removes the old ribbon test items ("Probe check box") from the IMM VV Settings dropdown.
   Safe to keep; it does nothing once they are gone.
2. Starts the live workset watcher (IMM Workset Manager). A failure here never
   blocks Revit; the reason is shown by the Live Watcher button."""
try:
    import clr
    clr.AddReference('AdWindows')
    import Autodesk.Windows as aw

    def _clean(items):
        for it in list(items):
            if str(getattr(it, 'Id', '') or '').startswith('IMM_PROBE_'):
                items.Remove(it)
                continue
            try:
                sub = it.Items
            except Exception:
                sub = None
            if sub is not None:
                _clean(sub)

    for tab in aw.ComponentManager.Ribbon.Tabs:
        if 'IMM' not in str(tab.Title or '') + str(tab.Id or ''):
            continue
        for panel in tab.Panels:
            _clean(panel.Source.Items)
except Exception:
    pass

try:
    import imm_ws_watch
    imm_ws_watch.start(__revit__)
except Exception:
    import traceback
    try:
        import imm_ws_common
        imm_ws_common.shared_set('RUNNING', False)
        imm_ws_common.shared_set('ERROR', traceback.format_exc())
    except Exception:
        pass
