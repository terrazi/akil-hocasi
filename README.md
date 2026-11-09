# Akıl Hocası — v0.1 (Faz 1 çekirdeği)

TOGÜ idari personeli için kaynak gösteren, yerel bilgisayarda çalışan danışman.
Bilgi üretmez: resmî kaynaktan alır, doğrular, kaynağıyla sunar. Kamu sistemlerine
(KBS, MYS, HYS, EBYS, HİTAP, e-Devlet) **bağlanmaz**.

## Bu sürümde neler var

| Bölüm | Durum |
| --- | --- |
| Danışma ekranı (ana eksen): sohbet, cevap kartı, [1] [2] atıflar, kaynak paneli | Çalışır |
| Yedi basamaklı derin araştırma + 7 testli doğrulama motoru | Çalışır, test edildi |
| Çıplak "bilmiyorum" yerine: kesin olanlar + en yakın hüküm + somut yol + takip | Çalışır, test edildi |
| Yerel kütüphane: madde madde, sürümlü, Türkçe duyarlı arama, atıf zinciri | Çalışır, test edildi |
| Sürekli tarayıcı: saat başı / gece / sabah / boşta / haftalık takvim | Çalışır, test edildi (sahte sunucuyla) |
| Belge Deposu: orijinal Word/Excel/PDF, sürümler, makrosuz kopya, Korumalı Görünüm | Çalışır, test edildi |
| Hızlı Yakala: bölge seçme, Print Screen + Ctrl+V, canlı metin, akıllı algılama | Kod tamam; derleme sunucusunda öz testle denenir |
| Türkçe OCR: iyileştirme, çoklu okuma oylaması, Türkçe karakter önerileri | Çalışır (Tesseract `tur` ile test edildi) |
| Tarayıcı gözlemcisi (Chrome/Edge eklentisi): pasif gözlem + arka planda site taraması → değerlendirme → kütüphane | Çalışır, test edildi (Python 28 + Node 17 test) |
| Yerel dil modeli (llama.cpp) | İsteğe bağlı; yoksa alıntıya dayalı mod |
| Yazı Hazırlama, Hesaplama, Ön Kontrol | Yer tutucu sayfa (Faz 3, 4, 5) |

## Kurulum (tek dosya, yönetici yetkisi gerekmez)

`AkilHocasi-Kurulum-0.1.0.exe` dosyasına çift tıklayın. İçinde her şey vardır: Python yorumlayıcısı,
Qt arayüzü, OCR motorları (RapidOCR ve Türkçe dil dosyasıyla taşınabilir Tesseract) ve tüm kütüphaneler.
Bilgisayara ayrıca Python veya başka bir şey kurmak gerekmez.

