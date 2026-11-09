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
| Kaynak Havuzu: gömülü görünmez tarayıcı + kendiliğinden eşleşen Chrome/Edge eklentisi → değerlendirme → kütüphane | Çalışır, test edildi (gerçek Chrome/Edge ile uçtan uca; Node 21 test) |
| Çekirdek: 12 değişmez ilke, 25 yordamlık Yordam Kitabı, iş akışları, ilke karnesi, gelişim kapısı | Çalışır, test edildi |
| Danışman muhakemesi: durum çözümlemesi, netleştirme, gerekçe (olgu → kural → sonuç), değerlendirme, öz eleştiri | Çalışır, test edildi |
| Yerel dil modeli: llama.cpp `llama-server` pakette; bilgisayara göre Qwen3.5 önerisi, tek tıkla doğrulamalı indirme | Çalışır; derleme sunucusunda gerçek modelle öz test |
| Anlam araması (Qwen3 Embedding) + kelime araması birleşik | Çalışır, test edildi |
| Kendini geliştirme: çalışma soruları, hatalardan yöntem dersleri, yordam ayarı denemeleri, model yarışı | Çalışır, test edildi |
| Resmî Yazı Hazırlama: gelen yazı çözümleme, 2020 Yönetmeliğine göre taslak, sınama, kontrol listesi, Word + EBYS metni | Çalışır, test edildi |
| Çekirdek bilgi paketi: temel mevzuat kurulumla gelir (internet yokken ilk gün de kaynaklı cevap) | Derleme hattında resmî kaynaktan |
| Kaggle'da yoğun eğitim: öğretmen modelle damıtma, 4B ince ayar, ilke karnesiyle sınav, programa ekleme | Defterler ve hat hazır; ilk GPU çalıştırması bekleniyor |
| Hesaplama, Ön Kontrol | Yer tutucu sayfa (Faz 4, 5) |

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
Windows açılış kaydı ve tarayıcı eklentisinin köprü kaydı silinir. Son adımda "Kişisel verileriniz de silinsin mi?" diye sorulur:
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

## Yerel dil modeli ve çekirdek (Zekâ ekranı)

Kurulum paketi model sunucusunu (llama.cpp `llama-server`, CPU) içerir. Model dosyaları büyük olduğu için ilk
açılışta bilgisayarın belleğine uygun olanı önerilir ve tek tıkla indirilir (dosya bütünlüğü sha256 ile doğrulanır,
kesilen indirme kaldığı yerden sürer). İnternet yoksa **Zekâ › Ortak model klasörü** ile ağdaki bir klasörden
alınır. Model yokken program **alıntıya dayalı modda** çalışır.

| Bellek | Önerilen dil modeli | Not |
| --- | --- | --- |
| 16 GB ve üstü | Qwen3.5 9B (Q4_K_M) | En iyi muhakeme; en yavaş |
| 8–16 GB | Qwen3.5 4B | Dengeli |
| 6–8 GB | Qwen3.5 2B | Hızlı |
| Anlam araması | Qwen3 Embedding 0.6B | Her bilgisayarda |

**Çekirdek** programın temel çalışma ilkeleridir (Zekâ › *Çekirdek El Kitabı*): doğruluk, güncellik, normlar
hiyerarşisi, durumu anlama, gerekçeli muhakeme, dürüst güven düzeyi, çözüm odaklılık, somutluk, yetki sınırı,
gizlilik, resmî dil ve kontrollü öğrenme. Her yordam (anlama, netleştirme, planlama, tarama, bulma, seçme, analiz,
yordama, çatışma çözme, sentez, sınama, eleştirme, düzeltme, yeniden işleme, sunum, takip, test, ders çıkarma,
strateji ayarı, benimseme, model gelişimi…) bu ilkelere bağlıdır. Öğrenme ilkeleri değiştiremez: yalnızca yordam
ayarlarını izinli aralıkta, **ilke karnesinde** hiçbir ilkenin notunu düşürmeden ve gerçek iyileşme göstererek
değiştirebilir (gelişim kapısı). Bilgisayar boştayken program kendi çalışma sorularını üretir, hatalarından yöntem
dersleri çıkarır, ayar denemeleri yapar ve daha iyi bir model adayı varsa aynı sınavda yarıştırır.

## Kaggle'da yoğun eğitim

Ofis bilgisayarında çalışan küçük model, Kaggle'ın ücretsiz GPU'larında büyük bir öğretmen modelle (Qwen3.5-35B-A3B)
**programın kendi çekirdek yordamları üzerinden** eğitilir: öğretmen, programın sorduğu her şeye (durum çözümleme,
gerekçeli cevap, öz eleştiri, düzeltme, hatadan ders, çalışma sorusu, resmî yazı) programın istemleriyle cevap verir.
Yalnız programın sınamasından geçen cevaplar eğitim verisi olur. Eğitilen model (Qwen3.5-4B, 8 GB bilgisayarlar için)
eğitimde görmediği sorularda ilke karnesi ve gelişim kapısıyla sınanır. Program onu **Zekâ › Eğitilmiş modeli ekle**
ile alır ve gece kendi sınav setiyle yeniden sınar. **Zekâ › Kaggle eğitim paketi hazırla** düğmesi, kütüphaneyi ve
altın soru setini bir sonraki eğitime taşır; her tur bir öncekinin üzerine kurulur. Ayrıntılar ve adımlar:
[kaggle/BENIOKU.md](kaggle/BENIOKU.md).

