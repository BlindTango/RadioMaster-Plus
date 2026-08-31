; RadioMaster+ Inno Setup Installer Script
; Requires Inno Setup 7
;
; The app itself is portable by default (paths.py write-probes its own
; folder and only falls back to per-user AppData/Music when that folder
; isn't writable), so "portable" here just means: skip Start Menu/Desktop
; shortcuts and file associations, and suggest a relocatable folder instead
; of Program Files.
;
; PrivilegesRequired=lowest avoids Inno's own native "install for all
; users/me only" chooser dialog -- with PrivilegesRequiredOverridesAllowed
; still set, admin users get the elevate-if-needed behavior, but everyone
; sees only the single custom "Choose Installation Type" page below instead
; of that page AND a redundant native one stacked in front of it.

#define MyAppName "RadioMaster+"
#define MyAppVersion "1.1.65"
#define MyAppPublisher "RadioMaster+ Team"
#define MyAppURL "https://radiomaster.app"
#define MyAppExeName "RadioMaster+.exe"

[Setup]
AppId={{B8A3C4D5-E6F7-4890-A1B2-C3D4E5F67890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/support
AppUpdatesURL={#MyAppURL}/download
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=RadioMaster+_Setup_v{#MyAppVersion}
SetupIconFile=..\resources\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
; Must match RadioMasterApp.INSTANCE_MUTEX_NAME in app.py exactly -- lets
; Setup detect a running RadioMaster+ *before* it starts overwriting
; files (and offer to close it) instead of only reacting after hitting a
; locked file mid-copy. Without this, the in-app updater's launch-
; installer-then-close-self sequence could race the installer overwriting
; _internal\*.dll against the old process still shutting down, leaving a
; corrupted DLL behind ("Failed to load Python DLL... LoadLibrary: the
; specified module could not be found" on the very next launch).
AppMutex=RadioMasterPlusSingleInstance
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Main application
Source: "..\dist\RadioMaster+\RadioMaster+.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\RadioMaster+\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Resources
Source: "..\resources\themes\*"; DestDir: "{app}\resources\themes"; Flags: ignoreversion

; Portable tools (ffmpeg, yt-dlp)
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: not IsPortableMode
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; Check: not IsPortableMode
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Check: not IsPortableMode

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Check: not IsPortableMode

[Registry]
; File associations (only for full install)
Root: "HKA"; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.mp3"; ValueData: ""; Flags: uninsdeletevalue; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3"; ValueType: string; ValueName: ""; ValueData: "MP3 Audio"; Flags: uninsdeletekey; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.flac"; ValueData: ""; Flags: uninsdeletevalue; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.flac\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.flac\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\.m4b\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.m4b"; ValueData: ""; Flags: uninsdeletevalue; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.m4b\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.m4b\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\.pls\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.pls"; ValueData: ""; Flags: uninsdeletevalue; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.pls\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Check: not IsPortableMode
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.pls\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Check: not IsPortableMode

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  InstallModePage: TInputOptionWizardPage;

function IsPortableMode: Boolean;
begin
  Result := InstallModePage.SelectedValueIndex = 1;
end;

// Whether an existing install of this exact AppId is already on the
// system (an update/reinstall) rather than a genuinely first-time
// install. Setup itself already knows this and auto-fills DirEdit with
// wherever that install actually lives -- CurPageChanged below used to
// unconditionally stomp on that with a freshly computed Full/Portable
// default every single time, so an update always "landed" wherever the
// Full/Portable choice implied instead of the folder the app was already
// running from. That's how an update could silently end up in a second,
// different location from the copy that launched it -- the previous
// install completely unaware it now had a stale sibling.
function IsUpgrade: Boolean;
var
  UninstallKey, Value: string;
begin
  UninstallKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8A3C4D5-E6F7-4890-A1B2-C3D4E5F67890}_is1';
  Result := RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', Value) or
            RegQueryStringValue(HKLM, UninstallKey, 'UninstallString', Value);
end;

procedure InitializeWizard;
begin
  InstallModePage := CreateInputOptionPage(wpWelcome,
    'Choose Installation Type', 'How would you like to set up ' + '{#MyAppName}' + '?',
    'Select an option, then click Next.',
    True, False);
  InstallModePage.Add('Full installation (Start Menu shortcuts, file associations, uninstaller)');
  InstallModePage.Add('Portable (copy to any folder you choose, e.g. a USB drive - no shortcuts)');
  InstallModePage.SelectedValueIndex := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // Only impose a computed default directory for a genuinely fresh
  // install -- an upgrade keeps whichever folder Setup already detected
  // the existing install in, so "run the installer to update" always
  // lands in the same place instead of leaving the question open.
  if (CurPageID = wpSelectDir) and not IsUpgrade then
  begin
    if IsPortableMode then
      WizardForm.DirEdit.Text := ExpandConstant('{sd}\RadioMaster+_Portable')
    else
      WizardForm.DirEdit.Text := ExpandConstant('{autopf}\{#MyAppName}');
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Skip Start Menu page for portable mode }
  if (PageID = wpSelectProgramGroup) and IsPortableMode then
    Result := True
  else
    Result := False;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  S: String;
begin
  S := '';
  S := S + 'Installation type: ';
  if IsPortableMode then
    S := S + 'Portable' + NewLine
  else
    S := S + 'Full installation' + NewLine;

  S := S + MemoDirInfo + NewLine;

  if not IsPortableMode then
  begin
    S := S + MemoGroupInfo + NewLine;
    S := S + MemoComponentsInfo + NewLine;
  end;

  S := S + MemoTasksInfo;
  Result := S;
end;