- Kurulum yeri: `%LOCALAPPDATA%\Programs\AkilHocasi` (yönetici gerekmez; sihirbazda "tüm kullanıcılar"
  seçilirse yönetici izniyle Program Files'a kurulur).
- Seçenekler: masaüstü kısayolu, Windows açılışında sistem tepsisinde başlatma (saat başı güncelleme için önerilir).
- Yeni sürüm, eskisinin üzerine kurulur; kütüphane ve ayarlar korunur.
- İlk açılışta **Şimdi güncelle** düğmesine basın: program TOGÜ kalite belgelerini, Resmî Gazete'yi ve
  çekirdek kanunları indirmeye başlar.

Kurulum dosyası henüz kod imzalı değildir; Windows "Bilgisayarınız korundu" uyarısı gösterirse
**Ek bilgi → Yine de çalıştır** ile devam edilir. Kurum geneline dağıtımda BİDB ile kod imzalama
sertifikası veya izin listesi konuşulmalıdır.

## Kaldırma

**Ayarlar → Uygulamalar → Yüklü uygulamalar → Akıl Hocası → Kaldır** ya da Başlat menüsündeki
**Akıl Hocası'nı kaldır** kısayolu. Program açıksa kapatılır; masaüstü kısayolu, Başlat menüsü kaydı ve
Windows açılış kaydı silinir. Son adımda "Kişisel verileriniz de silinsin mi?" diye sorulur:
**Evet** derseniz kütüphane, belge deposu, ayarlar ve soru geçmişi de silinir; **Hayır** (varsayılan)
derseniz korunur ve yeniden kurduğunuzda kaldığınız yerden devam edersiniz.
Tarayıcıya eklediğiniz Akıl Hocası Gözlemci eklentisini `chrome://extensions` sayfasından ayrıca kaldırın.

## Kurulum dosyasını oluşturma (geliştirici)

Kurulum dosyası Windows'ta üretilir. İki yol vardır, ikisi de aynı betiği (`paketleme/paket_olustur.ps1`)
çalıştırır: testler → taşınabilir Tesseract + Türkçe → PyInstaller (Python gömülü uygulama) →
**paket öz testi** (paketlenmiş program gerçek Qt ile ekransız açılır, örnek soru cevaplanır, Türkçe
OCR denenir) → Inno Setup.

1. **GitHub (önerilen):** Bu klasör bir GitHub deposuna gönderildiğinde `.github/workflows/kurulum-paketi.yml`
   Windows sunucusunda kurulum dosyasını otomatik üretir; Actions sekmesindeki çalışmanın
   "AkilHocasi-Kurulum" çıktısından indirilir. `v0.1.0` gibi bir etiket gönderilirse Releases sayfasında
   yayımlanır.
2. **Kendi bilgisayarınızda:** Python 3.12 ve [Inno Setup 6](https://jrsoftware.org/isdl.php) kurulu,
   internet açıkken `paket_olustur.bat` dosyasını çalıştırın. Çıktı: `derleme\cikti\`.
   Tesseract'ın pakete girmesi için `C:\Program Files\Tesseract-OCR` kurulu olmalıdır (yoksa paket
   Windows OCR ve RapidOCR ile oluşturulur).

Python ortamıyla doğrudan geliştirme için `gelistirici\kur.bat` kullanılabilir.

## OCR motorları

Program şu sırayla dener (Ayarlar'dan değiştirilebilir):

1. **Windows OCR** — en hızlısı. Ayarlar > Saat ve dil > Dil bölümünde **Türkçe** dil paketinde
   "Optik karakter tanıma" bileşeni yüklü olmalıdır (kurum bilgisayarında yönetici gerekebilir).
2. **Tesseract** — kurulum paketiyle Türkçe dil dosyasıyla birlikte gelir; ayrıca kurmak gerekmez.
3. **RapidOCR** — kurulum paketiyle gelir. Türkçe karakterler için PaddleOCR "latin" tanıma modeli
   önerilir (Faz 0'da doğruluk ölçülecek).

## Yerel dil modeli (isteğe bağlı)

Model olmadan program **alıntıya dayalı modda** çalışır: cevap cümleleri doğrudan madde metninden alınır.
Kurulum paketi model çalıştırıcısını (llama.cpp) içerir; model dosyası boyutu nedeniyle (birkaç GB) ayrıdır.
4–8 milyar parametreli, 4 bit (Q4_K_M) bir GGUF modelini `%LOCALAPPDATA%\AkilHocasi\modeller`
klasörüne koyup Ayarlar > Yapay zekâ modeli bölümünden seçin. Hangi modelin Türkçe mevzuatta en iyi
sonucu verdiği Faz 0'da altın soru setiyle ölçülecek. Model hangi cevabı yazarsa yazsın,
kaynakta olmayan sayı, alıntı veya hüküm doğrulama motorunda elenir.

## Sürekli öğrenme ve kendini geliştirme

Program kullanıldıkça ve her gece kendini sınayarak gelişir. Öğrendiği şey kanunun ne dediği değil;
nasıl daha iyi arayacağı, anlayacağı ve sunacağıdır. Her cevap yine madde metnine bağlıdır ve doğrulamadan geçer.

| Ne öğrenir | Nereden | Güvence |
| --- | --- | --- |
| Terim karşılıkları ("tatil hakkı" → "aylıksız izin") | Başarısız sorudan sonra başarılı yeniden sorma (2 gözlemde etkin) | Yalnızca aramayı genişletir |
| İşe yarayan kaynaklar | "Faydalı" / "Yanlış" işaretleri, tıklanan kaynaklar | Yalnızca sıralamayı değiştirir |
| OCR düzeltmeleri | Kullanıcının uyguladığı düzeltmeler | Öneri olarak sunulur |
| Soru-cevap bankası ve örnek hafıza | "Faydalı" işaretlenen doğrulanmış cevaplar | Her gece güncel mevzuatla yeniden doğrulanır |
| Öğrenen sıralayıcı | Kütüphanedeki gerçek madde başlıkları ve metinleri, geri bildirimler, altın set | Her gece eğitilir; testte daha iyiyse devreye girer |
| Dil modeli ek katmanı (LoRA) | Doğrulanmış etkileşimler (`egitim.jsonl`) | Boştayken ve donanım yeterliyse; altın sette daha iyiyse devreye girer |

- **Gece öz değerlendirmesi** (Neler Değişti › Öğrenme › *Şimdi öğren* ile elle de): soru-cevap bankasını yeniden
  doğrular, altın soru setinde başarıyı ölçer (düşerse uyarır), sıralayıcıyı eğitir, bilgi boşluklarını listeler.
- **Altın soru seti:** birim uzmanlarının onayladığı sorular `egitim/altin_set_sablonu.json` biçiminde hazırlanıp
  *Altın soru setini yükle* ile eklenir. Program her gece bu setle kendini sınar.
- **Paylaşım:** Ayarlar › Öğrenme › *Paylaşım klasörü* (ör. ortak ağ klasörü) tanımlanırsa her bilgisayar öğrendiğini
  kişisel veri içermeyen bir paket olarak yazar ve diğerlerininkini alır. Gelen soru-cevaplar yerel kütüphaneyle
  doğrulanmadan kullanılmaz.
- **Dil modelinin gelişimi:** İlk eğitim ve kapasite artırımı için isteğe bağlı olarak `egitim/kaggle_ilk_egitim.ipynb`
  kullanılabilir. Sonrasında Ayarlar › *Yerel eğitim* komutu tanımlıysa ve bellek yeterliyse program boştayken kendi
  ek katmanını eğitir. Her yeni model ya da katman *Aday modeli dene* kapısından geçer: altın sette eskisinden daha
  başarılı ve kritik hatası fazla değilse devreye girer, değilse eski model kalır.

## Tarayıcı gözlemcisi (Akıl Hocası Gözlemci eklentisi)

Program, takvimli tarayıcısına ek olarak tarayıcıda gördüğünüz resmî sayfalardan da beslenir.
Eklenti `gozlemci_eklenti/` klasöründedir; kurulumda pakete girer ve ilk açılışta
`%LOCALAPPDATA%\AkilHocasi\gozlemci_eklenti` klasörüne kopyalanır.

**Kurulum (bir kez):** Başlat menüsünde **Akıl Hocası Gözlemci (tarayıcı eklentisi) kur** → açılan
klasörü Chrome'da `chrome://extensions` (Edge'de `edge://extensions`) → *Geliştirici modu* →
*Paketlenmemiş öğe yükle* ile seçin → eklentinin Ayarlar sayfasına Akıl Hocası › Ayarlar ›
*Tarayıcı gözlemcisi* bölümündeki **eşleştirme anahtarını** yapıştırın.

**Nasıl çalışır?**

- **Pasif gözlem:** Beyaz listedeki herkese açık resmî bir sayfayı açtığınızda ana metin, başlık ve dosya
  bağlantıları okunur, maskelenir ve yalnızca bu bilgisayardaki programa (127.0.0.1) gönderilir.
- **Site taraması:** Eklenti simgesi › *Bu siteyi tara*. Arka plan sekmesinde yalnız aynı alandaki bağlantılar
  izlenir; hız profili (yavaş/normal/hızlı), sayfa ve derinlik sınırı, robots.txt, yapı benzerliği süzgeci
  (aynı şablondaki sayfaların bağlantıları beş kez görüldükten sonra yeniden açılmaz), duraklat/devam/sıfırla.
  Uygulama kapanırsa tarama kendiliğinden duraklar.
- **Değerlendirme (programda):** kamu sistemi/oturum denetimi → beyaz liste → maskeleme → sınıflandırma
  (mevzuat / form listesi / SSS / sayfa) → aynı içerik başka adreste var mı → kütüphaneye **sürümlü** kayıt
  (değişen sayfa eski sürümü saklar, ona dayanan kart ve soru-cevapları yeniden doğrulamaya düşürür) →
  resmî PDF/Word/Excel bağlantıları **doğrudan resmî siteden** indirilip Belge Deposu'na işlenir.
  memurlar.net gibi ikincil sitelerden içerik kopyalanmaz; yalnız başlık ve soru cümleleri ipucu olarak tutulur.

**Kesin sınırlar (eklentide ve programda ayrı ayrı uygulanır):** KBS, MYS, HYS, EBYS (enVision), HİTAP,
e-Devlet, OBS, EKAP ve giriş/oturum sayfaları gözlenmez; parola alanı ya da çıkış bağlantısı görülen sayfa
okunmaz; hiçbir düğmeye tıklanmaz, form gönderilmez. Eklenti yalnız `storage` ve `alarms` izinlerini ister;
`<all_urls>`, `debugger`, `downloads`, `cookies` istemez. Sunucu yalnız 127.0.0.1'i dinler; eşleştirme anahtarı,
eklenti kaynağı ve Host denetimi yapar.

## Kullanım

- **Danışma:** Sorunuzu yazın; "Derin araştırma" yedi basamağın hepsini çalıştırır. Cevaptaki
  [1], [2] atıflarına tıklayınca dayandığı madde sağ panelde vurgulu açılır.
- **Hızlı Yakala:** `Win+Shift+Y` (Ayarlar'dan değiştirilebilir) → alanı seçin → metne tıklayın,
  sürükleyin, çift tık kelime, üçlü tık satır, `Ctrl+A` / `Ctrl+C`. TC ve IBAN varsayılan olarak
  maskeli kopyalanır. Print Screen'den sonra tepside "metni al?" bildirimi çıkar.
- **Belge Deposu:** İndirilen formların orijinalleri; açtığınız her dosya bir kopyadır.
- **Neler Değişti:** Son 7 günün değişiklikleri ve takipteki sorular.

## Veri ve gizlilik

Tüm veri `%LOCALAPPDATA%\AkilHocasi` altındadır: `kutuphane.db`, `depo\`, `modeller\`,
`gunluk\`, `ayarlar.json`. Program yalnızca beyaz listedeki resmî alanlara okuma isteği gönderir
(`akil_hocasi/crawler/beyaz_liste.py`), telemetri göndermez.

## Faz 0'da gerçek TOGÜ bilgisayarında denenecekler

- [ ] Kaynak adres düzenleri (`akil_hocasi/crawler/kaynaklar.py`): Resmî Gazete günlük fihristi,
      mevzuat.gov.tr kanun metni adresleri, TOGÜ kalite listesi ayrıştırması
- [ ] Windows OCR Türkçe paketi ve yönetici gereksinimi; RapidOCR Türkçe doğruluğu
- [ ] `Win+Shift+Y` kısayolunun başka programla çakışıp çakışmadığı
- [ ] Model hızı (16 GB ve 8 GB RAM'de), disk kullanımı
- [ ] Altın soru seti (birimlerden gelecek 15–20 gerçek soru)
- [ ] Gözlemci eklentisi: kurum Chrome/Edge politikasının paketlenmemiş eklentiye izin verip vermediği
      (izin yoksa BT birimiyle zorunlu kurulum politikası); TOGÜ sitelerinde ana metin seçiminin doğruluğu

## Geliştirici notları

```
akil_hocasi/
  core/      Türkçe metin, TC/IBAN/ekonomik kod doğrulayıcıları, maskeleme, akıllı algılama
  library/   SQLite FTS5 kütüphane, madde ayrıştırıcı, eş anlamlı sözlüğü
  answer/    cevap hattı (7 basamak), doğrulama motoru (7 test), llama.cpp adaptörü
  crawler/   beyaz liste, indirici, kaynak adaptörleri, tarayıcı, zamanlayıcı, belge deposu
  ocr/       iyileştirme, motorlar, oylama, Türkçe düzeltme
  ogrenme/   öğrenme motoru, öğrenen sıralayıcı, gece öz değerlendirmesi, paylaşım paketleri, eğitim kapısı
  gozlem/    tarayıcı gözlemi: değerlendirici (kabul/ipucu/ret), yerel sunucu (127.0.0.1), eklenti kurulumu
  ui/        PySide6 arayüz (tema, danışma, cevap kartı, Hızlı Yakala, sayfalar, ana pencere)
gozlemci_eklenti/ Akıl Hocası Gözlemci (Chrome/Edge MV3): kurallar, içerik betiği, arka plan çalışanı, açılır pencere
tests/       pytest (çekirdek, kütüphane, cevap, tarayıcı, OCR, öğrenme, gözlem); tests/js: Node eklenti testleri
paketleme/  PyInstaller tarifi, Inno Setup kurulum/kaldırma betiği, simge, derleme betiği
.github/    otomatik kurulum dosyası üretimi (GitHub Actions, Windows)
gelistirici/ Python ortamıyla geliştirme betikleri
egitim/     isteğe bağlı Kaggle ilk eğitim not defteri, altın soru seti şablonu
```

Testler: `gelistirici\testleri_calistir.bat` veya `python -m pytest -q tests` ve
`node --test tests/js/kurallar.test.js tests/js/arka_plan.test.js`.
Doğrudan çalıştırma: `python -m akil_hocasi` (`--tepside` pencere açmadan başlar,
`--oz-test=rapor.txt` ekransız öz test yapar, `--surum` sürümü yazar, `--gozlemci-kur` eklenti klasörünü
açıp kurulumu anlatır).