## Resmî Yazı Hazırlama

Gelen yazıyı yapıştırın, Word/PDF olarak açın ya da ekran görüntüsünden okutun; program gönderen idareyi, sayıyı,
tarihi, konuyu, istenen hususları ve cevap süresini çözümler. *Ne yazılsın?* alanına birimin cevabını yazın.
Taslak, Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmeliğe (RG 10.06.2020/31151) göre hazırlanır:
başlık, konu ve muhatap biçimi (yönelme hâli), ilgi sıralaması, 1,25 cm girinti, makama göre bitiş ifadesi
(arz/rica ederim), imza, ek, dağıtım ve iletişim alanı.

- **Sınama:** Metindeki her tarih, sayı, belge sayısı ve mevzuat atfı gelen yazıda, talimatta ya da doğrulanmış
  mevzuatta bulunmalıdır; bulunmayan cümle çıkarılır ve *Nasıl düşündüm* sekmesinde gösterilir.
- **Kontrol listesi:** Yönetmelik maddeleriyle (md. 10–26) ve çekirdek ilkeleriyle; bir maddeye çift tıklayınca
  Yönetmeliğin o maddesi kütüphaneden açılır. Gelen yazıda istenen her hususun karşılanıp karşılanmadığı da denetlenir.
- **Çıktılar:** Word taslağı (TASLAK ibareli), EBYS'ye alan alan yapıştırılacak metin. **Sayı, tarih, e-imza ve
  doğrulama kodu üretilmez**; bunları EBYS verir. Başlık, imza ve iletişim bilgileri *Birim profili*nden gelir.
- Danışma cevabındaki *Yazıya dönüştür* düğmesi, doğrulanmış cevabı yazının dayanağı yapar.

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

## Kaynak Havuzu: gömülü tarayıcı + tarayıcı eklentisi (entegre)

Program resmî sitelerden kendi kendine beslenir; hepsi soldaki **Kaynaklar** ekranından yönetilir.

- **Gömülü tarayıcı (eklenti gerekmez):** Program bilgisayardaki Edge'i (yoksa Chrome'u) görünmez çalıştırır.
  Her tarama çerezsiz, oturumsuz, geçici bir profille yapılır; profil iş bitince silinir. Bu yüzden hiçbir kamu
  sistemine oturum açık hâlde girilemez. Betikle yüklenen (JavaScript) sayfalar da okunur. Listedeki siteler haftada bir,
  bilgisayar boştayken kendiliğinden taranır; "Tümünü şimdi tara" ile elle de başlatılır. Durdurulan tarama kaldığı
  yerden sürer. Ek Python paketi gerekmez (Chrome DevTools Protokolü standart kütüphaneyle konuşulur).
- **Tarayıcı eklentisi (isteğe bağlı):** Gezdiğiniz resmî sayfaları da havuza ekler. Kurulum, eklentinin
  programla **kendiliğinden eşleşmesi** için Chrome/Edge'e yerel bir köprü (`AkilHocasiKopru.exe`, yalnız bu kullanıcı,
  yönetici yetkisi gerekmez) kaydeder; anahtar kopyalanmaz. Eklentideki **Bu siteyi tara** işi programın görünmez
  tarayıcısına devredilir; tarayıcınızı kapatsanız da sürer. Program kapalıysa eklenti onu tepside açtırır.
- **Tek değerlendirme hattı:** Her iki yoldan gelen sayfa aynı denetimden geçer: kamu sistemi/oturum →
  beyaz liste → maskeleme → sınıflandırma (mevzuat / form listesi / SSS / sayfa) → tekrar mı → kütüphaneye
  **sürümlü** kayıt (değişen sayfa, ona dayanan kart ve soru-cevapları yeniden doğrulamaya düşürür) → resmî
  PDF/Word/Excel bağlantıları **doğrudan resmî siteden** indirilip Belge Deposu'na işlenir. HTTP hata sayfaları
  (404/500) kaydedilmez; yönlendirmeyle giriş sayfasına ya da başka alana düşen sayfa okunmaz. memurlar.net gibi
  ikincil sitelerden içerik kopyalanmaz; yalnız başlık ve soru cümleleri ipucu olarak tutulur.

**Eklentiyi ekleme (bir kez):** Başlat menüsü › **Akıl Hocası Gözlemci (tarayıcı eklentisi) kur** → açılan klasörü
`chrome://extensions` (Edge: `edge://extensions`) › *Geliştirici modu* › *Paketlenmemiş öğe yükle* ile seçin. Eşleşme
kendiliğinden olur. (Chrome, Web Mağazası dışındaki eklentileri Windows'ta sessizce kuramaz; bu tek adım
tarayıcının güvenlik kuralıdır. Eklenti mağazada yayımlanırsa kurulum tek tıklamayla etkinleştirmeye iner.)

