"""Yordam Kitabı: Akıl Hocası'nın iş akışı yordamları ve kuralları (çekirdek modelin işleyiş biçimi).

Her yordam: amaç, girdi, adımlar, kurallar, başarısızlıkta ne yapılacağı, bağlı olduğu ilkeler, kalite ölçütleri,
ürettiği öğrenme sinyalleri ve geliştirilebilir ayarları (izinli aralıklarıyla) tanımlar. Program her işi bu
yordamlarla yürütür; kendini geliştirme yalnızca yordamların ayarlarında, derslerinde ve araçlarında (model,
arama, sıralama) olur. İlkeler (ilkeler.py) ve yordamların kuralları öğrenmeyle değişmez; ayarlar yalnızca izinli
aralıkta ve gelişim kapısından geçerek değişir.

Tasarım dokümanındaki "Çekirdek" bölümü ve programdaki Çekirdek El Kitabı bu dosyadan üretilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ilkeler import ILKELER


@dataclass(frozen=True)
class Ayar:
    ad: str
    aciklama: str
    varsayilan: float | int | bool | str
    alt: float | None = None
    ust: float | None = None
    secenekler: tuple = ()


@dataclass(frozen=True)
class Yordam:
    kod: str
    ad: str
    grup: str
    amac: str
    girdi: str
    adimlar: tuple[str, ...]
    kurallar: tuple[str, ...]
    basarisizlikta: tuple[str, ...]
    ilkeler: tuple[str, ...]
    olcutler: tuple[str, ...]
    ogrenme: tuple[str, ...]
    ayarlar: tuple[Ayar, ...] = field(default_factory=tuple)


GRUPLAR = ("Görev", "Bilgi", "Muhakeme", "Kalite", "Süreklilik", "Öğrenme")

YORDAMLAR: tuple[Yordam, ...] = (
    # ============================================================== GÖREV
    Yordam(
        "kabul", "Kabul ve sınıflandırma", "Görev",
        "Gelen isteği güvenli biçimde almak, türünü ve uygun beceriyi belirlemek.",
        "Kullanıcının yazdığı soru, yapıştırdığı ya da yüklediği metin/belge, önceki konuşma.",
        ("Girdideki kişisel verileri (TC kimlik, IBAN, telefon) maskele; maskesiz hâli yalnız bellekte tut.",
         "İsteğin türünü belirle: bilgi, işlem, yazı, hesap, ön kontrol.",
         "Önceki konuşmayla bağını kur: 'peki', 'bu durumda', 'o personel' gibi göndermeleri işaretle.",
         "Uygun beceriyi seç (danışma, resmî yazı; ileride hesap ve ön kontrol) ve iş kaydını aç."),
        ("Kamu sistemlerinde işlem yapma talebi (KBS'ye gir, EBYS'de imzala vb.) üstlenilmez; nasıl yapılacağı anlatılır.",
         "Kişisel veri gerekmedikçe istenmez; istenmişse yalnızca maskeli işlenir.",
         "Tek istekte birden fazla iş varsa hepsi alt görev olarak kaydedilir; hiçbiri sessizce atlanmaz."),
        ("Tür belirlenemezse 'bilgi' kabul edilir ve anlama yordamına geçilir.",
         "Beceri tanımlı değilse danışma becerisiyle ele alınır ve kullanıcıya hangi kısmın yapılamadığı söylenir."),
        ("gizlilik", "yetki"),
        ("Doğru beceri seçim oranı", "Maskelenmeden işlenen kişisel veri sayısı (sıfır)"),
        ("Kullanıcının beceri değiştirmesi (ör. danışmadan yazıya geçmesi) yanlış sınıflandırma sinyalidir.",),
    ),
    Yordam(
        "anlama", "Anlama (durum çözümleme)", "Görev",
        "İsteği bir danışman gibi çözümlemek: kim, ne, ne zaman, hangi statü, asıl soru ne.",
        "Maskelenmiş istek, önceki konuşma, ilgili dersler.",
        ("Olguları tek tek çıkar: kişi, statü (657/4-A, 4/B, 2547, işçi), birim, olayın tarihi, yapılmak istenen işlem.",
         "Asıl soruyu ve onu cevaplamak için gereken alt soruları yaz.",
         "Arama terimlerini mevzuat diliyle ve eş anlamlılarıyla üret (ör. 'ücretsiz izin' → 'aylıksız izin').",
         "Zorluğu belirle: kolay (tek hüküm), orta (birden çok hüküm), zor (çatışma, istisna, hesap, yorum).",
         "Cevabı değiştirecek eksik bilgiyi belirle."),
        ("Kullanıcının söylemediği olgu varsayılmaz; varsayım gerekiyorsa açıkça 'varsayım' diye yazılır.",
         "Önceki konuşmada belirtilen statü ve tarih, kullanıcı değiştirmedikçe korunur.",
         "Alt soru sayısı en fazla beştir; her alt soru tek bir hukuki meseleye karşılık gelir."),
        ("Dil modeli yoksa ya da çıktı geçersizse kural tabanlı çözümleme kullanılır.",),
        ("durum", "muhakeme"),
        ("Altın setteki netleştirme gerektiren sorularda eksik bilgiyi bulma oranı",),
        ("Kullanıcının sonradan düzelttiği olgu (\"hayır, 4/B'yim\") anlama hatasıdır ve ders adayı olur.",),
        (Ayar("alt_soru_siniri", "En fazla alt soru sayısı", 5, 1, 8),),
    ),
    Yordam(
        "netlestirme", "Netleştirme", "Görev",
        "Cevabı değiştiren eksik bilgiyi kullanıcıya sormak; beklerken genel çerçeveyi yine vermek.",
        "Durum çözümlemesindeki eksik bilgiler.",
        ("Eksik bilginin cevabı gerçekten değiştirip değiştirmediğini denetle.",
         "Değiştiriyorsa en fazla iki kısa, seçenekli soru hazırla (ör. 'Statü: 4/A mı, 4/B mi, akademik mi?').",
         "Soruları cevabın en üstünde göster; cevabın geri kalanında olası her durum için genel çerçeveyi ver."),
        ("Cevabı değiştirmeyen ayrıntı sorulmaz.", "Aynı soru aynı konuşmada ikinci kez sorulmaz.",
         "Kullanıcı cevaplarsa aynı konuşma bağlamında yeniden işleme alınır."),
        ("Kullanıcı cevaplamazsa en olası durum varsayım olarak açıkça belirtilerek cevap verilir.",),
        ("durum", "guven"),
        ("Gereksiz soru oranı (kullanıcının 'önemi yok' dediği)", "Netleştirme sonrası cevap kalitesindeki artış"),
        ("Sorulmayan ama sonradan önemli çıkan bilgi, anlama ve netleştirme dersi olur.",),
        (Ayar("soru_siniri", "Bir cevapta en fazla netleştirme sorusu", 2, 0, 3),),
    ),
    Yordam(
        "planlama", "Planlama", "Görev",
        "Alt sorular için araştırma planı ve bütçe çıkarmak.",
        "Alt sorular, terimler, zorluk.",
        ("Her alt soru için aranacak norm düzeylerini sırala (kanun → yönetmelik → TOGÜ düzenlemesi → görüş/emsal).",
         "Önce yerel kütüphane, eksik kalırsa resmî kaynaklarda canlı arama planla.",
         "Zorluğa göre bütçe ayır: adım sayısı, okunacak kaynak sayısı, eleştiri turu."),
        ("Her alt soru en az bir kez aranır.", "Kolay sorularda bütçe aşılmaz; zor sorularda eleştiri yordamı zorunludur."),
        ("Plan üretilemezse alt soru başına tek tarama uygulanır.",),
        ("muhakeme", "somutluk"),
        ("Bütçe içinde tamamlanan iş oranı", "Cevaplanmadan kalan alt soru oranı"),
        ("Cevaplanmadan kalan alt soru, tarama ve bulma ayarlarının sinyalidir.",),
        (Ayar("derin_okuma", "Zor sorularda okunacak en fazla kaynak", 10, 6, 20),),
    ),
    # ============================================================== BİLGİ
    Yordam(
        "tarama", "Tarama (yerel kaynak arama)", "Bilgi",
        "Yerel kütüphanede, işlem kartlarında ve doğrulanmış soru-cevap bankasında ilgili hükümleri bulmak.",
        "Alt sorular, terimler, öğrenilmiş eş anlamlılar.",
        ("Doğrulanmış kart ve soru-cevapları ara; dayanakları havuza al.",
         "Her alt soru için kelime araması (Türkçe ek budamalı) ve anlam araması (vektör) yap; sonuçları birleştir.",
         "En iyi sonuçların atıf zincirini izle (bir maddenin gönderme yaptığı maddeler).",
         "Öğrenen sıralayıcıyla adayları sırala."),
        ("Yalnızca yürürlükteki (ya da olayın tarihinde yürürlükte olan) metin aday olur.",
         "Mülga madde aday listesinde kalabilir ama dayanak yapılamaz.",
         "İkincil site ipuçları dayanak değildir; yalnızca arama yönü verir."),
        ("Sonuç yoksa terimler genişletilip bir kez daha aranır; yine yoksa bulma yordamına geçilir.",),
        ("dogruluk", "guncellik"),
        ("Altın setteki beklenen dayanağın ilk 10 adayda bulunma oranı (MRR@10)",),
        ("Kullanıcının tıkladığı ve 'faydalı' dediği kaynaklar sıralayıcı eğitim verisidir.",),
        (Ayar("aday_sayisi", "Alt soru başına aday sayısı", 12, 6, 30),
         Ayar("anlam_agirligi", "Anlam aramasının birleştirmedeki ağırlığı", 0.5, 0.0, 1.0),
         Ayar("atif_derinligi", "Atıf zinciri derinliği", 1, 0, 2)),
    ),
    Yordam(
        "bulma", "Bulma (resmî kaynaklarda arama)", "Bilgi",
        "Yerelde bulunamayan hükmü resmî kaynaklarda bulup kütüphaneye kazandırmak.",
        "Cevaplanmadan kalan alt sorular, terimler.",
        ("Resmî Gazete, mevzuat.gov.tr, TOGÜ siteleri ve üst kurum sitelerinde hedefli arama yap.",
         "Bulunan belgeyi değerlendirme hattından geçir (kamu sistemi/oturum denetimi, beyaz liste, maskeleme, sürüm).",
         "Kütüphaneye eklenen belgelerle taramayı yinele."),
        ("Yalnızca beyaz listedeki birincil kaynaklar dayanak olur.", "Giriş gerektiren hiçbir sayfa okunmaz.",
         "Çevrimdışıyken atlanır ve cevapta belirtilir."),
        ("Bulunamazsa soru takibe alınır; her güncellemede yeniden aranır.",),
        ("dogruluk", "yetki", "gizlilik"),
        ("Canlı aramayla cevaplanan alt soru oranı",),
        ("Sık bulunamayan konular, Kaynak Havuzu'na eklenecek site ve tarama hedefi önerisidir.",),
        (Ayar("canli_arama", "Yerelde yetersizse canlı arama yap", True),),
    ),
    Yordam(
        "secme", "Seçme (kanıt seçimi)", "Bilgi",
        "Aday hükümlerden soruyu gerçekten cevaplayanları seçmek ve sıralamak.",
        "Aday pasajlar, olgular, olay tarihi.",
        ("Her adayı ilgililik, güncellik ve norm düzeyiyle puanla.",
         "Aynı konuda farklı norm düzeylerinden hükümleri birlikte tut (kanun + uygulama yönetmeliği + TOGÜ düzenlemesi).",
         "Çelişen hükümleri işaretle ve çatışma çözümüne gönder."),
        ("Sunulacak kaynak sayısı bütçeyi aşmaz.", "Aynı maddenin eski ve yeni sürümü birlikte sunulmaz; eskisi uyarıyla anılır."),
        ("Seçilecek kaynak yoksa 'hüküm yok' yoluna gidilir (çözüm odaklılık ilkesi).",),
        ("dogruluk", "guncellik", "hiyerarsi"),
        ("Seçilen kaynakların cevapta kullanılma oranı",),
        ("Cevapta hiç kullanılmayan seçili kaynak, seçme ayarlarının sinyalidir.",),
        (Ayar("sunulacak_kaynak", "Taslağa verilecek en fazla kaynak", 6, 3, 10),),
    ),
    Yordam(
        "analiz", "Analiz (hüküm çözümleme)", "Bilgi",
        "Seçilen her hükümden şartları, süreleri, istisnaları, yetkili makamı ve gerekli belgeleri ayrıştırmak.",
        "Seçilen kaynak pasajları.",
        ("Her hükmü 'şart → sonuç' biçiminde ayrıştır.",
         "Süre, oran, tutar ve tarihleri kaynaktaki yazılışıyla çıkar.",
         "İstisnaları ('ancak', 'şu kadar ki', 'saklıdır') ve atıfları ayrıca işaretle.",
         "Yetkili makamı ve gereken belgeleri/formları çıkar."),
        ("Analiz yalnızca kaynak metne dayanır; kaynakta olmayan şart eklenmez.",),
        ("Ayrıştırılamayan hüküm, analiz edilmeden alıntıyla kullanılır.",),
        ("dogruluk", "somutluk"),
        ("Analizdeki her sayının kaynakta bulunma oranı (çapraz kontrol)",),
        ("Çapraz kontrolde düşen sayı, analiz dersi olur.",),
    ),
    # ============================================================== MUHAKEME
    Yordam(
        "yordama", "Yordama (çıkarım ve uygulama)", "Muhakeme",
        "Kuralı somut duruma uygulamak: olgu → kural → şartların karşılaştırılması → sonuç.",
        "Olgular, analiz edilmiş hükümler.",
        ("Uygulanacak kuralı ve dayanağını yaz.",
         "Kuralın her şartını olgularla tek tek karşılaştır: karşılanıyor / karşılanmıyor / bilgi eksik.",
         "İstisnaların bu durumda işleyip işlemediğini değerlendir.",
         "Sonucu ve sonucun nedenini yaz; bilgi eksikse sonucu koşula bağla ('…ise …')."),
        ("Her şart karşılaştırması bir kaynağa bağlanır.",
         "Kaynakta açıkça yazmayan çıkarım 'değerlendirme' olarak etiketlenir ve yeni sayı/süre/madde içeremez.",
         "Sonuç, yetkili makamın takdirini gerektiriyorsa bunu belirtir."),
        ("Şartlar karşılaştırılamıyorsa (bilgi eksik) sonuç koşullu verilir ve netleştirme sorusu eklenir.",),
        ("muhakeme", "guven", "yetki"),
        ("Gerekçeli uygulama bölümü bulunan cevap oranı", "Şart karşılaştırmalarının kaynaklı olma oranı"),
        ("Kullanıcının 'sonuç yanlış' düzeltmesi yordama dersidir.",),
        (Ayar("dusunme_kipi", "Zor sorularda modelin düşünme kipi", True),),
    ),
    Yordam(
        "catisma", "Çatışma çözümü", "Muhakeme",
        "Çelişen hükümler arasında uygulanacak olanı normlar hiyerarşisine göre belirlemek.",
        "Çelişki işaretli hükümler.",
        ("Norm düzeylerini karşılaştır: üst norm alt normdan önce gelir.",
         "Aynı düzeyde özel hüküm genel hükümden, sonraki düzenleme önceki düzenlemeden önce gelir.",
         "TOGÜ düzenlemesi, dayandığı üst norm maddesi sonradan değiştiyse uyarıyla anılır."),
        ("Çatışma cevapta gizlenmez; hangi hükmün neden uygulandığı açıkça yazılır.",),
        ("Çözülemeyen çatışmada cevap 'Çelişkili' olarak işaretlenir ve görüş alınacak birim belirtilir.",),
        ("hiyerarsi", "guven"),
        ("Hiyerarşi testinden geçen cevap oranı",),
        ("Çözülemeyen çatışmalar uzman görüşü önceliği olarak raporlanır.",),
    ),
    Yordam(
        "sentez", "Sentez (taslak)", "Muhakeme",
        "Danışman cevabını ya da yazı metnini, her cümlesi kaynağa bağlı olarak oluşturmak.",
        "Olgular, uygulama sonucu, analiz edilmiş hükümler, beceriye özgü şablon.",
        ("Kısa cevabı (sonuç) ilk iki cümlede ver.",
         "Gerekçeyi (uygulama), yapılacakları (adımlar), dikkat edilecekleri ve değerlendirmeyi ayrı bölümlerde yaz.",
         "Güven düzeyini belirle: kesin / yoruma açık / hüküm yok.",
         "Form, belge ve birimleri somut olarak an."),
        ("Her bilgi cümlesi en az bir kaynak kimliğine bağlanır.", "Alıntı harfi harfine ve tırnak içinde yapılır.",
         "Resmî ve sade Türkçe kullanılır; boş kalıplar kullanılmaz."),
        ("Yapılandırılmış çıktı alınamazsa alıntıya dayalı taslağa geçilir.",),
        ("dogruluk", "somutluk", "resmi_dil", "guven"),
        ("Sınamadan çıkarılmadan geçen cümle oranı",),
        ("Sınamada çıkarılan cümleler sentez dersi ve eğitim verisi (negatif örnek) olur.",),
        (Ayar("sicaklik", "Taslak üretim sıcaklığı", 0.2, 0.0, 0.6),
         Ayar("ornek_sayisi", "Biçim için gösterilen doğrulanmış örnek sayısı", 2, 0, 4)),
    ),
    # ============================================================== KALİTE
    Yordam(
        "sinama", "Sınama (doğrulama testleri)", "Kalite",
        "Taslaktaki her cümleyi ve cevabın bütününü ilkelere göre otomatik denetlemek.",
        "Taslak, kaynaklar.",
        ("Kaynak testi: kaynaksız ya da beyaz liste dışı kaynağa dayanan cümle çıkarılır.",
         "Güncellik testi: mülga maddeye dayanan cümle çıkarılır; eski sürüm uyarılır.",
         "Alıntı testi: kaynakta birebir bulunmayan alıntı reddedilir.",
         "Çapraz kontrol: cümledeki her sayı kaynakta bulunmalıdır.",
         "Hiyerarşi testi: alt düzenlemenin dayandığı üst norm sonradan değiştiyse uyarılır.",
         "Biçim testi: ekonomik kod, TC kimlik ve IBAN biçimleri denetlenir; kişisel veri maskelenir.",
         "Somutluk testi: boş kalıplı cümle çıkarılır.",
         "Değerlendirme testi: yorum cümlesi kaynaklarda bulunmayan sayı, süre ya da madde içeremez.",
         "Güven testi: güven düzeyi doğrulama sonucuyla tutarlı olmalıdır."),
        ("Testler atlanamaz ve devre dışı bırakılamaz.", "Çıkarılan her cümle gerekçesiyle kaydedilir."),
        ("Kısa cevapta hiçbir cümle kalmazsa 'hüküm yok' yoluna gidilir.",),
        tuple(i.kod for i in ILKELER if i.kod not in ("ogrenme",)),
        ("İlke karnesi (her ilke için 0–1)",),
        ("Her çıkarma bir hata örneğidir: eleştiri, düzeltme ve ders yordamlarını besler.",),
    ),
    Yordam(
        "elestirme", "Eleştirme (öz eleştiri)", "Kalite",
        "Taslağa bağımsız bir denetçi gözüyle bakıp eksikleri bulmak.",
        "Taslak, olgular, alt sorular, sınama sonuçları.",
        ("Cevaplanmayan alt soru var mı?", "Atlanan şart ya da istisna var mı?",
         "Statü, tarih ya da birim yanlış mı varsayılmış?", "Gereğinden kesin konuşulmuş mu (güven fazla mı)?",
         "Adımlar uygulanabilir ve sıralı mı; form ve birimler doğru mu?",
         "Sınamada çıkarılan cümlelerin yerine konması gereken bilgi var mı?"),
        ("Eleştiri yalnızca taslak ve kaynaklar üzerinden yapılır; yeni bilgi eklemez, düzeltme önerir.",
         "Zor sorularda ve sınamada hata çıkan cevaplarda zorunludur."),
        ("Eleştiri üretilemezse sınama sonuçları eleştiri yerine kullanılır.",),
        ("muhakeme", "guven", "dogruluk"),
        ("Eleştiri sonrası düzeltilen sorun sayısı",),
        ("Sık tekrarlanan eleştiri türleri ders adayı olur.",),
        (Ayar("elestiri_esigi", "Eleştirinin çalışacağı en düşük zorluk", "orta", secenekler=("kolay", "orta", "zor")),),
    ),
    Yordam(
        "duzeltme", "Düzeltme (revizyon)", "Kalite",
        "Eleştiri ve sınama bulgularına göre taslağı hedefli olarak düzeltmek.",
        "Taslak, eleştiri bulguları, çıkarılan cümleler ve gerekçeleri.",
        ("Yalnızca bulgu olan bölümleri yeniden yaz.", "Çıkarılan cümlenin yerine kaynakta karşılığı olanı koy ya da sil.",
         "Düzeltilen taslağı yeniden sınamadan geçir."),
        ("Düzeltme kaynakta olmayan bilgi ekleyemez.", "En fazla iki düzeltme turu yapılır.",
         "Düzeltme sonrası daha kötü sınama sonucu çıkarsa önceki taslak korunur."),
        ("İki turda düzelmeyen sorun, yeniden işleme yordamına gönderilir.",),
        ("dogruluk", "muhakeme"),
        ("Düzeltme sonrası ilke karnesindeki artış",),
        ("Başarılı düzeltmeler (önce/sonra) eğitim verisi olur.",),
        (Ayar("tur_siniri", "En fazla düzeltme turu", 1, 0, 2),),
    ),
    Yordam(
        "yeniden_isleme", "Yeniden işleme alma", "Kalite",
        "Kaynak eksikliği ya da yanlış anlama nedeniyle düzelmeyen işi baştan, eksik noktaya odaklanarak yeniden yürütmek.",
        "Eleştiri bulguları (eksik alt soru, yanlış statü), kullanıcı düzeltmesi ya da netleştirme cevabı.",
        ("Sorunun kaynağını belirle: anlama, tarama/bulma ya da yordama.",
         "İlgili yordama geri dön ve yalnızca eksik kısmı yeniden işle.",
         "Yeni sonuçları önceki taslakla birleştir ve sınamadan geçir."),
        ("Bir işte en fazla bir kez yeniden işleme yapılır (kullanıcı yeni bilgi verirse yeni iş sayılır).",
         "Yeniden işleme sonucu öncekinden kötüyse önceki sonuç sunulur."),
        ("Yine çözülmezse 'hüküm yok' yolu: kesin olanlar, en yakın hüküm, somut yol, takip.",),
        ("cozum", "muhakeme"),
        ("Yeniden işlemeyle kurtarılan iş oranı",),
        ("Yeniden işlemeye düşen soru türleri anlama ve tarama dersleridir.",),
        (Ayar("acik", "Yeniden işleme açık", True),),
    ),
    Yordam(
        "sunum", "Sunum", "Kalite",
        "Sonucu kullanıcının hemen kullanabileceği biçimde sunmak ve nasıl düşünüldüğünü göstermek.",
        "Sınanmış cevap, düşünce kaydı.",
        ("Durum etiketi (Doğrulandı, Çelişkili, Doğrudan hüküm yok) ve güven düzeyi.",
         "Netleştirme soruları (varsa) en üstte, tıklanabilir.",
         "Kısa cevap, gerekçe (uygulama), adımlar, dikkat, değerlendirme, belgeler, kaynaklar.",
         "'Nasıl düşündüm' kaydı ve doğrulama raporu."),
        ("Çıktı TASLAK ve danışma niteliğindedir; son karar yetkili makamındır.", "Kişisel veriler maskeli gösterilir."),
        ("Bölümlerden biri boşsa gösterilmez; boş bölüm doldurulmaz.",),
        ("guven", "yetki", "gizlilik", "resmi_dil"),
        ("Kullanıcının cevabı 'faydalı' bulma oranı",),
        ("Faydalı / hatalı işaretleri ve düzeltmeler öğrenme yordamlarına gider.",),
    ),
    # ============================================================== SÜREKLİLİK
    Yordam(
        "kayit", "Kayıt ve izlenebilirlik", "Süreklilik",
        "Her işin neye dayandığını, hangi yordamlardan geçtiğini ve neyin neden çıkarıldığını saklamak.",
        "Düşünce kaydı, kaynaklar, sınama sonuçları.",
        ("İş kaydını (olay) soru, kaynak anahtarları, yordam izi ve sonuçla birlikte yaz.",
         "Kişisel verileri maskeli sakla.", "Gizlilik süresi dolan kayıtları sil."),
        ("Kayıt olmadan öğrenme yapılmaz.", "Kayıtlar yalnızca bu bilgisayarda (ve izin verilen ortak klasörde) tutulur."),
        ("Kayıt yazılamazsa cevap yine verilir; öğrenme o iş için atlanır.",),
        ("gizlilik", "ogrenme"),
        ("Kaydı eksik iş oranı",),
        ("Kayıtlar tüm öğrenme yordamlarının ham verisidir.",),
    ),
    Yordam(
        "takip", "Takip", "Süreklilik",
        "Cevaplanamayan soruları unutmamak; kaynak bulununca kullanıcıya haber vermek.",
        "'Hüküm yok' cevapları.",
        ("Soruyu takibe al.", "Her güncellemede yeniden ara.", "Bulunca bildir ve takipten düş."),
        ("Takipteki soru kullanıcı istemedikçe silinmez.",),
        ("Uzun süre bulunamayan soru, birim uzmanı görüşü önerisi olarak raporlanır.",),
        ("cozum",),
        ("Takipten çözülen soru oranı",),
        ("Takipteki sorular bulma yordamının hedef listesidir.",),
    ),
    Yordam(
        "bakim", "Bilgi bakımı", "Süreklilik",
        "Kütüphaneyi güncel tutmak ve değişen mevzuata dayanan bilgiyi yeniden doğrulamak.",
        "Takvimli tarama, gözlem ve kaynak havuzu sonuçları.",
        ("Değişen belgeyi sürümle (eski sürüm saklanır).",
         "Ona dayanan işlem kartlarını ve soru-cevapları yeniden doğrulamaya al.",
         "Anlam vektörlerini değişen maddeler için yenile."),
        ("Doğrulanmamış bilgi soru-cevap bankasında 'doğrulandı' olarak kalmaz.",),
        ("Kaynağa ulaşılamazsa son doğrulanmış sürüm uyarıyla kullanılır.",),
        ("guncellik", "dogruluk"),
        ("Yeniden doğrulamayı bekleyen kayıt sayısı",),
        ("Sık değişen kaynaklar tarama sıklığı ayarına sinyaldir.",),
    ),
    # ============================================================== ÖĞRENME
    Yordam(
        "test", "Test etme (sınav)", "Öğrenme",
        "Programın gerçek başarısını düzenli olarak ölçmek.",
        "Altın soru seti (uzman onaylı), sentetik soru seti (programın ürettiği ve doğruladığı).",
        ("Her soruyu tam iş akışıyla cevapla (kayıt ve takip olmadan).",
         "Beklenen dayanak ve ifadeyle karşılaştır; kritik hatayı (yanlışken 'Doğrulandı') ayrıca say.",
         "İlke karnesini hesapla ve geçmişe yaz."),
        ("Sınav verisi eğitimde kullanılmaz (altın set her zaman ayrı tutulur).",
         "Karnede düşüş varsa kullanıcı uyarılır."),
        ("Altın set yoksa sentetik setle ölçülür ve bu açıkça belirtilir.",),
        ("ogrenme",),
        ("Başarı oranı, kritik hata sayısı, ilke notları",),
        ("Kalan sorular ders ve tarama hedefidir.",),
        (Ayar("sentetik_soru", "Sınavdaki en fazla sentetik soru", 60, 10, 300),),
    ),
    Yordam(
        "geri_bildirim", "Geri bildirim alma", "Öğrenme",
        "Kullanıcının 'faydalı', 'hatalı' işaretlerini ve düzeltmelerini öğrenmeye dönüştürmek.",
        "Kullanıcı işareti, düzeltme metni, tıklanan kaynaklar.",
        ("Faydalı cevabı örnek hafızasına ve (doğrulamadan geçerse) soru-cevap bankasına ekle.",
         "Hatalı işaretini ve düzeltmeyi ders adayına dönüştür.", "Tıklanan kaynakları sıralayıcı verisine ekle."),
        ("Geri bildirim tek başına bilgi kaynağı değildir; kaynakla doğrulanmadan banka ya da ders olmaz.",),
        ("Doğrulanamayan düzeltme uzman incelemesi listesine alınır.",),
        ("ogrenme", "dogruluk"),
        ("Geri bildirimlerin öğrenmeye dönüşme oranı",),
        ("Tüm öğrenme yordamlarının girdisidir.",),
    ),
    Yordam(
        "ders", "Ders çıkarma", "Öğrenme",
        "Hatalardan, düzeltmelerden ve yeniden işlemelerden genellenebilir yöntem dersleri çıkarmak.",
        "Sınamada çıkarılan cümleler, eleştiri bulguları, kullanıcı düzeltmeleri, sınavda kalan sorular.",
        ("Hatanın hangi yordamda doğduğunu belirle.",
         "Yöntem dersi yaz: 'Şu tür sorularda şunu yap/şunu kontrol et' (bilgi değil, yöntem).",
         "Dersi aday olarak kaydet; gelişim kapısında sınanmadan kullanma."),
        ("Ders kesin bilgi (süre, oran, madde) içeremez; bilgi kütüphaneden gelir.",
         "Ders bir ilkeyi gevşetemez ya da bir testi atlatamaz.", "Aynı anlamdaki ders tekrar eklenmez."),
        ("Genellenemeyen hata yalnızca kayıtta kalır.",),
        ("ogrenme",),
        ("Benimsenen ders sayısı ve derslerin karneye katkısı",),
        ("Benimsenen dersler anlama, sentez ve eleştiri talimatlarına eklenir.",),
        (Ayar("ders_siniri", "Bir işte kullanılan en fazla ders", 3, 0, 6),),
    ),
    Yordam(
        "strateji", "Strateji ayarı", "Öğrenme",
        "Yordamların ayarlarını izinli aralıkta deneyerek daha iyi çalışma biçimini bulmak.",
        "Yordam ayarları, sınav sonuçları, iş türlerine göre başarı istatistikleri.",
        ("Zayıf karne notuna bağlı yordamı seç.", "Bir ayarı izinli aralıkta tek adım değiştir (bir seferde tek değişiklik).",
         "Sınavda eski ve yeni ayarı karşılaştır.", "Kapıdan geçerse benimse; geçmezse eski ayarda kal."),
        ("Ayar izinli aralığın dışına çıkamaz.", "Kurallar ve ilkeler ayar değildir; değiştirilemez.",
         "Kullanıcının elle verdiği ayar önceliklidir."),
        ("Sınav seti küçükse (10 sorudan az) strateji ayarı yapılmaz.",),
        ("ogrenme",),
        ("Benimsenen ayar değişikliklerinin karneye katkısı",),
        ("Hangi ayarın hangi iş türünde işe yaradığı birikir.",),
    ),
    Yordam(
        "benimseme", "Benimseme (gelişim kapısı) ve geri alma", "Öğrenme",
        "Her türlü gelişimi (ders, ayar, sıralayıcı, anlam katmanı, model) aynı kapıdan geçirmek; kötüleşeni geri almak.",
        "Eski ve yeni karne.",
        ("Hiçbir ilkenin notu tolerans payından fazla düşmemeli.", "Kritik hata artmamalı.",
         "Başarı ya da ilke ortalaması gerçekten artmalı.",
         "Benimsenen değişiklik sonraki sınavlarda kötüleşirse otomatik geri alınır."),
        ("Kapı atlanamaz.", "Her karar gerekçesiyle gelişim geçmişine yazılır ve kullanıcıya gösterilir."),
        ("Ölçüm yapılamazsa değişiklik benimsenmez.",),
        ("ogrenme",),
        ("Geri alınan değişiklik oranı (düşük olmalı)",),
        ("Gelişim geçmişi, programın neyi neden öğrendiğinin kaydıdır.",),
    ),
    Yordam(
        "model_gelisimi", "Model gelişimi", "Öğrenme",
        "Dil modelini ve arama modellerini kendi kendine güçlendirmek.",
        "Doğrulanmış süreç kayıtları, sentetik sorular, model kataloğu.",
        ("Öğrenen sıralayıcıyı ve anlam katmanını doğrulanmış verilerle yeniden eğit.",
         "Kütüphaneden sentetik sorular üret, doğrula ve sınav/eğitim setlerine ayır.",
         "Katalogda bu bilgisayara uygun daha iyi bir model varsa boştayken indir ve yarışa sok.",
         "Yerel eğitim komutu tanımlı ve donanım uygunsa doğrulanmış kayıtlardan ek katman eğit.",
         "Her aday benimseme kapısından geçer."),
        ("Eğitim verisi yalnızca sınamadan geçmiş, kaynaklı kayıtlardan oluşur; altın set eğitimde kullanılmaz.",
         "Ağır işler yalnızca bilgisayar boştayken ve prizdeyken yapılır."),
        ("İndirme ya da eğitim yarıda kalırsa sonraki boş zamanda sürer.",),
        ("ogrenme",),
        ("Modeller arası karne farkı",),
        ("Model yarışlarının sonuçları katalog seçimini yönlendirir.",),
        (Ayar("model_yarisi", "Daha iyi modeli kendiliğinden dene", True),),
    ),
)

IS_AKISLARI: dict[str, tuple[str, ...]] = {
    "danisma": ("kabul", "anlama", "netlestirme", "planlama", "tarama", "bulma", "secme", "analiz", "yordama",
                "catisma", "sentez", "sinama", "elestirme", "duzeltme", "yeniden_isleme", "sunum", "kayit"),
    "yazi": ("kabul", "anlama", "netlestirme", "planlama", "tarama", "bulma", "secme", "analiz", "yordama",
             "sentez", "sinama", "elestirme", "duzeltme", "sunum", "kayit"),
    "gelisim": ("test", "geri_bildirim", "ders", "strateji", "model_gelisimi", "benimseme"),
    "bakim": ("bakim", "takip"),
}


def yordam(kod: str) -> Yordam:
    return next(y for y in YORDAMLAR if y.kod == kod)


def varsayilan_ayarlar() -> dict[str, dict]:
    return {y.kod: {a.ad: a.varsayilan for a in y.ayarlar} for y in YORDAMLAR if y.ayarlar}


def el_kitabi_md() -> str:
    """Çekirdek El Kitabı (Markdown): ilkeler, iş akışları ve yordamlar."""
    from .ilkeler import CEKIRDEK_SURUMU
    s = [f"# Akıl Hocası Çekirdek El Kitabı (sürüm {CEKIRDEK_SURUMU})", "",
         "## Temel çalışma ilkeleri", ""]
    s += [f"{n}. **{i.ad}:** {i.ilke}" for n, i in enumerate(ILKELER, 1)]
    s += ["", "## İş akışları", ""]
    adlar = {y.kod: y.ad for y in YORDAMLAR}
    s += [f"- **{ad}:** " + " → ".join(adlar[k] for k in akis) for ad, akis in
          (("Danışma", IS_AKISLARI["danisma"]), ("Resmî yazı", IS_AKISLARI["yazi"]),
           ("Kendini geliştirme", IS_AKISLARI["gelisim"]), ("Bakım", IS_AKISLARI["bakim"]))]
    ilke_adi = {i.kod: i.ad for i in ILKELER}
    for g in GRUPLAR:
        s += ["", f"## {g} yordamları"]
        for y in (y for y in YORDAMLAR if y.grup == g):
            s += ["", f"### {y.ad}", "", f"**Amaç:** {y.amac}", "", f"**Girdi:** {y.girdi}", "", "**Adımlar:**"]
            s += [f"{n}. {a}" for n, a in enumerate(y.adimlar, 1)]
            s += ["", "**Kurallar:**"] + [f"- {k}" for k in y.kurallar]
            s += ["", "**Başarısızlıkta:**"] + [f"- {k}" for k in y.basarisizlikta]
            s += ["", "**Bağlı ilkeler:** " + ", ".join(ilke_adi[k] for k in y.ilkeler)]
            s += ["", "**Ölçüt:** " + "; ".join(y.olcutler), "", "**Öğrenme sinyali:** " + " ".join(y.ogrenme)]
            if y.ayarlar:
                s += ["", "**Geliştirilebilir ayarlar:**"]
                for a in y.ayarlar:
                    aralik = (f" (izinli: {a.alt}–{a.ust})" if a.alt is not None else
                              f" (seçenekler: {', '.join(a.secenekler)})" if a.secenekler else " (açık/kapalı)")
                    s.append(f"- {a.aciklama}: varsayılan {a.varsayilan}{aralik}")
    return "\n".join(s) + "\n"
