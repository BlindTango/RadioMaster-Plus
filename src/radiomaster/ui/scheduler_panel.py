"""Scheduler tab panel for managing recording schedules."""

from typing import Any

import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import ScheduleRepository
from radiomaster.ui.schedule_dialog import ScheduleDialog
from radiomaster.utils.accessibility import set_accessible_name


class SchedulerPanel(wx.Panel):
    """Panel for managing recording schedules."""

    def __init__(self, parent: wx.Window, db: DatabaseManager, scheduler_service: Any = None) -> None:
        super().__init__(parent)
        self._db = db
        self._repo = ScheduleRepository(db)
        self._scheduler_service = scheduler_service
        self._setup_ui()
        self._load_schedules()

    def _resync_service(self) -> None:
        """Push the current DB state to the live SchedulerService.

        The UI only ever writes schedules to SQLite; without this the
        monitor loop's in-memory schedule list never learns about
        additions/edits/deletions and recordings never fire.
        """
        if self._scheduler_service is not None:
            self._scheduler_service.load_schedules(self._repo.get_all())

    def _setup_ui(self) -> None:
        """Create the scheduler panel layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Scheduled recordings
        main_sizer.Add(wx.StaticText(self, label="Scheduled Recordings"), 0, wx.ALL, 4)

        self._schedule_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._schedule_list, "Scheduled Recordings")
        self._schedule_list.AppendColumn("Title", width=200)
        self._schedule_list.AppendColumn("Start Time", width=120)
        self._schedule_list.AppendColumn("Duration", width=70)
        self._schedule_list.AppendColumn("Recurrence", width=100)
        self._schedule_list.AppendColumn("Status", width=80)
        main_sizer.Add(self._schedule_list, 1, wx.EXPAND | wx.ALL, 4)

        # Controls
        ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_add = wx.Button(self, label="Add Schedule...")
        set_accessible_name(self._btn_add, "Add Schedule")
        ctrl_sizer.Add(self._btn_add, 0, wx.RIGHT, 4)

        self._btn_edit = wx.Button(self, label="Edit...")
        set_accessible_name(self._btn_edit, "Edit Schedule")
        ctrl_sizer.Add(self._btn_edit, 0, wx.RIGHT, 4)

        self._btn_delete = wx.Button(self, label="Delete")
        set_accessible_name(self._btn_delete, "Delete Schedule")
        ctrl_sizer.Add(self._btn_delete, 0)

        main_sizer.Add(ctrl_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 4)

        self.SetSizer(main_sizer)

        self._btn_add.Bind(wx.EVT_BUTTON, self._on_add)
        self._btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
        self._btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)

    def _load_schedules(self) -> None:
        """Load schedules from database into the list."""
        self._schedule_list.DeleteAllItems()
        schedules = self._repo.get_all()
        
        for schedule in schedules:
            idx = self._schedule_list.InsertItem(
                self._schedule_list.GetItemCount(),
                schedule.get('title', 'Unknown')
            )
            self._schedule_list.SetItem(idx, 1, schedule.get('start_time', ''))
            self._schedule_list.SetItem(idx, 2, f"{schedule.get('duration', 0)} min")
            self._schedule_list.SetItem(idx, 3, schedule.get('recurrence', 'None'))
            self._schedule_list.SetItem(idx, 4, "Active" if schedule.get('enabled') else "Disabled")
            self._schedule_list.SetItemData(idx, schedule['id'])

    def _on_add(self, event: wx.CommandEvent) -> None:
        """Add a new recording schedule."""
        dlg = ScheduleDialog(self, self._db)
        if dlg.ShowModal() == wx.ID_OK:
            self._load_schedules()
            self._resync_service()
        dlg.Destroy()

    def _on_edit(self, event: wx.CommandEvent) -> None:
        """Edit the selected schedule."""
        idx = self._schedule_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Please select a schedule to edit.", "No Selection", 
                         wx.OK | wx.ICON_WARNING)
            return
        
        # Get schedule data
        schedule_id = self._schedule_list.GetItemData(idx)
        schedule_data = None
        for schedule in self._repo.get_all():
            if schedule['id'] == schedule_id:
                schedule_data = schedule
                break
        
        if schedule_data:
            dlg = ScheduleDialog(self, self._db, schedule_data)
            if dlg.ShowModal() == wx.ID_OK:
                self._load_schedules()
                self._resync_service()
            dlg.Destroy()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        """Delete the selected schedule."""
        idx = self._schedule_list.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Please select a schedule to delete.", "No Selection",
                         wx.OK | wx.ICON_WARNING)
            return
        
        schedule_id = self._schedule_list.GetItemData(idx)
        dlg = wx.MessageDialog(self, "Delete this schedule?", "Confirm",
                               wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self._repo.delete(schedule_id)
            self._load_schedules()
            self._resync_service()
        dlg.Destroy()
