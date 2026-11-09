; Akıl Hocası — Inno Setup kurulum betiği (Inno Setup 6)
; Derleme:  iscc /DSurum=0.1.0 paketleme\akilhocasi.iss
; Girdi:    derleme\dist\AkilHocasi\  (PyInstaller çıktısı; Python ve tüm kütüphaneler içinde)
; Çıktı:    derleme\cikti\AkilHocasi-Kurulum-<sürüm>.exe

#ifndef Surum
  #define Surum "0.1.0"
#endif
#define UygAdi "Akıl Hocası"
#define UygExe "AkilHocasi.exe"

[Setup]
; AppId kurulumlar arasında sabit kalmalı: yeni sürüm eskisinin üzerine güncelleme olarak kurulur
AppId={{6F1C2E4A-8B3D-4C7E-9A21-5D0B7E3F9A64}
AppName={#UygAdi}
AppVersion={#Surum}
AppVerName={#UygAdi} {#Surum}
AppPublisher=Akıl Hocası
AppComments=TOGÜ idari personeli için kaynak gösteren, yerel çalışan mevzuat danışmanı
VersionInfoVersion={#Surum}
VersionInfoDescription={#UygAdi} kurulumu
; Yönetici yetkisi istemez; kullanıcının kendi klasörüne kurar (%LOCALAPPDATA%\Programs\AkilHocasi)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\AkilHocasi
DefaultGroupName={#UygAdi}
DisableProgramGroupPage=yes
UninstallDisplayName={#UygAdi}
UninstallDisplayIcon={app}\{#UygExe}
SetupIconFile=akilhocasi.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\derleme\cikti
OutputBaseFilename=AkilHocasi-Kurulum-{#Surum}
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
; Program açıksa kurulum ve kaldırma bunu fark eder (uygulama bu adla mutex oluşturur)
AppMutex=AkilHocasi.Calisiyor
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[CustomMessages]
turkish.Kisayollar=Kısayollar:
turkish.MasaustuSimgesi=Masaüstüne kısayol oluştur
turkish.Baslangic=Windows açılışında sistem tepsisinde başlat (saat başı güncelleme için önerilir)
turkish.Gozlemci=Akıl Hocası Gözlemci (tarayıcı eklentisi) kur
turkish.Baslat=Akıl Hocası'nı şimdi başlat
turkish.VeriSilinsinMi=Kişisel verileriniz de silinsin mi?%n%nKütüphane, belge deposu, ayarlar, soru geçmişi ve gözlemci eklenti klasörü (%1) silinir. Tarayıcıya eklediğiniz Akıl Hocası Gözlemci eklentisini chrome://extensions sayfasından ayrıca kaldırabilirsiniz.%n%n"Hayır" derseniz veriler korunur; yeniden kurduğunuzda kaldığınız yerden devam edersiniz.
turkish.ProgramAcik=Akıl Hocası şu anda açık. Kaldırmaya devam etmek için program kapatılacak.

[Tasks]
Name: "masaustu"; Description: "{cm:MasaustuSimgesi}"; GroupDescription: "{cm:Kisayollar}"
Name: "baslangic"; Description: "{cm:Baslangic}"; GroupDescription: "{cm:Kisayollar}"

[Files]
Source: "..\derleme\dist\AkilHocasi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#UygAdi}"; Filename: "{app}\{#UygExe}"
Name: "{group}\{cm:Gozlemci}"; Filename: "{app}\{#UygExe}"; Parameters: "--gozlemci-kur"; \
  Comment: "Chrome / Edge için Akıl Hocası Gözlemci eklentisinin klasörünü açar ve kurulumu anlatır"
Name: "{group}\{cm:UninstallProgram,{#UygAdi}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#UygAdi}"; Filename: "{app}\{#UygExe}"; Tasks: masaustu

[Registry]
; Windows açılışında tepside başlat; kaldırırken bu kayıt da silinir
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AkilHocasi"; \
  ValueData: """{app}\{#UygExe}"" --tepside"; Flags: uninsdeletevalue; Tasks: baslangic

[Run]
Filename: "{app}\{#UygExe}"; Description: "{cm:Baslat}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Programın kurulum klasöründe sonradan oluşturduğu dosyalar
Type: files; Name: "{app}\surum.txt"
Type: dirifempty; Name: "{app}"

[Code]
function VeriKlasoru(): String;
begin
  Result := ExpandConstant('{localappdata}\AkilHocasi');
end;

function InitializeUninstall(): Boolean;
var
  Sonuc: Integer;
begin
  Result := True;
  if CheckForMutexes('AkilHocasi.Calisiyor') then
  begin
    if MsgBox(CustomMessage('ProgramAcik'), mbConfirmation, MB_OKCANCEL) = IDOK then
      Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM AkilHocasi.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Sonuc)
    else
      Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(VeriKlasoru()) and not UninstallSilent() then
  begin
    if MsgBox(FmtMessage(CustomMessage('VeriSilinsinMi'), [VeriKlasoru()]),
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(VeriKlasoru(), True, True, True);
  end;
end;
