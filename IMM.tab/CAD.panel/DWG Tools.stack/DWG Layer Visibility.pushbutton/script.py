# -*- coding: utf-8 -*-
import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

import System
from System import Action, TimeSpan
from System.Diagnostics import Process
from System.Collections.Generic import List
from System.Windows import Window, Visibility, FontWeights
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority, DispatcherTimer
from System.Windows.Controls import ListBoxItem, CheckBox, ScrollViewer, TextBlock
from System.Windows.Controls.Primitives import ScrollBar, Thumb, RepeatButton
from System.Windows.Documents import Run
from System.Windows.Input import Keyboard, ModifierKeys, MouseButtonState, Key, Mouse
from System.Windows.Media import VisualTreeHelper, SolidColorBrush, Color
from System.Windows.Markup import XamlReader
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs

from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

HIGHLIGHT_BG = SolidColorBrush(Color.FromRgb(255, 235, 59))
HIGHLIGHT_FG = SolidColorBrush(Color.FromRgb(0, 0, 0))
NORMAL_FG = SolidColorBrush(Color.FromRgb(30, 30, 30))
DISABLED_FG = SolidColorBrush(Color.FromRgb(150, 150, 150))

XAML_STR = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="CAD Layer Visibility Controller" Height="720" Width="1280"
        WindowStartupLocation="CenterScreen" Background="#F4F4F4" ShowInTaskbar="False">
    <Grid>
        <!-- Main Content -->
        <Grid Margin="12">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>

            <!-- View Scope Group -->
            <GroupBox Header="1. Target View Scope" Grid.Row="0" Margin="0,0,0,10" Padding="8" FontWeight="SemiBold">
                <StackPanel Orientation="Horizontal" TextElement.FontWeight="Normal">
                    <RadioButton x:Name="rb_current" Content="Current View Only" IsChecked="True" Margin="0,0,25,0" VerticalAlignment="Center"/>
                    <RadioButton x:Name="rb_selected" Content="Selected Views" Margin="0,0,10,0" VerticalAlignment="Center"/>
                    <Button x:Name="btn_pick_views" Content="Select Views (0)" Width="120" Margin="0,0,25,0" IsEnabled="False" Padding="4,2"/>
                    <RadioButton x:Name="rb_all" Content="All Model Views" VerticalAlignment="Center"/>
                </StackPanel>
            </GroupBox>

            <!-- Main Lists -->
            <Grid Grid.Row="1" Margin="0,0,0,10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="1*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="1.4*"/>
                </Grid.ColumnDefinitions>

                <!-- CAD Files List -->
                <GroupBox Header="2. Select CAD Files" Grid.Column="0" Padding="6" FontWeight="SemiBold">
                    <Grid TextElement.FontWeight="Normal">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                        </Grid.RowDefinitions>
                        <Grid Grid.Row="0" Margin="0,0,0,6">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <Button x:Name="btn_cad_all" Content="All" Width="55" Grid.Column="0" Margin="0,0,6,0" Padding="2"/>
                            <Button x:Name="btn_cad_none" Content="None" Width="55" Grid.Column="1" Padding="2"/>
                            <Button x:Name="btn_cad_hide" Content="Hide" Width="75" Grid.Column="3" Padding="2" Background="#EAEAEA"/>
                        </Grid>
                        <ListBox x:Name="lb_cads" Grid.Row="1" BorderBrush="#CCCCCC" SelectionMode="Extended" HorizontalContentAlignment="Stretch">
                            <ListBox.ItemTemplate>
                                <DataTemplate>
                                    <Grid Background="Transparent" Margin="1">
                                        <Grid.ColumnDefinitions>
                                            <ColumnDefinition Width="Auto"/>
                                            <ColumnDefinition Width="*"/>
                                            <ColumnDefinition Width="Auto"/>
                                        </Grid.ColumnDefinitions>
                                        <CheckBox IsChecked="{Binding IsChecked, Mode=TwoWay}" IsEnabled="{Binding IsCheckEnabled}" Grid.Column="0" Margin="2,2,6,2" VerticalAlignment="Center"/>
                                        <TextBlock Text="{Binding Name}" Foreground="{Binding TextBrush}" Grid.Column="1" VerticalAlignment="Center" Margin="0,2"/>
                                        <Border Grid.Column="2" Background="#E0E0E0" CornerRadius="4" Padding="5,1" Margin="6,0,2,0" VerticalAlignment="Center" Visibility="{Binding HiddenBadgeVis}">
                                            <TextBlock Text="Hidden" FontSize="10" Foreground="#666666" FontStyle="Italic"/>
                                        </Border>
                                    </Grid>
                                </DataTemplate>
                            </ListBox.ItemTemplate>
                        </ListBox>
                    </Grid>
                </GroupBox>

                <!-- Layers List -->
                <GroupBox Header="3. Check Layers to Show (Unchecked will be Hidden)" Grid.Column="2" Padding="6" FontWeight="SemiBold">
                    <Grid TextElement.FontWeight="Normal">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                        </Grid.RowDefinitions>
                        <Grid Grid.Row="0" Margin="0,0,0,6">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Button x:Name="btn_lay_all" Content="All" Width="55" Grid.Column="0" Margin="0,0,6,0" Padding="2"/>
                            <Button x:Name="btn_lay_none" Content="None" Width="55" Grid.Column="1" Margin="0,0,8,0" Padding="2"/>
                            <TextBox x:Name="tb_search" Grid.Column="2" VerticalContentAlignment="Center" Padding="4,0" ToolTip="Search Layer Names"/>
                        </Grid>
                        <ListBox x:Name="lb_layers" Grid.Row="1" BorderBrush="#CCCCCC" SelectionMode="Extended" HorizontalContentAlignment="Stretch">
                            <ListBox.ItemTemplate>
                                <DataTemplate>
                                    <Grid Background="Transparent" Margin="1">
                                        <Grid.ColumnDefinitions>
                                            <ColumnDefinition Width="68"/>
                                            <ColumnDefinition Width="Auto"/>
                                            <ColumnDefinition Width="*"/>
                                        </Grid.ColumnDefinitions>
                                        <Border Grid.Column="0" Background="#E0E8F0" BorderBrush="#B8C8D8" BorderThickness="1" CornerRadius="10" Padding="6,1" Margin="2,0,8,0" VerticalAlignment="Center" HorizontalAlignment="Left" ToolTip="{Binding TooltipText}">
                                            <TextBlock Text="{Binding CountText}" FontSize="11" Foreground="#204060" FontWeight="SemiBold" HorizontalAlignment="Center"/>
                                        </Border>
                                        <CheckBox IsChecked="{Binding IsChecked, Mode=TwoWay}" Grid.Column="1" Margin="2,2,6,2" VerticalAlignment="Center"/>
                                        <ContentControl Content="{Binding HighlightedText}" Grid.Column="2" VerticalAlignment="Center" Margin="0,2"/>
                                    </Grid>
                                </DataTemplate>
                            </ListBox.ItemTemplate>
                        </ListBox>
                    </Grid>
                </GroupBox>
            </Grid>

            <!-- Actions -->
            <Border Grid.Row="2" BorderBrush="#DDDDDD" BorderThickness="0,1,0,0" Padding="0,10,0,0">
                <Grid>
                    <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
                        <Button x:Name="btn_reset" Content="Reset Selected CADs (Show All Layers)" Width="240" Height="32" Background="#FFF0E5"/>
                    </StackPanel>
                    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                        <Button x:Name="btn_apply" Content="Apply" Width="110" Height="32" Margin="0,0,10,0" Background="#E5F9E7" FontWeight="SemiBold"/>
                        <Button x:Name="btn_cancel" Content="Close" Width="110" Height="32" Background="#E8E8E8"/>
                    </StackPanel>
                </Grid>
            </Border>
        </Grid>

        <!-- Loading Overlay -->
        <Grid x:Name="loading_overlay" Background="#D9FFFFFF" Visibility="Visible">
            <Border Background="White" BorderBrush="#CCCCCC" BorderThickness="1" CornerRadius="8" Padding="35,25" HorizontalAlignment="Center" VerticalAlignment="Center">
                <StackPanel HorizontalAlignment="Center" VerticalAlignment="Center">
                    <Grid Width="48" Height="48" HorizontalAlignment="Center" Margin="0,0,0,14">
                        <Ellipse Width="48" Height="48" Stroke="#E6EEF8" StrokeThickness="5"/>
                        <Path Stroke="#0066CC" StrokeThickness="5" StrokeStartLineCap="Round" StrokeEndLineCap="Round"
                              Data="M 24,2.5 A 21.5,21.5 0 0 1 45.5,24" RenderTransformOrigin="0.5,0.5" Width="48" Height="48">
                            <Path.RenderTransform>
                                <RotateTransform Angle="0"/>
                            </Path.RenderTransform>
                            <Path.Triggers>
                                <EventTrigger RoutedEvent="FrameworkElement.Loaded">
                                    <BeginStoryboard>
                                        <Storyboard>
                                            <DoubleAnimation Storyboard.TargetProperty="(UIElement.RenderTransform).(RotateTransform.Angle)"
                                                             From="0" To="360" Duration="0:0:0.9" RepeatBehavior="Forever"/>
                                        </Storyboard>
                                    </BeginStoryboard>
                                </EventTrigger>
                            </Path.Triggers>
                        </Path>
                    </Grid>
                    <TextBlock x:Name="tb_loading_msg" Text="Analyzing DWGs..." FontSize="15" FontWeight="SemiBold" Foreground="#333333" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
        </Grid>
    </Grid>
