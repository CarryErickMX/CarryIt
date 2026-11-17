; Instalador de CarryIt (Inno Setup 6). No se compila a mano: lo llama build.py
; con /DAppVersion=..., /DSourceDir=... (carpeta de la app ya compilada) y /DOutputDir=...

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\CarryIt"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\carryit\resources\icon.ico"
#endif

#define AppName "CarryIt"
#define AppExe "CarryIt.exe"

[Setup]
AppId={{8D864ECC-ADE7-40C9-A712-81C1413B65A6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=CARRY
VersionInfoVersion={#AppVersion}
; Instalación por usuario (sin pedir permisos de administrador); se puede elegir "para todos".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=CarryIt-Setup-{#AppVersion}
SetupIconFile={#IconFile}
; Imágenes del asistente (generadas por tools/branding.py), en tamaño normal y para pantallas 2x.
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Si la app está abierta, pedir que se cierre antes de instalar/actualizar.
AppMutex=CarryIt.Mutex
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"; InfoBeforeFile: "aviso_es.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "aviso_en.txt"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; La carpeta completa generada por PyInstaller + deno.exe + ffmpeg\ + licencias.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Al actualizar, borrar los archivos internos de la versión anterior para que no queden mezclados.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; AppUserModelID igual al de la app: así la barra de tareas toma el ícono del acceso directo
; (Windows elige del .ico el tamaño exacto y se ve nítido).
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Carry.CarryIt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; AppUserModelID: "Carry.CarryIt"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; La copia actualizada de yt-dlp que descarga la app (las preferencias del usuario se conservan).
Type: filesandordirs; Name: "{userappdata}\CarryIt\lib"
Type: filesandordirs; Name: "{userappdata}\CarryIt\lib.new"
Type: filesandordirs; Name: "{userappdata}\CarryIt\lib.old"
