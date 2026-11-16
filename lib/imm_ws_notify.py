# -*- coding: utf-8 -*-
"""IMM Worksets: small rounded notices in the bottom-right corner of the
screen that holds the Revit window. They never take focus, fade out on their
own, and pause while the mouse is over them so their buttons stay clickable.
"""
import time

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

from System import TimeSpan
from System.Windows import Duration, PresentationSource, UIElement, Visibility
from System.Windows.Controls import Button
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Animation import DoubleAnimation
from System.Windows.Threading import DispatcherTimer
import System.Windows.Forms as WinForms

import imm_ws_common as common

KIND_INFO = 'info'
KIND_SUCCESS = 'success'
KIND_WARN = 'warn'
KIND_DANGER = 'danger'

ACCENTS = {
    KIND_INFO: '#2F6FEB',
    KIND_SUCCESS: '#1F9D55',
    KIND_WARN: '#E8590C',
    KIND_DANGER: '#D1242F',
}

LIGHT = {'BG': '#FFFFFF', 'BORDER': '#E3E6EA', 'FG': '#1F2328', 'FG2': '#59636E',
         'BTN2': '#F3F4F6', 'BTN2H': '#E7E9EC'}
DARK = {'BG': '#2B2F36', 'BORDER': '#3D434C', 'FG': '#F0F3F6', 'FG2': '#B3BCC6',
        'BTN2': '#3A4049', 'BTN2H': '#454C57'}

TOAST_XAML = u'''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        ShowInTaskbar="False" ShowActivated="False" Topmost="False"
        ResizeMode="NoResize" SizeToContent="Height" Width="390" Opacity="0"
        FontFamily="Segoe UI">
  <Window.Resources>
    <Style x:Key="Primary" TargetType="Button">
      <Setter Property="Foreground" Value="White"/>
      <Setter Property="Background" Value="@ACCENT@"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="{TemplateBinding Background}" CornerRadius="6" Padding="12,5">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Opacity" Value="0.88"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="Secondary" TargetType="Button">
      <Setter Property="Foreground" Value="@FG@"/>
      <Setter Property="Background" Value="@BTN2@"/>
      <Setter Property="FontSize" Value="12"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Margin" Value="0,0,8,0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="{TemplateBinding Background}" CornerRadius="6" Padding="12,5">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Background" Value="@BTN2H@"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
  <Border Margin="16" CornerRadius="12" Background="@BG@" BorderBrush="@BORDER@" BorderThickness="1">
    <Border.Effect>
      <DropShadowEffect BlurRadius="20" ShadowDepth="3" Direction="270" Opacity="0.22" Color="Black"/>
    </Border.Effect>
    <Grid Margin="0,0,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="5"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <Border Grid.Column="0" Background="@ACCENT@" CornerRadius="12,0,0,12"/>
      <StackPanel Grid.Column="1" Margin="14,12,4,13">
        <TextBlock x:Name="TitleText" FontSize="13" FontWeight="SemiBold" Foreground="@FG@" TextWrapping="Wrap"/>
        <TextBlock x:Name="BodyText" FontSize="12" Foreground="@FG2@" TextWrapping="Wrap" Margin="0,3,0,0"/>
        <CheckBox x:Name="Check" FontSize="11" Foreground="@FG2@" Margin="0,9,0,0" Visibility="Collapsed"/>
        <WrapPanel x:Name="Buttons" Margin="0,10,0,0" Visibility="Collapsed"/>
      </StackPanel>
      <Button x:Name="CloseButton" Grid.Column="2" VerticalAlignment="Top" Margin="0,8,8,0"
              Width="22" Height="22" Cursor="Hand" ToolTip="Close">
        <Button.Template>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="Transparent" CornerRadius="11">
              <TextBlock Text="&#x2715;" FontSize="11" Foreground="@FG2@" HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Background" Value="@BTN2@"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Button.Template>
      </Button>
    </Grid>
  </Border>
</Window>
'''


class Notice(object):
    """One notice. buttons = [(label, callback(checked), primary)]."""

    def __init__(self, title, body='', kind=KIND_INFO, buttons=None,
                 check_text=None, key=None, seconds=None):
        self.title = title
        self.body = body
        self.kind = kind
        self.buttons = buttons or []
        self.check_text = check_text
        self.key = key or title
        self.seconds = seconds


