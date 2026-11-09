# Akıl Hocası'nı Kaggle'da eğitmek

Bu klasör, Akıl Hocası'nın yerel dil modelini Kaggle'ın ücretsiz GPU'larında **yoğun eğitime** tabi tutan iki defteri
içerir. Eğitim, programın çekirdeğine göre yapılır: model, program çalışırken hangi yordamları yürütüyorsa (durum
çözümleme, gerekçeli cevap, öz eleştiri, düzeltme, hatadan ders çıkarma, kendi çalışma sorularını üretme, resmî yazı)
o yordamların istemleriyle ve yalnızca **programın sınamasından geçmiş** cevaplarla eğitilir.

## Nasıl çalışır?

1. **Öğretmen:** Kaggle'daki iki T4 kartına büyük bir açık model, **Qwen3.5-35B-A3B**, yüklenir.
2. **Damıtma (1. defter):** Akıl Hocası kütüphanesindeki gerçek mevzuattan (mevzuat.gov.tr, TOGÜ sayfaları ve
   isterseniz sizin kütüphaneniz) personel soruları üretir. Öğretmen bu soruları programın kendi akışıyla cevaplar.
   Doğrulanamayan cümle içeren, beklenen mevzuatı bulamayan ya da biçimi bozuk her cevap atılır; kalanlar eğitim
   verisi olur. Soruların üçte biri sınav için ayrılır ve eğitime hiç girmez.
3. **Eğitim (2. defter):** Öğrenci model, **Qwen3.5-4B** (8 GB bellekli bilgisayarlar için), bu veriyle 16 bit LoRA
   yöntemiyle eğitilir ve GGUF Q4_K_M biçimine dönüştürülür.
4. **Sınav:** Eğitilen model, eğitimde görmediği sorularda temel modelle yarıştırılır. Değerlendirme programın kendi
   **ilke karnesi** ve **gelişim kapısı** ile yapılır: hiçbir ilkenin notu düşmemeli, kritik hata artmamalı, gerçek
   bir iyileşme olmalı.
5. **Programa yükleme:** Model Zekâ ekranından eklenir. Program onu gece kendi bilgisayarındaki sınav setiyle bir kez
   daha sınar; temel modelden kötü çıkarsa kullanmaz.

## İki yol

- **A) GitHub üzerinden (önerilen; eğitimi Claude sizin adınıza başlatıp izleyebilir):** Kaggle API anahtarınızı bir
  kez GitHub deposuna gizli değer olarak eklersiniz. Sonra **Actions › Kaggle eğitimi › Run workflow** ile defterler
  Kaggle'da başlatılır. Durum, günlük ve sonuç raporu GitHub'da görünür; eğitilen model GitHub'dan indirilebilir.
- **B) Kaggle sitesinden elle:** Aşağıdaki "Adım adım" bölümü.

### A) GitHub üzerinden kurulum (bir kez)
1. kaggle.com › sağ üstte profil › **Settings › API › Create New Token**. İnen `kaggle.json` dosyasında `username`
   ve `key` değerleri bulunur.
2. github.com/terrazi/akil-hocasi › **Settings › Secrets and variables › Actions › New repository secret**:
   `KAGGLE_USERNAME` = username, `KAGGLE_KEY` = key.
3. **Actions › Kaggle eğitimi › Run workflow**:
   - `baslat` + `veri` + tur `1`: 1. veri turu Kaggle'da başlar (~11 saat).
   - `durum` + `veri` + tur `1`: Durumu gösterir; bittiyse günlüğü ve raporu getirir.
   - Daha çok veri için `baslat` + `veri` + tur `2`, `3`… Her tur öncekilerin üzerine ekler.
   - `baslat` + `egit` + veri_turu `N`: Bütün veri turlarıyla eğitir ve sınar. `durum` + `egit` bitince modeli
     **akilhocasi-model** adıyla GitHub'a koyar.

## Adım adım (B: Kaggle sitesinden elle)

### Hazırlık (bir kez)
- kaggle.com'da hesap açın ve **telefon numaranızı doğrulayın** (GPU ve internet erişimi için gerekli).
- Kaggle haftada yaklaşık 30 saat GPU verir. Bir eğitim turu yaklaşık 20 saattir.

