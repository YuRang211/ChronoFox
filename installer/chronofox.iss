; ChronoFox (크로노폭스) Inno Setup installer script
; planning/PROJECT.md §9 install/uninstall decisions:
;   - per-user install under {localappdata}\Programs\ChronoFox (no admin required)
;   - start-menu shortcut; desktop icon is an opt-in task, unchecked by default
;   - installer NEVER enables startup. The explicit in-app toggle owns it;
;     uninstall only removes that app-created registration and legacy .bat files
;   - uninstall preserves %USERPROFILE%\.desktop_note_calendar and tells the
;     user so, in Korean and English
;
; Build prerequisite: run the pipeline (or PyInstaller with --distpath out/dist)
; so out\dist\ChronoFox exists (see build_release.ps1 for the full pipeline).
; Compile manually with: iscc installer\chronofox.iss   (run from repo root)

#define MyAppName "ChronoFox"
; Overridable from the command line via build_release.ps1: /DMyAppVersion=x.y.z
; AUDIT-D7: default mirrors app_constants.APP_VERSION (the app-displayed version).
; Inno Setup can't import the Python constant, so keep this in sync by hand when bumping.
#ifndef MyAppVersion
  #define MyAppVersion "0.8.3"
#endif
#define MyAppPublisher "ChronoFox"
#define MyAppURL "https://github.com/YuRang211/ChronoFox"
#define MyAppExeName "ChronoFox.exe"
#define MyDistDir "..\out\dist\ChronoFox"

[Setup]
; Fixed AppId (GUID) — keep stable across versions so upgrades are detected
; as the same product instead of installing side-by-side.
AppId={{B3E1B4B0-6C2E-4F0C-9C3A-0F9E7F3D2B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppComments=Desktop calendar, schedules, tasks, alarms, and memos in one local-first app.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install, never prompts for admin elevation (P4).
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=ChronoFox-{#MyAppVersion}-Setup
SetupIconFile=chronofox.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; PyInstaller build here targets 64-bit Python. x64compatible also accepts
; Windows 11 on ARM when its x64 emulation layer is available.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef EnableSigning
; build_release.ps1 defines ChronoFoxSign on the ISCC command line. This signs
; both Setup and the embedded uninstaller without storing certificates/secrets.
SignTool=ChronoFoxSign
SignedUninstaller=yes
SignToolRetryCount=3
SignToolMinimumTimeBetween=1000
#endif

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.DataPreservedMessage=ChronoFox 프로그램, 바로가기, 자동실행 등록을 제거했습니다.%n%n사용자 데이터(설정, 일정, 메모)는 삭제하지 않았으며 아래 위치에 그대로 남아 있습니다:%n%n%USERPROFILE%\.desktop_note_calendar%n%n데이터까지 완전히 지우려면 위 폴더를 직접 삭제해 주세요.
english.DataPreservedMessage=ChronoFox, its shortcuts, and its startup registration have been removed.%n%nYour data (settings, schedules, and memos) was preserved at:%n%n%USERPROFILE%\.desktop_note_calendar%n%nDelete that folder manually only if you also want to erase your data.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; PyInstaller owns this generated runtime directory. Remove it before copying
; the new build so obsolete DLLs from an older install cannot shadow Qt DLLs.
; User settings and calendar data live outside {app} and are never touched.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Whole onedir build (exe + _internal support files, assets, locales).
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Do not create or enable startup during install. If the user enabled it in the
; app, remove only ChronoFox's own value during uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ChronoFox"; Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; Clean up startup artifacts created by versions before HKCU Run migration.
; Exact filenames only: never use a wildcard and never touch the data folder.
Type: files; Name: "{userappdata}\Microsoft\Windows\Start Menu\Programs\Startup\ChronoFox.bat"
Type: files; Name: "{userappdata}\Microsoft\Windows\Start Menu\Programs\Startup\FoxCalendar.bat"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Show the data-preserved notice once uninstall has finished removing the
    app files. We never touch %USERPROFILE%\.desktop_note_calendar, so there
    is nothing to clean up here — this is purely informational. }
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    MsgBox(ExpandConstant('{cm:DataPreservedMessage}'), mbInformation, MB_OK);
  end;
end;
