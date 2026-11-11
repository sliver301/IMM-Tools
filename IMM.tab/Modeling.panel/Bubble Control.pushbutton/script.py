"""Configure Grid and Level bubbles via a visual UI."""
__title__ = 'Bubble\nControl'
__author__ = 'IMM'

import os
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *

from pyrevit import forms
from pyrevit import script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

class SheetItem(object):
    def __init__(self, sheet, is_selected=False):
        self.Sheet = sheet
        self._is_selected = is_selected
        self.SheetNumber = sheet.SheetNumber
        self.SheetName = sheet.Name
        
    @property
    def IsSelected(self):
        return self._is_selected
        
    @IsSelected.setter
    def IsSelected(self, value):
        self._is_selected = value

class SheetSelectorWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.selected_sheets = None
        sheets = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
        self.all_sheets = sorted(list(sheets), key=lambda s: s.SheetNumber)
        self.sheet_sets = FilteredElementCollector(doc).OfClass(ViewSheetSet).ToElements()
        
        self.set_names = ["None"]
        self.set_dict = {}
        for sset in self.sheet_sets:
            self.set_names.append(sset.Name)
            self.set_dict[sset.Name] = sset
            
        self.cmbSets.ItemsSource = self.set_names
        self.cmbSets.SelectedIndex = 0
        
    def OnSetSelectionChanged(self, sender, args):
        sel_set_name = self.cmbSets.SelectedItem
        new_items = []
        if sel_set_name == "None":
            for sheet in self.all_sheets:
                new_items.append(SheetItem(sheet, False))
        else:
            sset = self.set_dict[sel_set_name]
            set_views_ids = [v.Id for v in sset.Views if isinstance(v, ViewSheet)]
            for sheet in self.all_sheets:
                if sheet.Id in set_views_ids:
                    new_items.append(SheetItem(sheet, True))
        self.lstSheets.ItemsSource = new_items

    def OnCancelClick(self, sender, args):
        self.selected_sheets = None
        self.Close()
        
    def OnOkClick(self, sender, args):
        current_source = self.lstSheets.ItemsSource
        self.selected_sheets = [item.Sheet for item in current_source if item.IsSelected]
        self.Close()

class BubbleControlWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.plugin_dir = os.path.dirname(__file__)
        self.images_dir = os.path.join(os.path.dirname(self.plugin_dir), "Resources", "Images")
        self.icons_dir = os.path.join(os.path.dirname(self.plugin_dir), "Resources", "icons")
        self.plans_img_dir = os.path.join(self.images_dir, "Plans")
        self.secs_img_dir = os.path.join(self.images_dir, "Sections")
        
        # Set align icons
        self.set_image_source(self.imgPlanAlignTop, os.path.join(self.icons_dir, "align_top.png"))
        self.set_image_source(self.imgPlanAlignBottom, os.path.join(self.icons_dir, "align_bottom.png"))
        self.set_image_source(self.imgPlanAlignLeft, os.path.join(self.icons_dir, "align_left.png"))
        self.set_image_source(self.imgPlanAlignRight, os.path.join(self.icons_dir, "align_right.png"))
        
        self.set_image_source(self.imgSecAlignTop, os.path.join(self.icons_dir, "align_top.png"))
        self.set_image_source(self.imgSecAlignBottom, os.path.join(self.icons_dir, "align_bottom.png"))
        self.set_image_source(self.imgSecAlignLeft, os.path.join(self.icons_dir, "align_left.png"))
        self.set_image_source(self.imgSecAlignRight, os.path.join(self.icons_dir, "align_right.png"))
        
        self._is_updating = False
        # Initial View logic
        self.selected_views = []
        self.update_view_selection()
        
        # Initial image load
        self.update_plan_image()
        self.update_sec_image()
        
    def get_image_name(self, prefix, top, bottom, left, right):
        """Generates exact filenames according to our convention"""
        if prefix == "Plan":
            mapping = {
                (False, False, False, False): "Plan - Empty.png",
                (True, False, False, False): "Plan - Top.png",
                (False, True, False, False): "Plan - Bottom.png",
                (False, False, True, False): "Plan - Left.png",
                (False, False, False, True): "Plan - Right.png",
                (True, True, False, False): "Plan - Top & Bottom.png",
                (False, False, True, True): "Plan - Left & Right.png",
                (True, False, True, False): "Plan - Top & Left.png",
                (True, False, False, True): "Plan - Top & Right.png",
                (False, True, True, False): "Plan - Bottom & Left.png",
                (False, True, False, True): "Plan - Bottom & Right.png",
                (True, True, True, False): "Plan - Top & Left & Bottom.png",
                (True, True, False, True): "Plan - Top & Right & Bottom.png",
                (True, False, True, True): "Plan - Top & Left & Right.png",
                (False, True, True, True): "Plan - Bottom & Left & Right.png",
                (True, True, True, True): "Plan - ALL.png"
            }
        else: # Section
            mapping = {
                (False, False, False, False): "Section - Empty.png",
                (True, False, False, False): "Section - Top.png",
                (False, True, False, False): "Section - Bottom.png",
                (False, False, True, False): "Section - Left.png",
                (False, False, False, True): "Section - Right.png",
                (True, True, False, False): "Section - Top & Bottom.png",
                (False, False, True, True): "Section - Left & Right.png",
                (True, False, True, False): "Section - Left & Top.png",
                (True, False, False, True): "Section - Right & Top.png",
                (False, True, True, False): "Section - Left & Bottom.png",
                (False, True, False, True): "Section - Right & Bottom.png",
                (True, True, True, False): "Section - Left & Top & Bottom.png",
                (True, True, False, True): "Section - Right & Top & Bottom.png",
                (True, False, True, True): "Section - Left & Right & Top.png",
                (False, True, True, True): "Section - Left & Right & Bottom.png",
                (True, True, True, True): "Section - ALL.png"
            }
        return mapping.get((top, bottom, left, right), "{0} - Empty.png".format(prefix))

    def update_plan_image(self):
        t = self.chkPlanTop.IsChecked
        b = self.chkPlanBottom.IsChecked
        l = self.chkPlanLeft.IsChecked
        r = self.chkPlanRight.IsChecked
        
        img_name = self.get_image_name("Plan", t, b, l, r)
        img_path = os.path.join(self.plans_img_dir, img_name)
        
        if os.path.exists(img_path):
            self.set_image_source(self.imgPlan, img_path)
            
    def update_sec_image(self):
        t = self.chkSecTop.IsChecked
        b = self.chkSecBottom.IsChecked
        l = self.chkSecLeft.IsChecked
        r = self.chkSecRight.IsChecked
        
        img_name = self.get_image_name("Section", t, b, l, r)
        img_path = os.path.join(self.secs_img_dir, img_name)
        
        if os.path.exists(img_path):
            self.set_image_source(self.imgSec, img_path)

    def OnPlanCheckChanged(self, sender, args):
        self.update_plan_image()
        
    def OnSecCheckChanged(self, sender, args):
        self.update_sec_image()
        
    def OnViewSelectorChanged(self, sender, args):
        if not hasattr(self, 'cmbViewSelector'): return
        if self._is_updating: return
        self.update_view_selection()
        
    def update_view_selection(self):
        self._is_updating = True
        sel_idx = self.cmbViewSelector.SelectedIndex
        views = []
        
        try:
            if sel_idx == 0: # Current View
                views = [doc.ActiveView]
            elif sel_idx == 1: # Selected Views
                sel_ids = uidoc.Selection.GetElementIds()
                views = [doc.GetElement(i) for i in sel_ids if isinstance(doc.GetElement(i), View)]
            elif sel_idx == 2: # Views on Sheets
                selector = SheetSelectorWindow(os.path.join(self.plugin_dir, 'sheet_selector.xaml'))
                selector.ShowDialog()
                
                if selector.selected_sheets is None:
                    # Cancelled, revert to Current View
                    self.cmbViewSelector.SelectedIndex = 0
                    views = [doc.ActiveView]
                else:
                    for sheet in selector.selected_sheets:
                        placed_view_ids = sheet.GetAllPlacedViews()
                        for v_id in placed_view_ids:
                            views.append(doc.GetElement(v_id))
            elif sel_idx == 3: # Manual Select
                views = forms.select_views(title="Select Views for Bubble Control")
                if not views:
                    # Revert to Current View
                    self.cmbViewSelector.SelectedIndex = 0
                    views = [doc.ActiveView]
                    
            self.selected_views = views
            
            # Check if views contain plans or sections
            has_plans = any(v.ViewType in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan] for v in views)
            has_secs = any(v.ViewType in [ViewType.Elevation, ViewType.Section] for v in views)
            
            self.grpPlans.IsEnabled = has_plans
            self.grpSections.IsEnabled = has_secs
        finally:
            self._is_updating = False

    def OnCancelClick(self, sender, args):
        self.Close()
        
    def apply_to_grids(self, view, t, b, l, r):
        grids = FilteredElementCollector(doc, view.Id).OfClass(Grid).ToElements()
        for grid in grids:
            if not grid.CanBeVisibleInView(view): continue
            
            curves = grid.GetCurvesInView(DatumExtentType.ViewSpecific, view)
            if not curves or curves.Count == 0: continue
            curve = curves[0]
            
            grid.SetDatumExtentType(DatumEnds.End0, view, DatumExtentType.ViewSpecific)
            grid.SetDatumExtentType(DatumEnds.End1, view, DatumExtentType.ViewSpecific)
            
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            vec = p1 - p0
            
            dot_right = vec.DotProduct(view.RightDirection)
            dot_up = vec.DotProduct(view.UpDirection)
            
            if abs(dot_right) > abs(dot_up):
                # Horizontal on screen (Left/Right ends)
                if dot_right > 0:
                    left_end, right_end = DatumEnds.End0, DatumEnds.End1
                else:
                    left_end, right_end = DatumEnds.End1, DatumEnds.End0
                
                if l: grid.ShowBubbleInView(left_end, view)
                else: grid.HideBubbleInView(left_end, view)
                
                if r: grid.ShowBubbleInView(right_end, view)
                else: grid.HideBubbleInView(right_end, view)
                
            else:
                # Vertical on screen (Top/Bottom ends)
                if dot_up > 0:
                    bottom_end, top_end = DatumEnds.End0, DatumEnds.End1
                else:
                    bottom_end, top_end = DatumEnds.End1, DatumEnds.End0
                    
                if b: grid.ShowBubbleInView(bottom_end, view)
                else: grid.HideBubbleInView(bottom_end, view)
                
                if t: grid.ShowBubbleInView(top_end, view)
                else: grid.HideBubbleInView(top_end, view)

    def apply_to_levels(self, view, l, r):
        levels = FilteredElementCollector(doc, view.Id).OfClass(Level).ToElements()
        for level in levels:
            if not level.CanBeVisibleInView(view): continue
            
            curves = level.GetCurvesInView(DatumExtentType.ViewSpecific, view)
            if not curves or curves.Count == 0: continue
            curve = curves[0]
            
            level.SetDatumExtentType(DatumEnds.End0, view, DatumExtentType.ViewSpecific)
            level.SetDatumExtentType(DatumEnds.End1, view, DatumExtentType.ViewSpecific)
            
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            vec = p1 - p0
            
            dot_right = vec.DotProduct(view.RightDirection)
            if dot_right > 0:
                left_end, right_end = DatumEnds.End0, DatumEnds.End1
            else:
                left_end, right_end = DatumEnds.End1, DatumEnds.End0
                
            if l: level.ShowBubbleInView(left_end, view)
            else: level.HideBubbleInView(left_end, view)
            
            if r: level.ShowBubbleInView(right_end, view)
            else: level.HideBubbleInView(right_end, view)

    def align_datums(self, view, do_t, do_b, do_l, do_r, extent_type):
        grids = FilteredElementCollector(doc, view.Id).OfClass(Grid).ToElements()
        levels = FilteredElementCollector(doc, view.Id).OfClass(Level).ToElements()
        
        datums = list(grids) + list(levels)
        if not datums: return
        
        horizontal_datums = []
        vertical_datums = []
        
        for d in datums:
            if not d.CanBeVisibleInView(view): continue
            curves = d.GetCurvesInView(extent_type, view)
            if not curves or curves.Count == 0: continue
            curve = curves[0]
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            vec = p1 - p0
            dot_right = vec.DotProduct(view.RightDirection)
            dot_up = vec.DotProduct(view.UpDirection)
            
            if abs(dot_right) > abs(dot_up):
                if dot_right > 0:
                    left_end, right_end, p_left, p_right = DatumEnds.End0, DatumEnds.End1, p0, p1
                else:
                    left_end, right_end, p_left, p_right = DatumEnds.End1, DatumEnds.End0, p1, p0
                horizontal_datums.append((d, left_end, right_end, p_left, p_right))
            else:
                if dot_up > 0:
                    bottom_end, top_end, p_bottom, p_top = DatumEnds.End0, DatumEnds.End1, p0, p1
                else:
                    bottom_end, top_end, p_bottom, p_top = DatumEnds.End1, DatumEnds.End0, p1, p0
                vertical_datums.append((d, top_end, bottom_end, p_top, p_bottom))
                
        def get_x(p): return (p - view.Origin).DotProduct(view.RightDirection)
        def get_y(p): return (p - view.Origin).DotProduct(view.UpDirection)
        
        # Calculate extremes
        min_x = min([get_x(d[3]) for d in horizontal_datums]) if horizontal_datums and do_l else None
        max_x = max([get_x(d[4]) for d in horizontal_datums]) if horizontal_datums and do_r else None
        
        max_y = max([get_y(d[3]) for d in vertical_datums]) if vertical_datums and do_t else None
        min_y = min([get_y(d[4]) for d in vertical_datums]) if vertical_datums and do_b else None
        
        # Clamp to Crop Boundaries if 2D alignment and Crop Box is active
        if extent_type == DatumExtentType.ViewSpecific and view.CropBoxActive:
            cb = view.CropBox
            p_min = cb.Transform.OfPoint(cb.Min)
            p_max = cb.Transform.OfPoint(cb.Max)
            
            crop_x_1 = get_x(p_min)
            crop_x_2 = get_x(p_max)
            crop_y_1 = get_y(p_min)
            crop_y_2 = get_y(p_max)
            
            crop_left = min(crop_x_1, crop_x_2)
            crop_right = max(crop_x_1, crop_x_2)
            crop_bottom = min(crop_y_1, crop_y_2)
            crop_top = max(crop_y_1, crop_y_2)
            
            if min_x is not None: min_x = max(min_x, crop_left)
            if max_x is not None: max_x = min(max_x, crop_right)
            if min_y is not None: min_y = max(min_y, crop_bottom)
            if max_y is not None: max_y = min(max_y, crop_top)
            
        # Apply alignment
        for d, left_end, right_end, p_left, p_right in horizontal_datums:
            changed = False
            new_p_left = p_left
            new_p_right = p_right
            if do_l and min_x is not None:
                new_p_left = p_left + (min_x - get_x(p_left)) * view.RightDirection
                changed = True
            if do_r and max_x is not None:
                new_p_right = p_right + (max_x - get_x(p_right)) * view.RightDirection
                changed = True
                
            if changed:
                new_curve = Line.CreateBound(new_p_left, new_p_right) if left_end == DatumEnds.End0 else Line.CreateBound(new_p_right, new_p_left)
                d.SetCurveInView(extent_type, view, new_curve)

        for d, top_end, bottom_end, p_top, p_bottom in vertical_datums:
            changed = False
            new_p_top = p_top
            new_p_bottom = p_bottom
            if do_t and max_y is not None:
                new_p_top = p_top + (max_y - get_y(p_top)) * view.UpDirection
                changed = True
            if do_b and min_y is not None:
                new_p_bottom = p_bottom + (min_y - get_y(p_bottom)) * view.UpDirection
                changed = True
                
            if changed:
                new_curve = Line.CreateBound(new_p_bottom, new_p_top) if bottom_end == DatumEnds.End0 else Line.CreateBound(new_p_top, new_p_bottom)
                d.SetCurveInView(extent_type, view, new_curve)

    def OnPlanAlignAll(self, sender, args):
        all_checked = (self.chkPlanAlignTop.IsChecked and self.chkPlanAlignBottom.IsChecked and 
                       self.chkPlanAlignLeft.IsChecked and self.chkPlanAlignRight.IsChecked)
        state = not all_checked
        self.chkPlanAlignTop.IsChecked = state
        self.chkPlanAlignBottom.IsChecked = state
        self.chkPlanAlignLeft.IsChecked = state
        self.chkPlanAlignRight.IsChecked = state

    def OnSecAlignAll(self, sender, args):
        all_checked = (self.chkSecAlignTop.IsChecked and self.chkSecAlignBottom.IsChecked and 
                       self.chkSecAlignLeft.IsChecked and self.chkSecAlignRight.IsChecked)
        state = not all_checked
        self.chkSecAlignTop.IsChecked = state
        self.chkSecAlignBottom.IsChecked = state
        self.chkSecAlignLeft.IsChecked = state
        self.chkSecAlignRight.IsChecked = state

    def OnApplyClick(self, sender, args):
        if not self.selected_views:
            forms.alert("No valid views selected.")
            return
            
        t_trans = Transaction(doc, "Bubble Control & Align")
        t_trans.Start()
        
        plan_t = self.chkPlanTop.IsChecked
        plan_b = self.chkPlanBottom.IsChecked
        plan_l = self.chkPlanLeft.IsChecked
        plan_r = self.chkPlanRight.IsChecked
        
        sec_t = self.chkSecTop.IsChecked
        sec_b = self.chkSecBottom.IsChecked
        sec_l = self.chkSecLeft.IsChecked
        sec_r = self.chkSecRight.IsChecked
        
        plan_align_t = self.chkPlanAlignTop.IsChecked
        plan_align_b = self.chkPlanAlignBottom.IsChecked
        plan_align_l = self.chkPlanAlignLeft.IsChecked
        plan_align_r = self.chkPlanAlignRight.IsChecked

        sec_align_t = self.chkSecAlignTop.IsChecked
        sec_align_b = self.chkSecAlignBottom.IsChecked
        sec_align_l = self.chkSecAlignLeft.IsChecked
        sec_align_r = self.chkSecAlignRight.IsChecked
        
        do_2d = self.chkAlign2D.IsChecked
        do_3d = self.chkAlign3D.IsChecked
        
        for view in self.selected_views:
            if view.ViewType in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan]:
                if self.grpPlans.IsEnabled:
                    self.apply_to_grids(view, plan_t, plan_b, plan_l, plan_r)
                    if plan_align_t or plan_align_b or plan_align_l or plan_align_r:
                        if do_3d: self.align_datums(view, plan_align_t, plan_align_b, plan_align_l, plan_align_r, DatumExtentType.Model)
                        if do_2d: self.align_datums(view, plan_align_t, plan_align_b, plan_align_l, plan_align_r, DatumExtentType.ViewSpecific)
                        
            elif view.ViewType in [ViewType.Elevation, ViewType.Section]:
                if self.grpSections.IsEnabled:
                    self.apply_to_grids(view, sec_t, sec_b, sec_l, sec_r)
                    self.apply_to_levels(view, sec_l, sec_r)
                    if sec_align_t or sec_align_b or sec_align_l or sec_align_r:
                        if do_3d: self.align_datums(view, sec_align_t, sec_align_b, sec_align_l, sec_align_r, DatumExtentType.Model)
                        if do_2d: self.align_datums(view, sec_align_t, sec_align_b, sec_align_l, sec_align_r, DatumExtentType.ViewSpecific)
                    
        t_trans.Commit()
        self.Close()

if __name__ == '__main__':
    BubbleControlWindow('ui.xaml').ShowDialog()