### 1. defter: veri üretimi (~11 saat)
1. Bu bağlantıyla defteri açın:
   https://www.kaggle.com/notebooks/welcome?src=https://github.com/terrazi/akil-hocasi/blob/main/kaggle/1_veri_uretimi.ipynb
2. Sağ panelde **Accelerator → GPU T4 x2**, **Internet → On** seçin.
3. (İsteğe bağlı) Programdan aldığınız eğitim paketini ekleyin: **Add Input → Upload → Dataset** ile
   `akilhocasi_egitim_paketi_….zip` dosyasını yükleyin. Paketi programda **Zekâ › Kaggle eğitim paketi hazırla**
   düğmesiyle oluşturursunuz. Paket TOGÜ belgelerini ve altın soru setini eğitime katar.
4. Sağ üstten **Save Version → Save & Run All (Commit)** seçin. Defter arka planda çalışır, tarayıcıyı
   kapatabilirsiniz.
5. **Yoğun eğitim için** defteri 2–3 kez çalıştırın. Her seferinde **Add Input → Your Work** ile bu defterin önceki
   çıktısını ekleyin; veri kaldığı yerden birikir.

### 2. defter: eğitim ve sınav (~8–11 saat)
1. Defteri açın:
   https://www.kaggle.com/notebooks/welcome?src=https://github.com/terrazi/akil-hocasi/blob/main/kaggle/2_egitim_ve_sinama.ipynb
2. **GPU T4 x2** ve **Internet On** seçin. **Add Input → Your Work** ile 1. defterin son çıktısını ekleyin.
3. **Save Version → Save & Run All (Commit)**.
4. Bitince **Output** sekmesindeki `akilhocasi_model` klasöründen `akilhocasi-4b-….gguf` ve aynı adlı `.json`
   dosyasını indirin. `EGITIM_RAPORU.md` ilke karnesini ve kapı kararını gösterir.

### Programa yükleme
- Akıl Hocası'nda **Zekâ › Eğitilmiş modeli ekle…** düğmesine basıp `.gguf` dosyasını seçin. `.json` dosyası aynı
  klasörde olmalıdır.
- Model Kaggle sınavında kapıyı geçtiyse hemen kullanılır. Program onu gece kendi sınav setiyle ayrıca sınar.
- Birden çok bilgisayar için dosyayı ağdaki ortak klasöre koyup her bilgisayarda aynı düğmeyle ekleyebilirsiniz.

## Gerçekçi beklenti

Eğitim, küçük modelin Türkçe mevzuat dilini, programın cevap biçimini ve yordamlarını (gerekçe yazma, dürüstçe "hüküm
yok" deme, öz eleştiri, resmî yazı) belirgin şekilde iyileştirir. Yine de 4 milyar parametreli bir model, bulutta
çalışan çok büyük modellerin genel muhakeme gücüne ulaşmaz. Program bu yüzden her cevabı kaynakla sınamayı sürdürür.
Her eğitim turu bir öncekinin üzerine kurulur: programın biriktirdiği gerçek sorular ve altın set bir sonraki pakete
girer, model kurumun ihtiyacına giderek daha iyi uyar.

## Sorun giderme

- **"CUDA out of memory" (2. defter):** Ayarlar hücresinde `EN_COK_BELIRTEC = 4096` yapın.
- **"CUDA out of memory" (1. defter):** Ayarlar hücresinde `OGRETMEN = "Q4_K_S"` ya da `"Q3_K_M"` yapın; `PARALEL = 2`.
- **Unsloth kurulum hatası (2. defter):** Unsloth'un güncel Kaggle defterlerindeki kurulum hücresini kullanın
  (github.com/unslothai/notebooks, `Kaggle-Qwen3_5` defterleri).
- **mevzuat.gov.tr'ye ulaşılamadı:** Eğitim paketiyle (programın kütüphanesi) çalıştırın.
- **Süre doldu:** Veri kaybolmaz. 1. defteri önceki çıktısını girdi olarak ekleyip yeniden çalıştırın.
