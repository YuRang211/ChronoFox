; ChronoFox (크로노폭스) Inno Setup installer script
; planning/specs/release-v1.md P4 decisions:
;   - per-user install under {localappdata}\Programs\ChronoFox (no admin required)
;   - start-menu shortcut; desktop icon is an opt-in task, unchecked by default
;   - installer/uninstaller NEVER registers or removes startup — that stays an
;     explicit in-app toggle only (P5)
;   - uninstall preserves %USERPROFILE%\.desktop_note_calendar and tells the
;     user so, in Korean and English
;
; Build prerequisite: run the pipeline (or PyInstaller with --distpath out/dist)
; so out\dist\ChronoFox exists (see build_release.ps1 for the full pipeline).
; Compile manually with: iscc installer\chronofox.iss   (run from repo root)

#define MyAppName "ChronoFox"
; Overridable from the command line via build_release.ps1: /DMyAppVersion=x.y.z
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "ChronoFox"
#define MyAppExeName "ChronoFox.exe"
#define MyDistDir "..\out\dist\ChronoFox"

[Setup]
; Fixed AppId (GUID) — keep stable across versions so upgrades are detected
; as the same product instead of installing side-by-side.
AppId={{B3E1B4B0-6C2E-4F0C-9C3A-0F9E7F3D2B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install, never prompts for admin elevation (P4).
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=ChronoFox-{#MyAppVersion}-Setup
SetupIconFile=chronofox.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; PyInstaller build here targets 64-bit Python; keep installer 64-bit-only.
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
korean.DataPreservedMessage=ChronoFox 제거를 완료했습니다.%n%n사용자 데이터(설정, 일정, 메모)는 삭제되지 않고 아래 위치에 그대로 남아 있습니다:%n%n%USERPROFILE%\.desktop_note_calendar%n%n이 폴더를 완전히 지우려면 위 경로를 직접 열어 수동으로 삭제해 주세요.
english.DataPreservedMessage=ChronoFox has been uninstalled.%n%nYour data (settings, schedules, memos) was NOT deleted and remains at:%n%n%USERPROFILE%\.desktop_note_calendar%n%nTo remove it completely, open that folder yourself and delete it manually.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Whole onedir build (exe + _internal support files, assets, locales).
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; No [Registry] "Run" key entries anywhere in this script — startup
; registration is intentionally left to the app's own explicit-consent
; settings toggle (P5). Do not add one here without a spec update.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Show the data-preserved notice once uninstall has finished removing the
    app files. We never touch %USERPROFILE%\.desktop_note_calendar, so there
    is nothing to clean up here — this is purely informational. }
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox(ExpandConstant('{cm:DataPreservedMessage}'), mbInformation, MB_OK);
  end;
end;
