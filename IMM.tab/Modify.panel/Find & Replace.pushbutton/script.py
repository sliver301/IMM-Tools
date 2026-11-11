# -*- coding: utf-8 -*-
import clr
import re

clr.AddReference('System')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System.Windows import Window, Visibility
from System.Windows.Input import Key
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

XAML_LAYOUT = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Find &amp; Replace Parameters" Height="650" Width="820"
        MinHeight="550" MinWidth="700"
        WindowStartupLocation="CenterScreen"
        Background="#202023" Foreground="#E0E0E0"
        FontFamily="Segoe UI" FontSize="13">

    <Window.Resources>
        <!-- Dark ComboBox Template -->
        <ControlTemplate x:Key="DarkComboBoxTemplate" TargetType="{x:Type ComboBox}">
            <Grid>
                <ToggleButton x:Name="ToggleButton" 
                              Focusable="False" 
                              IsChecked="{Binding Path=IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}" 
                              ClickMode="Press">
                    <ToggleButton.Template>
                        <ControlTemplate TargetType="{x:Type ToggleButton}">
                            <Border x:Name="Border" Background="#2D2D30" BorderBrush="#434346" BorderThickness="1" CornerRadius="3">
                                <Grid>
                                    <Grid.ColumnDefinitions>
                                        <ColumnDefinition Width="*"/>
                                        <ColumnDefinition Width="26"/>
                                    </Grid.ColumnDefinitions>
                                    <Path x:Name="Arrow" Grid.Column="1" Fill="#CCCCCC" HorizontalAlignment="Center" VerticalAlignment="Center" Data="M 0 0 L 4 4 L 8 0 Z"/>
                                </Grid>
                            </Border>
                            <ControlTemplate.Triggers>
                                <Trigger Property="IsMouseOver" Value="True">
                                    <Setter TargetName="Border" Property="BorderBrush" Value="#007ACC"/>
                                </Trigger>
                            </ControlTemplate.Triggers>
                        </ControlTemplate>
                    </ToggleButton.Template>
                </ToggleButton>

                <ContentPresenter x:Name="ContentSite" 
                                  IsHitTestVisible="False" 
                                  Content="{TemplateBinding SelectionBoxItem}" 
                                  ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}" 
                                  ContentTemplateSelector="{TemplateBinding ItemTemplateSelector}" 
                                  TextElement.Foreground="#FFFFFF"
                                  Margin="8,4,26,4" 
                                  VerticalAlignment="Center" 
                                  HorizontalAlignment="Left"/>

                <!-- Dropdown Popup -->
                <Popup x:Name="Popup" 
                       Placement="Bottom" 
                       IsOpen="{TemplateBinding IsDropDownOpen}" 
                       AllowsTransparency="True" 
                       Focusable="False" 
                       PopupAnimation="Slide">
                    <Grid x:Name="DropDown" 
                          MinWidth="{TemplateBinding ActualWidth}" 
                          MaxHeight="{TemplateBinding MaxDropDownHeight}" 
                          SnapsToDevicePixels="True">
                        <Border x:Name="DropDownBorder" Background="#252526" BorderBrush="#434346" BorderThickness="1" CornerRadius="2">
                            <ScrollViewer CanContentScroll="True" SnapsToDevicePixels="True" Background="#252526">
                                <StackPanel IsItemsHost="True" Background="#252526"/>
                            </ScrollViewer>
                        </Border>
                    </Grid>
                </Popup>
            </Grid>
        </ControlTemplate>

        <Style TargetType="{x:Type ComboBox}">
            <Setter Property="Template" Value="{StaticResource DarkComboBoxTemplate}"/>
            <Setter Property="MaxDropDownHeight" Value="320"/>
            <Setter Property="Height" Value="28"/>
        </Style>

        <!-- Dropdown Items Style -->
        <Style TargetType="{x:Type ComboBoxItem}">
            <Setter Property="Background" Value="#252526"/>
            <Setter Property="Foreground" Value="#FFFFFF"/>
            <Setter Property="Padding" Value="8,5"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="{x:Type ComboBoxItem}">
                        <Border x:Name="ItemBorder" Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Left" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsHighlighted" Value="True">
                                <Setter TargetName="ItemBorder" Property="Background" Value="#007ACC"/>
                                <Setter Property="Foreground" Value="#FFFFFF"/>
                            </Trigger>
                            <Trigger Property="IsSelected" Value="True">
                                <Setter TargetName="ItemBorder" Property="Background" Value="#005A9E"/>
                                <Setter Property="Foreground" Value="#FFFFFF"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style TargetType="TextBox">
            <Setter Property="Background" Value="#2D2D30"/>
            <Setter Property="Foreground" Value="#FFFFFF"/>
            <Setter Property="CaretBrush" Value="#FFFFFF"/>
            <Setter Property="BorderBrush" Value="#434346"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Padding" Value="6,4"/>
            <Setter Property="VerticalContentAlignment" Value="Center"/>
        </Style>

        <Style TargetType="TextBlock">
            <Setter Property="Foreground" Value="#CCCCCC"/>
            <Setter Property="VerticalAlignment" Value="Center"/>
        </Style>

        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="#E0E0E0"/>
            <Setter Property="VerticalAlignment" Value="Center"/>
        </Style>
    </Window.Resources>

    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Category & Parameter Selection -->
        <Border Grid.Row="0" Background="#28282C" CornerRadius="4" Padding="14" Margin="0,0,0,12" BorderBrush="#38383D" BorderThickness="1">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="30"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>

                <TextBlock Grid.Row="0" Grid.Column="0" Text="Category:" FontWeight="SemiBold" Margin="0,0,10,0"/>
                <ComboBox Grid.Row="0" Grid.Column="1" x:Name="CmbCategories"/>

                <TextBlock Grid.Row="0" Grid.Column="3" Text="Parameter:" FontWeight="SemiBold" Margin="0,0,10,0"/>
                <ComboBox Grid.Row="0" Grid.Column="4" x:Name="CmbParameters"/>

                <TextBlock Grid.Row="1" Grid.Column="0" Grid.ColumnSpan="5" x:Name="TxtStatus" Foreground="#888888" FontSize="11" Margin="0,8,0,0"/>
            </Grid>
        </Border>

        <!-- Operation Fields -->
        <Border Grid.Row="1" Background="#28282C" CornerRadius="4" Padding="14" Margin="0,0,0,12" BorderBrush="#38383D" BorderThickness="1">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="8"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="65"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="20"/>
                    <ColumnDefinition Width="65"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="15"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>

                <TextBlock Grid.Row="0" Grid.Column="0" Text="Find:"/>
                <TextBox Grid.Row="0" Grid.Column="1" x:Name="TxtFind" Height="28"/>

                <TextBlock Grid.Row="0" Grid.Column="3" Text="Replace:"/>
                <TextBox Grid.Row="0" Grid.Column="4" x:Name="TxtReplace" Height="28"/>

                <CheckBox Grid.Row="0" Grid.Column="6" x:Name="ChkMatchCase" Content="Match Case"/>

                <TextBlock Grid.Row="2" Grid.Column="0" Text="Prefix:"/>
                <TextBox Grid.Row="2" Grid.Column="1" x:Name="TxtPrefix" Height="28"/>

                <TextBlock Grid.Row="2" Grid.Column="3" Text="Suffix:"/>
                <TextBox Grid.Row="2" Grid.Column="4" x:Name="TxtSuffix" Height="28"/>
            </Grid>
        </Border>

        <!-- Preview Grid -->
        <Border Grid.Row="2" Background="#28282C" CornerRadius="4" BorderBrush="#38383D" BorderThickness="1" Margin="0,0,0,14">
            <DataGrid x:Name="DgPreview" AutoGenerateColumns="False" CanUserAddRows="False"
                      CanUserDeleteRows="False" IsReadOnly="True" HeadersVisibility="Column"
                      GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#333337"
                      Background="Transparent" RowBackground="#232326" AlternatingRowBackground="#28282C"
                      Foreground="#EEEEEE" BorderThickness="0" SelectionMode="Extended">
                <DataGrid.Resources>
                    <Style TargetType="DataGridColumnHeader">
                        <Setter Property="Background" Value="#333337"/>
                        <Setter Property="Foreground" Value="#DDDDDD"/>
                        <Setter Property="FontWeight" Value="SemiBold"/>
                        <Setter Property="Padding" Value="8,6"/>
                        <Setter Property="BorderThickness" Value="0,0,1,1"/>
                        <Setter Property="BorderBrush" Value="#3E3E42"/>
                    </Style>
                    <Style TargetType="DataGridCell">
                        <Setter Property="Padding" Value="6,4"/>
                        <Setter Property="Template">
                            <Setter.Value>
                                <ControlTemplate TargetType="DataGridCell">
                                    <Border Padding="{TemplateBinding Padding}" Background="{TemplateBinding Background}">
                                        <ContentPresenter VerticalAlignment="Center"/>
                                    </Border>
                                </ControlTemplate>
                            </Setter.Value>
                        </Setter>
                    </Style>
                </DataGrid.Resources>
                <DataGrid.Columns>
                    <DataGridTextColumn Header="Element ID" Binding="{Binding Id}" Width="95"/>
                    <DataGridTextColumn Header="Element Name" Binding="{Binding Name}" Width="190"/>
                    <DataGridTextColumn Header="Original Value" Binding="{Binding OldValue}" Width="*"/>
                    <DataGridTextColumn Header="New Value" Binding="{Binding NewValue}" Width="*">
                        <DataGridTextColumn.ElementStyle>
                            <Style TargetType="TextBlock">
                                <Setter Property="FontWeight" Value="SemiBold"/>
                                <Setter Property="Foreground" Value="#81C784"/>
                            </Style>
                        </DataGridTextColumn.ElementStyle>
                    </DataGridTextColumn>
                </DataGrid.Columns>
            </DataGrid>
        </Border>

        <!-- Footer Actions -->
        <Grid Grid.Row="3">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="10"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>

            <TextBlock Grid.Column="0" x:Name="TxtItemCount" Foreground="#888888" VerticalAlignment="Center"/>

            <Button Grid.Column="1" Content="Apply" Width="100" Height="32" Background="#007ACC" Foreground="White"
                    FontWeight="SemiBold" BorderThickness="0" Cursor="Hand" Click="OnApply"/>

            <Button Grid.Column="3" Content="Close" Width="90" Height="32" Background="#4A4A4F" Foreground="White"
                    BorderThickness="0" Cursor="Hand" IsCancel="True" Click="OnClose"/>
        </Grid>
    </Grid>
