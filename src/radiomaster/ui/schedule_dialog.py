"""Schedule add/edit dialog for recording schedules."""

import wx
import wx.adv
from datetime import datetime, timedelta
from typing import Any
from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import ScheduleRepository
from radiomaster.utils.accessibility import set_accessible_name


class ScheduleDialog(wx.Dialog):
    """Dialog for adding or editing recording schedules."""

    def __init__(
        self,
        parent: wx.Window,
        db: DatabaseManager,
        schedule_data: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the schedule dialog.
        
        Args:
            parent: Parent window
            db: Database manager instance
            schedule_data: Existing schedule data for edit mode, None for add mode
        """
        title = "Edit Recording Schedule" if schedule_data else "Add Recording Schedule"
        super().__init__(parent, title=title, size=(500, 600))
        
        self._db = db
        self._repo = ScheduleRepository(db)
        self._schedule_data = schedule_data
        self._result: dict[str, Any] | None = None
        
        self._setup_ui()
        self._load_data()
        
        self.Centre(wx.BOTH)
        # Land initial focus on the URL field (the first, most important
        # control) rather than the default button -- use CallAfter so it
        # sticks after ShowModal() gives the button sizer initial focus.
        wx.CallAfter(self._url_ctrl.SetFocus)

    def _setup_ui(self) -> None:
        """Create the dialog UI."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # URL
        url_label = wx.StaticText(panel, label="Stream/Podcast URL:")
        main_sizer.Add(url_label, 0, wx.ALL, 4)
        self._url_ctrl = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        set_accessible_name(self._url_ctrl, "Schedule URL")
        self._url_ctrl.SetMaxLength(1000)
        main_sizer.Add(self._url_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Title
        title_label = wx.StaticText(panel, label="Title:")
        main_sizer.Add(title_label, 0, wx.ALL, 4)
        self._title_ctrl = wx.TextCtrl(panel)
        set_accessible_name(self._title_ctrl, "Schedule Title")
        self._title_ctrl.SetMaxLength(200)
        main_sizer.Add(self._title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Source Type
        type_label = wx.StaticText(panel, label="Source Type:")
        main_sizer.Add(type_label, 0, wx.ALL, 4)
        self._type_combo = wx.ComboBox(
            panel,
            choices=["Radio Station", "Podcast", "Audiobook", "YouTube"],
            style=wx.CB_READONLY
        )
        set_accessible_name(self._type_combo, "Source Type")
        main_sizer.Add(self._type_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Start Time (using time picker)
        time_label = wx.StaticText(panel, label="Start Time:")
        main_sizer.Add(time_label, 0, wx.ALL, 4)
        self._time_picker = wx.adv.TimePickerCtrl(panel)
        set_accessible_name(self._time_picker, "Start Time")
        main_sizer.Add(self._time_picker, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Date (for one-time or start date of recurring)
        date_label = wx.StaticText(panel, label="Start Date:")
        main_sizer.Add(date_label, 0, wx.ALL, 4)
        self._date_picker = wx.adv.DatePickerCtrl(panel, style=wx.adv.DP_DROPDOWN | wx.adv.DP_SHOWCENTURY)
        set_accessible_name(self._date_picker, "Start Date")
        main_sizer.Add(self._date_picker, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        default_start = datetime.now() + timedelta(minutes=5)
        self._date_picker.SetValue(wx.DateTime.FromDMY(
            default_start.day,
            default_start.month - 1,
            default_start.year,
        ))
        self._time_picker.SetValue(wx.DateTime.FromHMS(
            default_start.hour,
            default_start.minute,
            0,
        ))
        
        # Duration
        duration_label = wx.StaticText(panel, label="Duration (minutes, 0 = until end):")
        main_sizer.Add(duration_label, 0, wx.ALL, 4)
        self._duration_spin = wx.SpinCtrl(panel, min=0, max=1440, initial=60)
        set_accessible_name(self._duration_spin, "Duration")
        main_sizer.Add(self._duration_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Recurrence
        recurrence_label = wx.StaticText(panel, label="Recurrence:")
        main_sizer.Add(recurrence_label, 0, wx.ALL, 4)
        self._recurrence_combo = wx.ComboBox(
            panel,
            choices=["None", "Daily", "Weekly", "Monthly", "Weekdays"],
            style=wx.CB_READONLY
        )
        set_accessible_name(self._recurrence_combo, "Recurrence")
        self._recurrence_combo.SetValue("None")
        main_sizer.Add(self._recurrence_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Format
        format_label = wx.StaticText(panel, label="Recording Format:")
        main_sizer.Add(format_label, 0, wx.ALL, 4)
        self._format_combo = wx.ComboBox(
            panel,
            choices=["auto", "mp3", "aac", "opus", "wav", "flac"],
            style=wx.CB_READONLY
        )
        set_accessible_name(self._format_combo, "Recording Format")
        self._format_combo.SetValue("auto")
        main_sizer.Add(self._format_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        
        # Enabled checkbox
        self._enabled_check = wx.CheckBox(panel, label="Enabled")
        set_accessible_name(self._enabled_check, "Schedule Enabled")
        self._enabled_check.SetValue(True)
        main_sizer.Add(self._enabled_check, 0, wx.ALL, 4)
        
        # Buttons
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok = wx.Button(panel, wx.ID_OK, "Save")
        set_accessible_name(btn_ok, "Save Schedule")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        set_accessible_name(btn_cancel, "Cancel Schedule")
        
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        
        panel.SetSizer(main_sizer)
        
        # Bind events
        self.Bind(wx.EVT_BUTTON, self._on_ok, btn_ok)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, btn_cancel)
        self._url_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_ok)

    def _load_data(self) -> None:
        """Load existing schedule data if in edit mode."""
        if self._schedule_data:
            self._url_ctrl.SetValue(self._schedule_data.get('url', ''))
            self._title_ctrl.SetValue(self._schedule_data.get('title', ''))
            
            # Set source type
            source_type = self._schedule_data.get('source_type', 'Radio Station')
            idx = self._type_combo.FindString(source_type)
            if idx != wx.NOT_FOUND:
                self._type_combo.SetSelection(idx)
            
            # Parse start_time (format: "YYYY-MM-DD HH:MM")
            start_time_str = self._schedule_data.get('start_time', '')
            if start_time_str:
                try:
                    start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
                    self._date_picker.SetValue(wx.DateTime.FromDMY(
                        start_dt.day, start_dt.month - 1, start_dt.year
                    ))
                    self._time_picker.SetValue(wx.DateTime.FromHMS(
                        start_dt.hour, start_dt.minute, start_dt.second
                    ))
                except ValueError:
                    pass
            
            # Set duration
            duration = self._schedule_data.get('duration', 60)
            self._duration_spin.SetValue(duration)
            
            # Set recurrence
            recurrence = self._schedule_data.get('recurrence', 'None')
            idx = self._recurrence_combo.FindString(recurrence)
            if idx != wx.NOT_FOUND:
                self._recurrence_combo.SetSelection(idx)
            
            # Set format
            format_val = self._schedule_data.get('format', 'auto')
            idx = self._format_combo.FindString(format_val)
            if idx != wx.NOT_FOUND:
                self._format_combo.SetSelection(idx)
            
            # Set enabled
            enabled = self._schedule_data.get('enabled', 1)
            self._enabled_check.SetValue(bool(enabled))
    def _on_ok(self, event: wx.CommandEvent) -> None:
        """Handle OK button - validate and save."""
        # Validate
        url = self._url_ctrl.GetValue().strip()
        title = self._title_ctrl.GetValue().strip()
        
        if not url:
            wx.MessageBox("Please enter a URL.", "Validation Error", wx.OK | wx.ICON_ERROR)
            self._url_ctrl.SetFocus()
            return
        
        if not title:
            wx.MessageBox("Please enter a title.", "Validation Error", wx.OK | wx.ICON_ERROR)
            self._title_ctrl.SetFocus()
            return
        
        # Collect data
        date = self._date_picker.GetValue()
        time = self._time_picker.GetValue()
        
        start_datetime = datetime(
            date.year, date.month + 1, date.day,
            time.hour, time.minute, time.second
        )

        if self._enabled_check.GetValue() and start_datetime <= datetime.now():
            wx.MessageBox(
                "Start date and time must be in the future for an enabled schedule.",
                "Validation Error",
                wx.OK | wx.ICON_ERROR,
            )
            self._date_picker.SetFocus()
            return

        start_time = start_datetime.strftime("%Y-%m-%d %H:%M")
        
        self._result = {
            'url': url,
            'title': title,
            'source_type': self._type_combo.GetValue(),
            'start_time': start_time,
            'duration': self._duration_spin.GetValue(),
            'recurrence': self._recurrence_combo.GetValue(),
            'format': self._format_combo.GetValue(),
            'enabled': 1 if self._enabled_check.GetValue() else 0,
        }
        
        # Save to database
        try:
            if self._schedule_data:
                # Update existing
                self._repo.update(
                    self._schedule_data.get('id', 0),
                    **self._result
                )
                self._result['id'] = self._schedule_data.get('id', 0)
            else:
                # Add new
                self._result['id'] = self._repo.add(**self._result)
            
            self.EndModal(wx.ID_OK)
        except Exception as e:
            wx.MessageBox(f"Error saving schedule: {str(e)}", "Database Error", wx.OK | wx.ICON_ERROR)

    def _on_cancel(self, event: wx.CommandEvent) -> None:
        """Handle cancel button."""
        self.EndModal(wx.ID_CANCEL)

    def get_result(self) -> dict[str, Any] | None:
        """Get the schedule data if saved successfully."""
        return self._result