class Notifier(object):
    DEDUPE_SECONDS = 20
    MAX_QUEUE = 6

    def __init__(self, main_hwnd=None, seconds_getter=None):
        self.main_hwnd = main_hwnd
        self.seconds_getter = seconds_getter
        self.queue = []
        self.current = None
        self.recent = {}

    # ------------------------------------------------------------------
    def show(self, notice):
        now = time.time()
        last = self.recent.get(notice.key)
        if last is not None and now - last < self.DEDUPE_SECONDS:
            return
        for queued in self.queue:
            if queued.key == notice.key:
                return
        self.recent[notice.key] = now
        if len(self.queue) >= self.MAX_QUEUE:
            self.queue.pop(0)
        self.queue.append(notice)
        if self.current is None:
            self._next()

    def close_all(self):
        self.queue = []
        if self.current is not None:
            try:
                self.current['win'].Close()
            except Exception:
                pass
        self.current = None

    # ------------------------------------------------------------------
    def _seconds(self, notice):
        if notice.seconds:
            return notice.seconds
        try:
            return int(self.seconds_getter()) if self.seconds_getter else 5
        except Exception:
            return 5

    def _xaml(self, kind):
        palette = DARK if common.is_dark_theme() else LIGHT
        text = TOAST_XAML.replace('@ACCENT@', ACCENTS.get(kind, ACCENTS[KIND_INFO]))
        for key, value in palette.items():
            text = text.replace('@' + key + '@', value)
        return text

    def _next(self):
        self.current = None
        while self.queue:
            notice = self.queue.pop(0)
            try:
                self._open(notice)
                return
            except Exception:
                self.current = None
                continue

    def _open(self, notice):
        win = XamlReader.Parse(self._xaml(notice.kind))
        state = {'win': win, 'notice': notice, 'closing': False, 'done': False}
        self.current = state

        win.FindName('TitleText').Text = notice.title
        body = win.FindName('BodyText')
        if notice.body:
            body.Text = notice.body
        else:
            body.Visibility = Visibility.Collapsed
        check = win.FindName('Check')
        if notice.check_text:
            check.Content = notice.check_text
            check.Visibility = Visibility.Visible
        panel = win.FindName('Buttons')
        if notice.buttons:
            panel.Visibility = Visibility.Visible
            for label, callback, primary in notice.buttons:
                btn = Button()
                btn.Content = label
                btn.Style = win.FindResource('Primary' if primary else 'Secondary')
                btn.Click += self._make_click(state, callback)
                panel.Children.Add(btn)
        win.FindName('CloseButton').Click += self._make_click(state, None)

        try:
            if self.main_hwnd:
                WindowInteropHelper(win).Owner = self.main_hwnd
        except Exception:
            pass

        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromSeconds(self._seconds(notice))
        timer.Tick += lambda s, e: self._fade_out(state)
        state['timer'] = timer

        win.MouseEnter += lambda s, e: self._pause(state)
        win.MouseLeave += lambda s, e: self._resume(state)
        win.Closed += lambda s, e: self._closed(state)

        win.Show()
        self._place(win)
        self._fade(win, 0.0, 1.0, 220)
        timer.Start()

    def _make_click(self, state, callback):
        def handler(sender, args):
            checked = False
            try:
                checked = bool(state['win'].FindName('Check').IsChecked)
            except Exception:
                pass
            self._close(state)
            if callback is not None:
                try:
                    callback(checked)
                except Exception:
                    pass
            elif state['notice'].check_text and checked:
                # closing with "don't ask again" ticked counts as the
                # secondary button (Cancel) with the box ticked
                for label, cb, primary in state['notice'].buttons:
                    if not primary:
                        try:
                            cb(checked)
                        except Exception:
                            pass
                        break
        return handler

    def _place(self, win):
        try:
            hwnd = self.main_hwnd if self.main_hwnd else WindowInteropHelper(win).Handle
            screen = WinForms.Screen.FromHandle(hwnd)
        except Exception:
            screen = WinForms.Screen.PrimaryScreen
        area = screen.WorkingArea
        sx = sy = 1.0
        try:
            source = PresentationSource.FromVisual(win)
            matrix = source.CompositionTarget.TransformToDevice
            sx, sy = matrix.M11, matrix.M22
        except Exception:
            pass
        win.UpdateLayout()
        win.Left = area.Right / sx - win.ActualWidth - 4
        win.Top = area.Bottom / sy - win.ActualHeight - 4

    def _fade(self, win, start, end, ms, done=None):
        anim = DoubleAnimation(start, end, Duration(TimeSpan.FromMilliseconds(ms)))
        if done is not None:
            anim.Completed += lambda s, e: done()
        win.BeginAnimation(UIElement.OpacityProperty, anim)

    def _pause(self, state):
        if state['done']:
            return
        state['timer'].Stop()
        state['closing'] = False
        win = state['win']
        win.BeginAnimation(UIElement.OpacityProperty, None)
        win.Opacity = 1.0

    def _resume(self, state):
        if state['done']:
            return
        state['timer'].Stop()
        state['timer'].Start()

    def _fade_out(self, state):
        state['timer'].Stop()
        if state['done']:
            return
        state['closing'] = True

        def finish():
            if state['closing']:
                self._close(state)
        self._fade(state['win'], state['win'].Opacity, 0.0, 450, finish)

    def _close(self, state):
        if state['done']:
            return
        state['done'] = True
        try:
            state['timer'].Stop()
        except Exception:
            pass
        try:
            state['win'].Close()
        except Exception:
            self._closed(state)

    def _closed(self, state):
        state['done'] = True
        if self.current is state:
            self.current = None
            self._next()