</Window>
"""


class PreviewItem(object):
    def __init__(self, element, old_value, new_value):
        self.Element = element
        self.Id = str(element.Id)
        try:
            self.Name = element.Name
        except Exception:
            self.Name = str(element.Id)
        self.OldValue = old_value if old_value is not None else ""
        self.NewValue = new_value if new_value is not None else ""


class FindReplaceWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML_LAYOUT, literal_string=True)

        self.initial_selection = []
        self.cat_to_selected_elements = {}
        self.current_elements = []
        self.preview_items = []
        self._updating_preview = False

        self.TxtFind.TextChanged += self.OnFormInputsChanged
        self.TxtReplace.TextChanged += self.OnFormInputsChanged
        self.TxtPrefix.TextChanged += self.OnFormInputsChanged
        self.TxtSuffix.TextChanged += self.OnFormInputsChanged
        self.ChkMatchCase.Checked += self.OnFormInputsChanged
        self.ChkMatchCase.Unchecked += self.OnFormInputsChanged
        self.CmbCategories.SelectionChanged += self.OnCategoryChanged
        self.CmbParameters.SelectionChanged += self.OnParameterChanged
        self.KeyDown += self.OnWindowKeyDown

        self.init_source_selection()

    def init_source_selection(self):
        sel_ids = uidoc.Selection.GetElementIds()
        valid_elements = []
        for eid in sel_ids:
            elem = doc.GetElement(eid)
            if elem and elem.Category:
                valid_elements.append(elem)

        self.initial_selection = valid_elements

        if self.initial_selection:
            for elem in self.initial_selection:
                cat_name = elem.Category.Name
                if cat_name not in self.cat_to_selected_elements:
                    self.cat_to_selected_elements[cat_name] = []
                self.cat_to_selected_elements[cat_name].append(elem)

            cat_names = sorted(list(self.cat_to_selected_elements.keys()))
            self.CmbCategories.ItemsSource = cat_names

            if len(cat_names) == 1:
                self.TxtStatus.Text = "Applied to selected elements ({0} items)".format(len(self.initial_selection))
            else:
                self.TxtStatus.Text = "Multiple categories in selection. Choose category to proceed."
            self.CmbCategories.SelectedIndex = 0
        else:
            model_categories = []
            for cat in doc.Settings.Categories:
                if cat.CategoryType == DB.CategoryType.Model and cat.AllowsBoundParameters:
                    model_categories.append(cat.Name)
            model_categories.sort()
            self.CmbCategories.ItemsSource = model_categories
            self.TxtStatus.Text = "No pre-selection. Showing all model categories."
            if model_categories:
                self.CmbCategories.SelectedIndex = 0

    def OnCategoryChanged(self, sender, args):
        cat_name = self.CmbCategories.SelectedItem
        if not cat_name:
            return

        if self.initial_selection:
            self.current_elements = self.cat_to_selected_elements.get(cat_name, [])
        else:
            category = None
            for c in doc.Settings.Categories:
                if c.Name == cat_name:
                    category = c
                    break

            if category:
                collector = DB.FilteredElementCollector(doc)\
                              .OfCategoryId(category.Id)\
                              .WhereElementIsNotElementType()\
                              .ToElements()
                self.current_elements = [e for e in collector if e is not None]
            else:
                self.current_elements = []

        self.populate_parameters()

    def populate_parameters(self):
        param_names = set()
        for elem in self.current_elements:
            for p in elem.Parameters:
                if not p.IsReadOnly and p.StorageType == DB.StorageType.String:
                    param_names.add(p.Definition.Name)

        sorted_params = sorted(list(param_names))
        self.CmbParameters.SelectionChanged -= self.OnParameterChanged
        self.CmbParameters.ItemsSource = sorted_params
        if sorted_params:
            self.CmbParameters.SelectedIndex = 0
        self.CmbParameters.SelectionChanged += self.OnParameterChanged

        self.update_preview()

    def OnParameterChanged(self, sender, args):
        self.update_preview()

    def OnFormInputsChanged(self, sender, args):
        self.update_preview()

    def update_preview(self):
        if self._updating_preview:
            return
        self._updating_preview = True

        selected_param = self.CmbParameters.SelectedItem
        if not selected_param or not self.current_elements:
            self.DgPreview.ItemsSource = []
            self.TxtItemCount.Text = "0 elements"
            self._updating_preview = False
            return

        find_txt = self.TxtFind.Text or ""
        replace_txt = self.TxtReplace.Text or ""
        prefix_txt = self.TxtPrefix.Text or ""
        suffix_txt = self.TxtSuffix.Text or ""
        match_case = (self.ChkMatchCase.IsChecked == True)

        new_items = []
        for elem in self.current_elements:
            p = elem.LookupParameter(selected_param)
            if not p or p.IsReadOnly:
                continue

            old_val = p.AsString()
            old_val = old_val if old_val is not None else ""
            transformed = old_val

            if find_txt:
                if match_case:
                    transformed = transformed.replace(find_txt, replace_txt)
                else:
                    pattern = re.compile(re.escape(find_txt), re.IGNORECASE)
                    transformed = pattern.sub(replace_txt, transformed)

            if prefix_txt or suffix_txt:
                transformed = prefix_txt + transformed + suffix_txt

            new_items.append(PreviewItem(elem, old_val, transformed))

        self.preview_items = new_items
        self.DgPreview.ItemsSource = self.preview_items
        self.TxtItemCount.Text = "{0} element(s) loaded".format(len(self.preview_items))
        self._updating_preview = False

    def OnApply(self, sender, args):
        selected_param = self.CmbParameters.SelectedItem
        if not selected_param or not self.preview_items:
            forms.alert("No elements or parameter selected to apply.", title="Notice")
            return

        modified_count = 0
        with revit.Transaction("Find & Replace: " + str(selected_param)):
            for item in self.preview_items:
                if item.OldValue != item.NewValue:
                    p = item.Element.LookupParameter(selected_param)
                    if p and not p.IsReadOnly:
                        try:
                            p.Set(item.NewValue)
                            modified_count += 1
                        except Exception:
                            pass

        self.TxtFind.Text = ""
        self.TxtReplace.Text = ""
        self.TxtPrefix.Text = ""
        self.TxtSuffix.Text = ""

        self.update_preview()
        self.TxtItemCount.Text = "Applied successfully ({0} updated).".format(modified_count)

    def OnClose(self, sender, args):
        self.Close()

    def OnWindowKeyDown(self, sender, args):
        if args.Key == Key.Escape:
            self.Close()


if __name__ == "__main__":
    window = FindReplaceWindow()
    window.ShowDialog()