</Window>
"""


def build_highlighted_textblock(text, search_str):
    tb = TextBlock()
    tb.Foreground = NORMAL_FG
    if not search_str:
        tb.Text = text
        return tb

    lower_text = text.lower()
    lower_search = search_str.lower()
    start = 0
    s_len = len(search_str)

    while True:
        idx = lower_text.find(lower_search, start)
        if idx == -1:
            if start < len(text):
                tb.Inlines.Add(Run(text[start:]))
            break
        if idx > start:
            tb.Inlines.Add(Run(text[start:idx]))
        match_run = Run(text[idx:idx + s_len])
        match_run.Background = HIGHLIGHT_BG
        match_run.Foreground = HIGHLIGHT_FG
        match_run.FontWeight = FontWeights.Bold
        tb.Inlines.Add(match_run)
        start = idx + s_len

    return tb


class CheckItem(INotifyPropertyChanged):
    def __init__(self, name, data=None, instance_ids=None, count=0, cads_list=None, is_checked=False, is_hidden=False, on_check_changed=None):
        self._name = name
        self.Data = data
        self.InstanceIds = instance_ids or set()
        self._count = count
        self._cads_list = cads_list or []
        self._is_checked = is_checked if not is_hidden else False
        self._is_hidden = is_hidden
        self._search_str = ""
        self._highlighted_tb = build_highlighted_textblock(name, "")
        self._events = []
        self._on_check_changed = on_check_changed

    @property
    def Name(self):
        return self._name

    @property
    def Count(self):
        return self._count

    @property
    def CountText(self):
        return "{} DWG{}".format(self._count, "s" if self._count != 1 else "")

    @property
    def TooltipText(self):
        if self._cads_list:
            return "Found in:\n" + "\n".join(self._cads_list)
        return ""

    @property
    def IsHidden(self):
        return self._is_hidden

    @IsHidden.setter
    def IsHidden(self, value):
        if self._is_hidden != value:
            self._is_hidden = value
            if value and self._is_checked:
                self._is_checked = False
                self.notify("IsChecked")
            self.notify("IsHidden")
            self.notify("IsCheckEnabled")
            self.notify("TextBrush")
            self.notify("HiddenBadgeVis")

    @property
    def IsCheckEnabled(self):
        return not self._is_hidden

    @property
    def TextBrush(self):
        return DISABLED_FG if self._is_hidden else NORMAL_FG

    @property
    def HiddenBadgeVis(self):
        return Visibility.Visible if self._is_hidden else Visibility.Collapsed

    @property
    def HighlightedText(self):
        return self._highlighted_tb

    def update_highlight(self, search_str):
        if self._search_str != search_str:
            self._search_str = search_str
            self._highlighted_tb = build_highlighted_textblock(self._name, search_str)
            self.notify("HighlightedText")

    @property
    def IsChecked(self):
        return self._is_checked

    @IsChecked.setter
    def IsChecked(self, value):
        if self._is_hidden and value:
            return
        if self._is_checked != value:
            self._is_checked = value
            self.notify("IsChecked")
            if self._on_check_changed:
                self._on_check_changed()

    def set_checked_quiet(self, value):
        if self._is_hidden and value:
            value = False
        if self._is_checked != value:
            self._is_checked = value
            self.notify("IsChecked")

    def notify(self, prop_name):
        for handler in self._events:
            handler(self, PropertyChangedEventArgs(prop_name))

    def add_PropertyChanged(self, handler):
        self._events.append(handler)

    def remove_PropertyChanged(self, handler):
        if handler in self._events:
            self._events.remove(handler)


class MultiSelectController(object):
    def __init__(self, listbox, on_batch_check_changed=None, on_selection_changed=None):
        self.lb = listbox
        self.on_batch_check_changed = on_batch_check_changed
        self.on_selection_changed = on_selection_changed
        self.drag_mode = None
        self.target_check_state = True
        self.start_idx = -1
        self.last_check_idx = -1
        self.last_select_idx = -1
        self.initial_selected = set()
        self.scroll_dir = 0

        self.scroll_timer = DispatcherTimer()
        self.scroll_timer.Interval = TimeSpan.FromMilliseconds(35)
        self.scroll_timer.Tick += self.on_scroll_tick

        self.lb.PreviewMouseLeftButtonDown += self.on_mouse_down
        self.lb.PreviewMouseMove += self.on_mouse_move
        self.lb.PreviewMouseLeftButtonUp += self.on_mouse_up
        self.lb.PreviewKeyDown += self.on_key_down

    def find_ancestor(self, dep_obj, target_type):
        curr = dep_obj
        while curr is not None:
            if isinstance(curr, target_type):
                return curr
            try:
                curr = VisualTreeHelper.GetParent(curr)
            except Exception:
                break
        return None

    def find_visual_child(self, dep_obj, target_type):
        if dep_obj is None:
            return None
        try:
            count = VisualTreeHelper.GetChildrenCount(dep_obj)
            for i in range(count):
                child = VisualTreeHelper.GetChild(dep_obj, i)
                if isinstance(child, target_type):
                    return child
                res = self.find_visual_child(child, target_type)
                if res is not None:
                    return res
        except Exception:
            pass
        return None

    def get_scroll_viewer(self):
        return self.find_visual_child(self.lb, ScrollViewer)

    def is_on_scrollbar(self, dep_obj):
        return (
            self.find_ancestor(dep_obj, ScrollBar) is not None or
            self.find_ancestor(dep_obj, Thumb) is not None or
            self.find_ancestor(dep_obj, RepeatButton) is not None
        )

    def get_item_index(self, item):
        try:
            return self.lb.Items.IndexOf(item)
        except Exception:
            return -1

    def notify_sel_changed(self):
        if self.on_selection_changed:
            self.on_selection_changed()

    def stop_drag(self):
        if self.scroll_timer.IsEnabled:
            self.scroll_timer.Stop()
        if self.lb.IsMouseCaptured:
            self.lb.ReleaseMouseCapture()
        self.drag_mode = None
        self.scroll_dir = 0

    def on_mouse_down(self, sender, args):
        orig = args.OriginalSource
        if self.is_on_scrollbar(orig):
            return

        lbi = self.find_ancestor(orig, ListBoxItem)
        if lbi is None:
            return

        item = lbi.DataContext
        idx = self.get_item_index(item)
        if idx == -1:
            return

        cb = self.find_ancestor(orig, CheckBox)
        is_shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
        is_ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control

        if cb is not None:
            args.Handled = True
            if not item.IsCheckEnabled:
                return
            self.lb.Focus()
            self.drag_mode = 'check'
            new_state = not item.IsChecked
            self.target_check_state = new_state

            if is_shift and self.last_check_idx != -1:
                low = min(self.last_check_idx, idx)
                high = max(self.last_check_idx, idx)
                for i in range(low, high + 1):
                    it = self.lb.Items[i]
                    if it.IsCheckEnabled:
                        it.set_checked_quiet(new_state)
            elif item in self.lb.SelectedItems and self.lb.SelectedItems.Count > 1 and not is_ctrl:
                for sel_item in list(self.lb.SelectedItems):
                    if sel_item.IsCheckEnabled:
                        sel_item.set_checked_quiet(new_state)
            else:
                item.set_checked_quiet(new_state)

            self.last_check_idx = idx
            self.start_idx = idx
            self.lb.CaptureMouse()
            if self.on_batch_check_changed:
                self.on_batch_check_changed()
        else:
            args.Handled = True
            self.lb.Focus()
            self.drag_mode = 'select'
            self.start_idx = idx

            if is_shift and self.last_select_idx != -1:
                if not is_ctrl:
                    self.lb.SelectedItems.Clear()
                low = min(self.last_select_idx, idx)
                high = max(self.last_select_idx, idx)
                for i in range(low, high + 1):
                    it = self.lb.Items[i]
                    if it not in self.lb.SelectedItems:
                        self.lb.SelectedItems.Add(it)
            elif is_ctrl:
                if item in self.lb.SelectedItems:
                    self.lb.SelectedItems.Remove(item)
                else:
                    self.lb.SelectedItems.Add(item)
                self.last_select_idx = idx
            else:
                self.lb.SelectedItems.Clear()
                self.lb.SelectedItems.Add(item)
                self.last_select_idx = idx

            self.initial_selected = set(self.lb.SelectedItems)
            self.lb.CaptureMouse()
            self.notify_sel_changed()

    def update_drag_at_point(self, pos):
        h = self.lb.ActualHeight
        w = self.lb.ActualWidth
        if h <= 0 or w <= 0:
            return

        clamped_x = max(5.0, min(w - 25.0, pos.X))
        clamped_y = max(4.0, min(h - 4.0, pos.Y))
        hit = VisualTreeHelper.HitTest(self.lb, System.Windows.Point(clamped_x, clamped_y))
        if hit is None or hit.VisualHit is None:
            return

        lbi = self.find_ancestor(hit.VisualHit, ListBoxItem)
        if lbi is None:
            return

        item = lbi.DataContext
        idx = self.get_item_index(item)
        if idx == -1:
            return

        if self.drag_mode == 'check':
            low = min(self.start_idx, idx)
            high = max(self.start_idx, idx)
            changed = False
            for i in range(low, high + 1):
                it = self.lb.Items[i]
                if it.IsCheckEnabled and it.IsChecked != self.target_check_state:
                    it.set_checked_quiet(self.target_check_state)
                    changed = True
            self.last_check_idx = idx
            if changed and self.on_batch_check_changed:
                self.on_batch_check_changed()

        elif self.drag_mode == 'select':
            is_ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
            low = min(self.start_idx, idx)
            high = max(self.start_idx, idx)

            self.lb.SelectedItems.Clear()
            if is_ctrl:
                for it in self.initial_selected:
                    self.lb.SelectedItems.Add(it)

            for i in range(low, high + 1):
                it = self.lb.Items[i]
                if it not in self.lb.SelectedItems:
                    self.lb.SelectedItems.Add(it)
            self.notify_sel_changed()

    def on_mouse_move(self, sender, args):
        if args.LeftButton != MouseButtonState.Pressed or self.drag_mode is None:
            self.stop_drag()
            return

        pos = args.GetPosition(self.lb)
        h = self.lb.ActualHeight
        edge_zone = 24.0

        if pos.Y < edge_zone:
            self.scroll_dir = -1
            if not self.scroll_timer.IsEnabled:
                self.scroll_timer.Start()
        elif pos.Y > h - edge_zone:
            self.scroll_dir = 1
            if not self.scroll_timer.IsEnabled:
                self.scroll_timer.Start()
        else:
            self.scroll_dir = 0
            if self.scroll_timer.IsEnabled:
                self.scroll_timer.Stop()

        self.update_drag_at_point(pos)

    def on_scroll_tick(self, sender, args):
        if Mouse.LeftButton != MouseButtonState.Pressed or self.drag_mode is None:
            self.stop_drag()
            return

        sv = self.get_scroll_viewer()
        if sv is not None and self.scroll_dir != 0:
            sv.ScrollToVerticalOffset(sv.VerticalOffset + (self.scroll_dir * 2.0))

        pos = Mouse.GetPosition(self.lb)
        self.update_drag_at_point(pos)

    def on_mouse_up(self, sender, args):
        self.stop_drag()

    def on_key_down(self, sender, args):
        if args.Key == Key.Space and self.lb.SelectedItems.Count > 0:
            args.Handled = True
            enabled_items = [it for it in list(self.lb.SelectedItems) if it.IsCheckEnabled]
            if not enabled_items:
                return
            new_state = not enabled_items[0].IsChecked
            for it in enabled_items:
                it.set_checked_quiet(new_state)
            if self.on_batch_check_changed:
                self.on_batch_check_changed()


class CADLayerWindow(object):
    def __init__(self):
        self.win = XamlReader.Parse(XAML_STR)
        self.set_revit_owner()
        
        self.rb_current = self.win.FindName("rb_current")
        self.rb_selected = self.win.FindName("rb_selected")
        self.rb_all = self.win.FindName("rb_all")
        self.btn_pick_views = self.win.FindName("btn_pick_views")
        
        self.btn_cad_all = self.win.FindName("btn_cad_all")
        self.btn_cad_none = self.win.FindName("btn_cad_none")
        self.btn_cad_hide = self.win.FindName("btn_cad_hide")
        self.lb_cads = self.win.FindName("lb_cads")
        
        self.btn_lay_all = self.win.FindName("btn_lay_all")
        self.btn_lay_none = self.win.FindName("btn_lay_none")
        self.tb_search = self.win.FindName("tb_search")
        self.lb_layers = self.win.FindName("lb_layers")
        
        self.btn_reset = self.win.FindName("btn_reset")
        self.btn_apply = self.win.FindName("btn_apply")
        self.btn_cancel = self.win.FindName("btn_cancel")
        self.loading_overlay = self.win.FindName("loading_overlay")
        self.tb_loading_msg = self.win.FindName("tb_loading_msg")

        self.selected_views = []
        self.cad_items = ObservableCollection[object]()
        self.all_layer_items = []
        self.filtered_layer_items = ObservableCollection[object]()
        self._has_unapplied_changes = False
        self._cad_layer_cache = {}
        self._is_ready = False

        self.lb_cads.ItemsSource = self.cad_items
        self.lb_layers.ItemsSource = self.filtered_layer_items

        self.cad_ms_ctrl = MultiSelectController(
            self.lb_cads,
            on_batch_check_changed=self.on_cads_check_changed,
            on_selection_changed=self.update_hide_button_label
        )
        self.lay_ms_ctrl = MultiSelectController(
            self.lb_layers,
            on_batch_check_changed=self.mark_dirty
        )

        self.bind_events()
        self.win.ContentRendered += self.on_window_rendered

    def set_revit_owner(self):
        try:
            helper = WindowInteropHelper(self.win)
            try:
                main_hwnd = uidoc.Application.MainWindowHandle
            except Exception:
                main_hwnd = Process.GetCurrentProcess().MainWindowHandle
            helper.Owner = main_hwnd
        except Exception:
            pass

    def on_window_rendered(self, sender, args):
        if not self._is_ready:
            self._is_ready = True
            self.run_with_loading(self.initial_load)

    def initial_load(self):
        self.refresh_cads()
        self.mark_clean()

    def run_with_loading(self, work_fn):
        self.loading_overlay.Visibility = Visibility.Visible

        def do_work():
            try:
                work_fn()
            finally:
                self.loading_overlay.Visibility = Visibility.Collapsed

        self.win.Dispatcher.BeginInvoke(
            DispatcherPriority.ApplicationIdle,
            Action(do_work)
        )

    def set_dirty_state(self, is_dirty):
        self._has_unapplied_changes = is_dirty
        if self.btn_cancel:
            self.btn_cancel.Content = "Cancel" if is_dirty else "Close"

    def mark_dirty(self):
        self.set_dirty_state(True)

    def mark_clean(self):
        self.set_dirty_state(False)

    def on_cads_check_changed(self):
        self.refresh_layers(preserve_state=True)
        self.mark_dirty()

    def update_hide_button_label(self):
        if not self.btn_cad_hide:
            return
        sel = list(self.lb_cads.SelectedItems)
        if not sel:
            self.btn_cad_hide.Content = "Hide"
            return
        if all(it.IsHidden for it in sel):
            self.btn_cad_hide.Content = "Show"
        else:
            self.btn_cad_hide.Content = "Hide"

    def bind_events(self):
        self.rb_current.Checked += self.on_scope_changed
        self.rb_selected.Checked += self.on_scope_changed
        self.rb_all.Checked += self.on_scope_changed
        self.btn_pick_views.Click += self.on_pick_views

        self.btn_cad_all.Click += self.on_cad_all
        self.btn_cad_none.Click += self.on_cad_none
        self.btn_cad_hide.Click += self.on_cad_hide_toggle

        self.btn_lay_all.Click += self.on_lay_all
        self.btn_lay_none.Click += self.on_lay_none
        self.tb_search.TextChanged += self.on_search_changed

        self.btn_apply.Click += self.on_apply
        self.btn_cancel.Click += self.on_cancel
        self.btn_reset.Click += self.on_reset

    def get_elem_id_val(self, elem_id):
        try:
            return elem_id.Value
        except AttributeError:
            return elem_id.IntegerValue

    def can_modify_view(self, view):
        if not view:
            return False
        try:
            if view.ViewType in [
                DB.ViewType.DrawingSheet,
                DB.ViewType.Schedule,
                DB.ViewType.ColumnSchedule,
                DB.ViewType.PanelSchedule,
                DB.ViewType.Report,
                DB.ViewType.ProjectBrowser,
                DB.ViewType.SystemBrowser,
                DB.ViewType.Undefined,
                DB.ViewType.Internal
            ]:
                return False
            return True
        except Exception:
            return False

    def get_target_views(self):
        if self.rb_current.IsChecked:
            return [doc.ActiveView]
        elif self.rb_selected.IsChecked:
            return self.selected_views
        elif self.rb_all.IsChecked:
            views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
            return [v for v in views if not v.IsTemplate and self.can_modify_view(v)]
        return []

    def get_modification_targets(self, views):
        targets = {}
        for v in views:
            if not self.can_modify_view(v):
                continue
            vt_id = v.ViewTemplateId
            if vt_id and vt_id != DB.ElementId.InvalidElementId:
                vt = doc.GetElement(vt_id)
                if vt:
                    targets[self.get_elem_id_val(vt.Id)] = vt
            targets[self.get_elem_id_val(v.Id)] = v
        return list(targets.values())

    def get_cad_name(self, cad_inst):
        try:
            cad_type = doc.GetElement(cad_inst.GetTypeId())
            if cad_type:
                p = cad_type.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                if p and p.HasValue:
                    return p.AsString()
                return DB.Element.Name.__get__(cad_type)
        except Exception:
            pass
        try:
            if cad_inst.Category and cad_inst.Category.Name:
                return cad_inst.Category.Name
        except Exception:
            pass
        return "CAD_" + str(self.get_elem_id_val(cad_inst.Id))

    def get_cad_layers(self, cad_inst):
        type_id_val = self.get_elem_id_val(cad_inst.GetTypeId())
        if type_id_val in self._cad_layer_cache:
            return self._cad_layer_cache[type_id_val]

        layer_map = {}
        try:
            cat = cad_inst.Category
            if cat and cat.SubCategories:
                for subcat in cat.SubCategories:
                    name = subcat.Name.strip() if subcat.Name else ""
                    if name:
                        if name not in layer_map:
                            layer_map[name] = set()
                        layer_map[name].add(subcat.Id)
        except Exception:
            pass

        self._cad_layer_cache[type_id_val] = layer_map
        return layer_map

    def collect_scope_cads(self):
        views = self.get_target_views()
        all_cads = DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance).ToElements()

        if self.rb_all.IsChecked:
            return all_cads

        target_view_ids = set(self.get_elem_id_val(v.Id) for v in views if v)
        visible_ids_in_views = set()
        for v in views:
            try:
                for el in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.ImportInstance).ToElements():
                    visible_ids_in_views.add(self.get_elem_id_val(el.Id))
            except Exception:
                pass

        scope_cads = []
        for c in all_cads:
            cid_val = self.get_elem_id_val(c.Id)
            if cid_val in visible_ids_in_views:
                scope_cads.append(c)
                continue
            if c.ViewSpecific and c.OwnerViewId and self.get_elem_id_val(c.OwnerViewId) in target_view_ids:
                scope_cads.append(c)
                continue
            if not c.ViewSpecific:
                for v in views:
                    try:
                        if c.IsHidden(v):
                            scope_cads.append(c)
                            break
                    except Exception:
                        pass
        return scope_cads

    def is_cad_hidden_in_views(self, instance_ids, views):
        if not views or not instance_ids:
            return False
        for v in views:
            for iid in instance_ids:
                el = doc.GetElement(iid)
                if not el:
                    continue
                if el.ViewSpecific and el.OwnerViewId != v.Id:
                    continue
                try:
                    if not el.IsHidden(v):
                        return False
                except Exception:
                    return False
        return True

    def refresh_cads(self):
        self.cad_items.Clear()
        cad_dict = {}
        cad_inst_map = {}

        cads = self.collect_scope_cads()
        views = self.get_target_views()

        for c in cads:
            name = self.get_cad_name(c)
            layers = self.get_cad_layers(c)
            if not layers:
                continue
            if name not in cad_dict:
                cad_dict[name] = {}
                cad_inst_map[name] = set()
            cad_inst_map[name].add(c.Id)
            for lname, lid_set in layers.items():
                if lname not in cad_dict[name]:
                    cad_dict[name][lname] = set()
                cad_dict[name][lname].update(lid_set)

        for name in sorted(cad_dict.keys()):
            inst_ids = cad_inst_map[name]
            is_hid = self.is_cad_hidden_in_views(inst_ids, views)
            item = CheckItem(
                name,
                data=cad_dict[name],
                instance_ids=inst_ids,
                is_checked=(not is_hid),
                is_hidden=is_hid,
                on_check_changed=self.on_cads_check_changed
            )
            self.cad_items.Add(item)

        self.update_hide_button_label()
        self.refresh_layers(preserve_state=False)

    def on_cad_hide_toggle(self, sender, args):
        sel_items = list(self.lb_cads.SelectedItems)
        if not sel_items:
            forms.alert("Please select (highlight) at least one DWG in the list to Hide or Show.")
            return

        views = self.get_target_views()
        if not views:
            forms.alert("No target views selected.")
            return

        should_unhide = all(it.IsHidden for it in sel_items)
        action_name = "Unhide CAD Files" if should_unhide else "Hide CAD Files"

        with revit.Transaction(action_name):
            for v in views:
                if not self.can_modify_view(v):
                    continue
                ids_for_view = List[DB.ElementId]()
                for it in sel_items:
                    for iid in it.InstanceIds:
                        el = doc.GetElement(iid)
                        if not el:
                            continue
                        if el.ViewSpecific and el.OwnerViewId != v.Id:
                            continue
                        try:
                            if should_unhide and el.IsHidden(v):
                                ids_for_view.Add(iid)
                            elif not should_unhide and not el.IsHidden(v) and el.CanBeHidden(v):
                                ids_for_view.Add(iid)
                        except Exception:
                            pass
                if ids_for_view.Count > 0:
                    try:
                        if should_unhide:
                            v.UnhideElements(ids_for_view)
                        else:
                            v.HideElements(ids_for_view)
                    except Exception:
                        pass

        for it in sel_items:
            it.IsHidden = not should_unhide
            if should_unhide:
                it.set_checked_quiet(True)

        uidoc.RefreshActiveView()
        self.update_hide_button_label()
        self.refresh_layers(preserve_state=True)

    def is_layer_visible_currently(self, cat_ids):
        views = self.get_target_views()
        ref_view = views[0] if views else doc.ActiveView
        if ref_view and ref_view.ViewTemplateId != DB.ElementId.InvalidElementId:
            vt = doc.GetElement(ref_view.ViewTemplateId)
            if vt:
                ref_view = vt

        for cid in cat_ids:
            try:
                if not ref_view.GetCategoryHidden(cid):
                    return True
            except Exception:
                return True
        return False

    def refresh_layers(self, preserve_state=True):
        prev_state = {x.Name: x.IsChecked for x in self.all_layer_items} if preserve_state else {}
        layer_cads_map = {}
        layer_ids_map = {}

        for c_item in self.cad_items:
            if c_item.IsChecked and not c_item.IsHidden:
                for lname, lid_set in c_item.Data.items():
                    if lname not in layer_cads_map:
                        layer_cads_map[lname] = []
                        layer_ids_map[lname] = set()
                    layer_cads_map[lname].append(c_item.Name)
                    layer_ids_map[lname].update(lid_set)

        self.all_layer_items = []
        for lname in sorted(layer_cads_map.keys()):
            cads_with_layer = sorted(layer_cads_map[lname])
            if lname in prev_state:
                is_chk = prev_state[lname]
            else:
                is_chk = self.is_layer_visible_currently(layer_ids_map[lname])

            item = CheckItem(
                lname,
                count=len(cads_with_layer),
                cads_list=cads_with_layer,
                is_checked=is_chk,
                on_check_changed=self.mark_dirty
            )
            self.all_layer_items.append(item)

        self.apply_layer_filter()

    def apply_layer_filter(self):
        search_txt = self.tb_search.Text.strip() if self.tb_search.Text else ""
        lower_search = search_txt.lower()
        self.filtered_layer_items.Clear()
        for item in self.all_layer_items:
            if not lower_search or lower_search in item.Name.lower():
                item.update_highlight(search_txt)
                self.filtered_layer_items.Add(item)

    def on_scope_changed(self, sender, args):
        if not self._is_ready:
            return
        if self.btn_pick_views:
            self.btn_pick_views.IsEnabled = bool(self.rb_selected.IsChecked)
            self.run_with_loading(self._scope_refresh_work)

    def _scope_refresh_work(self):
        self.refresh_cads()
        self.mark_dirty()

    def on_pick_views(self, sender, args):
        picked = forms.select_views(title="Select Views to Control CAD Layers", multiple=True)
        if picked:
            self.selected_views = list(picked)
            self.btn_pick_views.Content = "Select Views ({})".format(len(self.selected_views))
            self.run_with_loading(self._scope_refresh_work)

    def on_cad_all(self, sender, args):
        for item in self.cad_items:
            if item.IsCheckEnabled:
                item.set_checked_quiet(True)
        self.refresh_layers(preserve_state=True)
        self.mark_dirty()

    def on_cad_none(self, sender, args):
        for item in self.cad_items:
            item.set_checked_quiet(False)
        self.refresh_layers(preserve_state=True)
        self.mark_dirty()

    def on_lay_all(self, sender, args):
        for item in self.filtered_layer_items:
            item.set_checked_quiet(True)
        self.mark_dirty()

    def on_lay_none(self, sender, args):
        for item in self.filtered_layer_items:
            item.set_checked_quiet(False)
        self.mark_dirty()

    def on_search_changed(self, sender, args):
        self.apply_layer_filter()

    def execute_visibility(self, reset_all=False):
        views = self.get_target_views()
        if not views:
            forms.alert("No target views selected.")
            return False

        checked_cads = [x for x in self.cad_items if x.IsChecked and not x.IsHidden]
        if not checked_cads:
            forms.alert("Please select at least one visible CAD file.")
            return False

        show_cat_ids = set()
        hide_cat_ids = set()

        if reset_all:
            for c_item in checked_cads:
                for lid_set in c_item.Data.values():
                    show_cat_ids.update(lid_set)
            for item in self.all_layer_items:
                item.set_checked_quiet(True)
        else:
            layer_state_map = {x.Name: x.IsChecked for x in self.all_layer_items}
            for c_item in checked_cads:
                for lname, lid_set in c_item.Data.items():
                    if layer_state_map.get(lname, False):
                        show_cat_ids.update(lid_set)
                    else:
                        hide_cat_ids.update(lid_set)

        mod_targets = self.get_modification_targets(views)
        action_name = "Reset CAD Layers" if reset_all else "Apply CAD Layer Visibility"

        with revit.Transaction(action_name):
            for target_view in mod_targets:
                for cid in show_cat_ids:
                    try:
                        if target_view.CanCategoryBeHidden(cid):
                            target_view.SetCategoryHidden(cid, False)
                    except Exception:
                        pass
                for cid in hide_cat_ids:
                    try:
                        if target_view.CanCategoryBeHidden(cid):
                            target_view.SetCategoryHidden(cid, True)
                    except Exception:
                        pass

        uidoc.RefreshActiveView()
        self.mark_clean()
        return True

    def on_apply(self, sender, args):
        self.execute_visibility(reset_all=False)

    def on_reset(self, sender, args):
        self.execute_visibility(reset_all=True)

    def on_cancel(self, sender, args):
        self.win.Close()

    def show(self):
        self.win.ShowDialog()


if __name__ == "__main__":
    app = CADLayerWindow()
    app.show()