**Kesin sınırlar (eklentide, görünmez tarayıcıda ve programda ayrı ayrı uygulanır):** KBS, MYS, HYS, EBYS (enVision),
HİTAP, e-Devlet, OBS, EKAP ve giriş/oturum sayfaları gözlenmez; parola alanı ya da çıkış bağlantısı görülen sayfa
okunmaz; hiçbir düğmeye tıklanmaz, form gönderilmez; indirme ve tarayıcı uyarı pencereleri kapalıdır. Eklenti yalnız
`storage`, `alarms` ve `nativeMessaging` izinlerini ister; `<all_urls>`, `debugger`, `downloads`, `cookies` istemez.
Yerel sunucu yalnız 127.0.0.1'i dinler; eşleştirme anahtarı, eklenti kaynağı ve Host denetimi yapar; köprü yalnız
Akıl Hocası Gözlemci'nin sabit kimliğine cevap verir.

## Kullanım

- **Danışma:** Sorunuzu yazın; "Derin araştırma" yedi basamağın hepsini çalıştırır. Cevaptaki
  [1], [2] atıflarına tıklayınca dayandığı madde sağ panelde vurgulu açılır.
- **Hızlı Yakala:** `Win+Shift+Y` (Ayarlar'dan değiştirilebilir) → alanı seçin → metne tıklayın,
  sürükleyin, çift tık kelime, üçlü tık satır, `Ctrl+A` / `Ctrl+C`. TC ve IBAN varsayılan olarak
  maskeli kopyalanır. Print Screen'den sonra tepside "metni al?" bildirimi çıkar.
- **Belge Deposu:** İndirilen formların orijinalleri; açtığınız her dosya bir kopyadır.
- **Kaynaklar:** Taranan siteler, canlı tarama ilerlemesi, gözlem günlüğü (eklendi / güncel / atlandı ve nedeni),
  ikincil site ipuçları ve eklentinin eşleşme durumu. Site eklemek için adresi yazıp *Ekle*.
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
- [ ] Kaynak Havuzu: varsayılan TOGÜ site listesinin doğrulanması, kurum Edge/Chrome politikasının görünmez
      tarayıcıya ve paketlenmemiş eklentiye izin verip vermediği, TOGÜ sayfalarında ana metin seçiminin doğruluğu

## Geliştirici notları

```
akil_hocasi/
  core/      Türkçe metin, TC/IBAN/ekonomik kod doğrulayıcıları, maskeleme, akıllı algılama
  library/   SQLite FTS5 kütüphane, madde ayrıştırıcı, eş anlamlı sözlüğü
  answer/    cevap hattı (7 basamak), doğrulama motoru (7 test), llama.cpp adaptörü
  crawler/   beyaz liste, indirici, kaynak adaptörleri, tarayıcı, zamanlayıcı, belge deposu
  ocr/       iyileştirme, motorlar, oylama, Türkçe düzeltme
  ogrenme/   öğrenme motoru, öğrenen sıralayıcı, gece öz değerlendirmesi, paylaşım paketleri, eğitim kapısı
  gozlem/    kaynak havuzu: değerlendirici, gömülü tarayıcı (CDP) ve tarama motoru, yerel sunucu, eklenti köprüsü
  ui/        PySide6 arayüz (tema, danışma, cevap kartı, Hızlı Yakala, sayfalar, ana pencere)
gozlemci_eklenti/ Akıl Hocası Gözlemci (Chrome/Edge MV3): kurallar, içerik betiği, arka plan çalışanı, açılır pencere
tests/       pytest (çekirdek, kütüphane, cevap, tarayıcı, OCR, öğrenme, gözlem); tests/js: Node eklenti testleri
paketleme/  PyInstaller tarifi, Inno Setup kurulum/kaldırma betiği, simge, derleme betiği
.github/    otomatik kurulum dosyası üretimi (GitHub Actions, Windows)
gelistirici/ Python ortamıyla geliştirme betikleri
egitim/     isteğe bağlı Kaggle ilk eğitim not defteri, altın soru seti şablonu
```

Testler: `gelistirici\testleri_calistir.bat` veya `python -m pytest -q tests` ve
`node --test tests/js/kurallar.test.js tests/js/arka_plan.test.js`. Gömülü tarayıcı testleri bilgisayarda Chrome/Edge
varsa sahte bir TOGÜ sitesine karşı uçtan uca çalışır (internet gerekmez).
Doğrudan çalıştırma: `python -m akil_hocasi` (`--tepside` pencere açmadan başlar,
`--oz-test=rapor.txt` ekransız öz test yapar, `--surum` sürümü yazar, `--gozlemci-kur` eklenti klasörünü
açıp kurulumu anlatır).
