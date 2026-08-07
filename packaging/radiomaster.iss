; RadioMaster+ Inno Setup Installer Script
; Requires Inno Setup 7

#define MyAppName "RadioMaster+"
#define MyAppVersion "1.0.0"
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
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
; Screen titles and descriptions
InstallModeTitle=Installation Mode
InstallModeDescription=Choose who should have access to {#MyAppName}
InstallTypeTitle=Installation Type
InstallTypeDescription=Choose how {#MyAppName} should be installed

[Types]
Name: "full"; Description: "Full installation"
Name: "portable"; Description: "Portable mode (no registry changes)"

[Components]
Name: "main"; Description: "Main application"; Types: full portable; Flags: fixed
Name: "assoc"; Description: "Register file associations"; Types: full; Flags: disablenouninstallwarning

[Files]
; Main application
Source: "..\dist\RadioMaster+\RadioMaster+.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\RadioMaster+\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Resources
Source: "..\resources\themes\*"; DestDir: "{app}\resources\themes"; Flags: ignoreversion

; Portable tools (ffmpeg, yt-dlp)
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Components: main
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; Components: main
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Components: main

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Components: main

[Registry]
; File associations (only for full install)
Root: "HKA"; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.mp3"; ValueData: ""; Flags: uninsdeletevalue; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3"; ValueType: string; ValueName: ""; ValueData: "MP3 Audio"; Flags: uninsdeletekey; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.mp3\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.flac"; ValueData: ""; Flags: uninsdeletevalue; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.flac\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.flac\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\.m4b\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.m4b"; ValueData: ""; Flags: uninsdeletevalue; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.m4b\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.m4b\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\.pls\OpenWithProgids"; ValueType: string; ValueName: "RadioMaster+.pls"; ValueData: ""; Flags: uninsdeletevalue; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.pls\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Components: assoc
Root: "HKA"; Subkey: "Software\Classes\RadioMaster+.pls\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Components: assoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Portable mode cleanup
Filename: "{app}\uninsportable.exe"; Flags: runhidden; Check: IsPortableMode

[Code]
var
  InstallModePage: TInputOptionWizardPage;
  InstallTypePage: TInputOptionWizardPage;
  IsPortable: Boolean;

function IsPortableMode: Boolean;
begin
  Result := IsPortable;
end;

procedure InitializeWizard;
begin
  { Screen 1: Installation Mode (Per User / All Users) }
  InstallModePage := CreateInputOptionPage(
    wpWelcome,
    CustomMessage('InstallModeTitle'),
    CustomMessage('InstallModeDescription'),
    'Select who should have access to RadioMaster+:',
    True, False
  );
  InstallModePage.Add('Install for &all users (recommended)');
  InstallModePage.Add('Install for &current user only');
  InstallModePage.SelectedValueIndex := 0;

  { Screen 2: Installation Type (Installed / Portable) }
  InstallTypePage := CreateInputOptionPage(
    InstallModePage.ID,
    CustomMessage('InstallTypeTitle'),
    CustomMessage('InstallTypeDescription'),
    'Select how RadioMaster+ should be installed:',
    True, False
  );
  InstallTypePage.Add('&Standard installation (Start Menu, file associations, uninstaller)');
  InstallTypePage.Add('&Portable mode (no registry changes, no Start Menu)');
  InstallTypePage.SelectedValueIndex := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectDir then
  begin
    { Screen 3: Adjust default directory based on choices }
    IsPortable := (InstallTypePage.SelectedValueIndex = 1);
    if IsPortable then
    begin
      WizardForm.DirEdit.Text := ExpandConstant('{sd}\RadioMaster+_Portable');
    end
    else if InstallModePage.SelectedValueIndex = 1 then
    begin
      WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\RadioMaster+');
    end
    else
    begin
      WizardForm.DirEdit.Text := ExpandConstant('{autopf}\RadioMaster+');
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Skip Start Menu page for portable mode }
  if (PageID = wpSelectProgramGroup) and IsPortable then
    Result := True
  else
    Result := False;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  S: String;
begin
  S := '';
  S := S + 'Installation mode: ';
  if InstallModePage.SelectedValueIndex = 0 then
    S := S + 'All users' + NewLine
  else
    S := S + 'Current user only' + NewLine;

  S := S + 'Installation type: ';
  if IsPortable then
    S := S + 'Portable' + NewLine
  else
    S := S + 'Standard' + NewLine;

  S := S + MemoDirInfo + NewLine;
  S := S + MemoTypeInfo + NewLine;
  S := S + MemoComponentsInfo + NewLine;

  if not IsPortable then
    S := S + MemoGroupInfo + NewLine;

  S := S + MemoTasksInfo;
  Result := S;
end;
