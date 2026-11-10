"""Damıtma: büyük öğretmen modelin bilgisini, programın kendi çekirdek iş akışı üzerinden küçük modele aktarmak.

Kaggle GPU'sunda büyük bir açık model (öğretmen, ör. Qwen3.5-35B-A3B) çalışır. Program, kütüphanesindeki gerçek
mevzuattan personel soruları üretir ve öğretmen bu soruları **programın kendi yordamlarıyla** cevaplar: durum
çözümleme, gerekçeli sentez, öz eleştiri, düzeltme, hatadan ders çıkarma, çalışma sorusu üretme ve resmî yazı.
Her model çağrısı (programın gönderdiği istem ve öğretmenin cevabı) kaydedilir. Yalnızca programın sınamasından
geçen çağrılar eğitim örneği olur: doğrulanamayan cümle içeren, beklenen dayanağı bulamayan ya da biçimi bozuk
cevaplar atılır. Böylece küçük model, çalışırken göreceği istemlerin aynısıyla ve yalnız doğrulanmış cevaplarla
eğitilir (çekirdeğe uyum).

Çıktı (JSONL, satır başına bir örnek):
  {"gorev": "sentez", "messages": [{system}, {user}], "cevap": "...", "bolum": "egitim"|"sinav", "soru_id": "..."}
Sınav bölümündeki soruların hiçbir çağrısı eğitime girmez; eğitilen modelin karnesi bu sorularla çıkarılır.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..cekirdek.ilkeler import sistem_cekirdegi
from .sunucu import ModelHatasi, onbellek_dostu

log = logging.getLogger("akilhocasi")
_DUSUNCE = re.compile(r"<think>.*?</think>", re.S)

GELEN_YAZI_SEMASI = {
    "type": "object",
    "properties": {
        "gelen_yazi": {"type": "string"},
        "talimat": {"type": "string"},
        "tur": {"type": "string", "enum": ["cevap", "bilgi_isteme", "gorus", "talep", "duyuru", "ek_gonderme", "olur"]},
    },
    "required": ["gelen_yazi", "talimat", "tur"],
}
GELEN_YAZI_GOREVI = (
    "Bir üniversitenin idari birimine gelebilecek gerçekçi bir resmî yazı örneği yaz (eğitim için kurgu). "
    "Yazı aşağıdaki mevzuat maddesinin uygulanmasıyla ilgili olsun. Biçim: 'T.C.' satırı, idare adı büyük harfle, "
    "birim adı, 'Sayı : E-<8 rakam>-<dosya kodu>-<6 rakam>' ve aynı satırda GG.AA.YYYY tarih, 'Konu :' satırı, "
    "muhatap (büyük harf, yönelme hâli), metin (istenen husus açıkça yazılı) ve imza. Kişi adları kurgu olsun; "
    "gerçek T.C. kimlik no, IBAN yazma. Ardından talimat alanına, bu yazıya cevap verecek birimin söyleyeceği "
    "kısa cevabı yaz (birimin bildiği somut bilgi; mevzuat hükmünü tekrar etme). tur alanına yazı türünü yaz.")

# Görev sınıflandırması: istemde geçen sabit görev metninin başı (önce özgül olanlar)
_GOREV_IZLERI: list[tuple[str, str]] = []


def _gorev_izleri() -> list[tuple[str, str]]:
    if _GOREV_IZLERI:
        return _GOREV_IZLERI
    from ..answer.hat import DUZELTME_GOREVI, ELESTIRI_GOREVI, SENTEZ_GOREVI
    from ..cekirdek.dersler import DersHafizasi
    from ..cekirdek.muhakeme import COZUMLEME_GOREVI
    from ..yazi.hazirlayici import DUZELTME_GOREVI as YAZI_DUZELTME_GOREVI
    from ..yazi.hazirlayici import YAZI_GOREVI
    from .oz_gelisim import SORU_GOREVI
    for gorev, metin in (("ogretmen", GELEN_YAZI_GOREVI), ("yazi_duzeltme", YAZI_DUZELTME_GOREVI),
                         ("yazi", YAZI_GOREVI), ("duzeltme", DUZELTME_GOREVI), ("elestiri", ELESTIRI_GOREVI),
                         ("sentez", SENTEZ_GOREVI), ("cozumleme", COZUMLEME_GOREVI),
                         ("ders", DersHafizasi.DERS_GOREVI), ("soru", SORU_GOREVI)):
        _GOREV_IZLERI.append((gorev, metin[:70]))
    return _GOREV_IZLERI


def gorev_turu(mesajlar: list[dict]) -> str:
    metin = "\n".join(str(m.get("content", "")) for m in mesajlar)
    for gorev, iz in _gorev_izleri():
        if iz in metin:
            return gorev
    return "diger"


@dataclass
class Cagri:
    gorev: str
    mesajlar: list[dict]
    cevap: str
    json: bool
    dusunce: int = 0                 # öğretmenin düşünme uzunluğu (karakter; yalnız istatistik)
    sure: float = 0.0
    bitis: str = ""                  # sunucunun bitiş nedeni (stop / length)
    belirtec: int = 0                # üretilen belirteç sayısı
    ham: str = ""                    # ayıklamadan önceki ham çıktı (yalnız tanılama; kısaltılmış)


class OgretmenModeli:
    """llama-server'daki öğretmen için istemci. Kilitsizdir: sunucu çok yuvalı (-np) çalışır, sorular paralel
    işlenir. Her çağrı, o iş parçacığında açık kayıt varsa kayda eklenir."""

    hazir = True

    DUSUNEN_GOREVLER = ("sentez", "duzeltme", "yazi", "yazi_duzeltme")

    def __init__(self, adres: str, ad: str = "öğretmen", dusunen_gorevler: tuple[str, ...] = (),
                 zaman_asimi: float = 900, kisa_yaz: bool = True):
        # Düşünme varsayılan olarak kapalı: deneme turunda 35B öğretmen İngilizce ve döngüsel düşünüp 4400 belirteçlik
        # bütçeyi cevaba geçmeden bitirdi (çağrı başına ~160 sn). Programın kendi yordam zinciri (çözümleme → sentez →
        # eleştiri → düzeltme) zaten adım adım akıl yürütmedir.
        self.adres, self.ad = adres.rstrip("/"), ad
        self.dusunen = set(dusunen_gorevler)
        self.kisa_yaz = kisa_yaz
        self.zaman_asimi = zaman_asimi
        self._yerel = threading.local()
        self.sayac = {"cagri": 0, "hata": 0}
        self._sayac_kilit = threading.Lock()

    @contextmanager
    def kayit(self):
        onceki = getattr(self._yerel, "kayit", None)
        self._yerel.kayit = []
        try:
            yield self._yerel.kayit
        finally:
            self._yerel.kayit = onceki

    def sohbet(self, mesajlar, max_tokens=900, sicaklik=0.2, json_mod=False, json_sema=None, dusunme=False,
               akis=None) -> str:
        mesajlar = onbellek_dostu(mesajlar)
        gorev = gorev_turu(mesajlar)
        dusun = gorev in self.dusunen
        giden = kisa_yaz_notu(mesajlar, max_tokens) if self.kisa_yaz else mesajlar
        govde = {"messages": giden, "max_tokens": max_tokens + (3000 if dusun else 0), "temperature": sicaklik,
                 "top_p": 0.9, "cache_prompt": True, "chat_template_kwargs": {"enable_thinking": dusun}}
        # Düşünürken dilbilgisi (JSON şeması) uygulanmaz: llama.cpp kısıtı düşünce bloğunun içine de uygular ve
        # model JSON'u düşüncenin içinde bırakır. Düşünen öğretmen JSON'u istemdeki tarife göre kendisi yazar.
        if json_sema and not dusun:
            if gorev == "cozumleme" and self.kisa_yaz:
                json_sema = sik_sema(json_sema)     # öğretmen dizileri dolduruyor ve 500 belirteçte kesiliyordu
            govde["response_format"] = {"type": "json_schema", "json_schema": {"name": "cikti", "schema": json_sema}}
        elif json_mod and not dusun:
            govde["response_format"] = {"type": "json_object"}
        bas = time.monotonic()
        istek = urllib.request.Request(f"{self.adres}/v1/chat/completions", json.dumps(govde).encode("utf-8"),
                                       headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(istek, timeout=self.zaman_asimi) as y:  # noqa: S310 - yerel sunucu
                veri = json.loads(y.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            with self._sayac_kilit:
                self.sayac["hata"] += 1
            raise ModelHatasi(f"Öğretmen isteği başarısız: {e}") from e
        secim = veri["choices"][0]
        mesaj = secim.get("message") or {}
        ham = mesaj.get("content") or ""
        dusunce = mesaj.get("reasoning_content") or ""
        icerik, ek_dusunce = dusunceyi_ayir(ham)
        dusunce += ek_dusunce
        beklenen_json = bool(json_sema or json_mod)
        if beklenen_json and not dusun and not icerik and _json_gecerli(dusunce) is not None:
            icerik = _JSON_SON.search(dusunce).group(0)     # düşünme istenmediği hâlde sunucu cevabı oraya koymuş
        with self._sayac_kilit:
            self.sayac["cagri"] += 1
        kayit = getattr(self._yerel, "kayit", None)
        if kayit is not None:
            kayit.append(Cagri(gorev, mesajlar, icerik, beklenen_json, len(dusunce), round(time.monotonic() - bas, 1),
                               str(secim.get("finish_reason") or ""),
                               int((veri.get("usage") or {}).get("completion_tokens") or 0),
                               (ham[:2500] + ("\n…[düşünce] " + dusunce[-1500:] if dusunce else ""))))
        return icerik


_JSON_SON = re.compile(r"\{.*\}", re.S)


def sik_sema(sema):
    """Öğretmene giden şemada uzun dizilerin üst sınırını yarıya indirir (çıktı yine asıl şemaya uyar)."""
    if isinstance(sema, dict):
        yeni = {a: sik_sema(d) for a, d in sema.items()}
        if yeni.get("type") == "array" and isinstance(yeni.get("maxItems"), int) and yeni["maxItems"] >= 4:
            yeni["maxItems"] = max(2, yeni["maxItems"] // 2)
        return yeni
    if isinstance(sema, list):
        return [sik_sema(x) for x in sema]
    return sema


def kisa_yaz_notu(mesajlar: list[dict], max_tokens: int) -> list[dict]:
    """Yalnız öğretmene giden istemin sonuna uzunluk notu ekler (kayda ve eğitim örneğine girmez). Öğretmen
    ayrıntılı yazınca programın belirteç sınırında kesiliyordu; öğrenci de çalışırken aynı sınırla yazacak.
    Türkçede bir belirteç ~3 karakter."""
    if not mesajlar or mesajlar[-1].get("role") != "user":
        return mesajlar
    karakter = int(max_tokens * 3 * 0.7)
    not_ = (f"\n\n[Uzunluk sınırı: cevabın tamamı en çok yaklaşık {karakter} karakter olsun. Dizilerde yalnız gerçekten "
            "gerekli öğeleri ver; her öğe tek ve kısa bir cümle olsun. Sonuç alanını (ör. kisa_cevap) boş bırakma; "
            "kısaltmayı ayrıntıdan yap. Kısalık için doğruluktan ve kaynak göstermekten ödün verme.]")
    son = dict(mesajlar[-1])
    son["content"] = str(son.get("content", "")) + not_
    return mesajlar[:-1] + [son]


def dusunceyi_ayir(metin: str) -> tuple[str, str]:
    """Ham çıktıdan düşünceyi ayırır: tam <think>…</think> blokları ve (şablon düşünceyi istemde açtıysa)
    açılışı görünmeyen düşüncenin sonundaki tek </think>. (cevap, düşünce) döner."""
    dusunce = "".join(re.findall(r"<think>(.*?)</think>", metin, re.S))
    metin = _DUSUNCE.sub("", metin)
    if "</think>" in metin:
        once, _, metin = metin.rpartition("</think>")
        dusunce += once
    return metin.replace("<think>", "").strip(), dusunce


_BOLUMLER = ("kisa_cevap", "uygulama", "adimlar", "dikkat", "degerlendirme")


def _cumle_anahtari(metin: str) -> str:
    from ..core.maskeleme import metni_maskele
    return re.sub(r"\s+", " ", metni_maskele(str(metin).strip())).strip()


def dogrulanmis_taslak(v: dict, cikan: set[str]) -> tuple[dict, int, int]:
    """Taslaktan sınamada çıkarılan cümleleri atar. (ayıklanmış taslak, cümle sayısı, atılan) döner."""
    yeni, toplam, atilan = dict(v), 0, 0
    for b in _BOLUMLER:
        ogeler = v.get(b)
        if not isinstance(ogeler, list):
            continue
        kalan = []
        for o in ogeler:
            metin = o.get("metin", "") if isinstance(o, dict) else str(o)
            if not str(metin).strip():
                continue
            toplam += 1
            if _cumle_anahtari(metin) in cikan:
                atilan += 1
                continue
            kalan.append(o)
        yeni[b] = kalan
    return yeni, toplam, atilan


def _isaretsiz(v):
    """Metin alanlarındaki Markdown kalın/italik işaretlerini kaldırır (program düz metin gösterir)."""
    if isinstance(v, dict):
        return {a: _isaretsiz(d) for a, d in v.items()}
    if isinstance(v, list):
        return [_isaretsiz(x) for x in v]
    if isinstance(v, str):
        return re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), v)
    return v


def _kaynak_satirlari(k: "Cagri") -> list[str]:
    metin = "\n".join(str(m.get("content", "")) for m in k.mesajlar if m.get("role") == "user")
    return re.findall(r"^\[K\d+\][^\n]*", metin, re.M)


def _json_gecerli(metin: str) -> dict | None:
    from ..answer.llm import json_cikar
    v = json_cikar(metin)
    return v if isinstance(v, dict) else None


def bolum_sec(soru: str) -> str:
    """Soru metnine göre kalıcı ayrım: üçte biri sınav (eğitime hiç girmez)."""
    return "sinav" if int(hashlib.md5(soru.strip().encode("utf-8")).hexdigest(), 16) % 3 == 0 else "egitim"


@dataclass
class DamitmaRaporu:
    soru: int = 0
    gecen_cevap: int = 0
    ornek: dict[str, int] = field(default_factory=dict)
    atilan: dict[str, int] = field(default_factory=dict)
    yazi: int = 0
    sure_sn: float = 0.0
    cagri: dict[str, dict] = field(default_factory=dict)     # görev → {n, sure, belirtec, kesik, bozuk}

    def say(self, sozluk: dict, anahtar: str, n: int = 1) -> None:
        sozluk[anahtar] = sozluk.get(anahtar, 0) + n

    def cagri_say(self, k: "Cagri", bozuk: bool) -> None:
        d = self.cagri.setdefault(k.gorev, {"n": 0, "sure": 0.0, "belirtec": 0, "kesik": 0, "bozuk": 0})
        d["n"] += 1
        d["sure"] = round(d["sure"] + k.sure, 1)
        d["belirtec"] += k.belirtec
        d["kesik"] += k.bitis == "length"
        d["bozuk"] += bozuk

    def ozet(self) -> str:
        ornek = ", ".join(f"{k} {v}" for k, v in sorted(self.ornek.items()))
        atilan = ", ".join(f"{k} {v}" for k, v in sorted(self.atilan.items()))
        return (f"{self.soru} soru işlendi, {self.gecen_cevap} cevap sınamadan geçti, {self.yazi} resmî yazı; "
                f"örnekler: {ornek or '—'}; atılan: {atilan or '—'}; {self.sure_sn / 60:.0f} dk")


class Damitici:
    """Öğretmenle veri üretir. s: hat, kutuphane, dersler (ve GeceZekaCalismasi için yz/ayarlar) taşıyan nesne."""

    def __init__(self, s, ogretmen: OgretmenModeli, cikti: Path, bildir=None):
        self.s, self.ogretmen = s, ogretmen
        self.cikti = Path(cikti)
        self.cikti.mkdir(parents=True, exist_ok=True)
        self.bildir = bildir or (lambda m: log.info(m))
        self.rapor = DamitmaRaporu()
        self._yaz_kilit = threading.Lock()
        self.ornek_dosyasi = self.cikti / "ornekler.jsonl"
        self.atilan_dosyasi = self.cikti / "atilan_ornekler.jsonl"   # tanılama: her nedenden ilk birkaç çağrı
        self._atilan_sayac: dict[str, int] = {}
        self.sinav_dosyasi = self.cikti / "sinav.jsonl"
        self.islenen = self._islenenler()
        from .oz_gelisim import SEMA as SENTETIK_SEMA
        with s.kutuphane._kilit, s.kutuphane.db:
            s.kutuphane.db.executescript(SENTETIK_SEMA)
        self._yerel = threading.local()
        self._dogrulamayi_izle()

    def _dogrulamayi_izle(self) -> None:
        """Programın sınamasını sarar: bir soru işlenirken (iş parçacığına özgü) sınamada çıkarılan bütün cümleler
        toplanır. Hat aynı cevabı birkaç kez sınar ve her seferinde denetim kaydını yeniler; öğretmenin hangi
        cümlesinin geçmediği ancak böyle bilinir."""
        d = getattr(self.s.hat, "dogrulama", None)
        if d is None or getattr(d, "_damitma_izleniyor", False):
            return
        asil, yerel = d.dogrula, self._yerel

        def izlenen(cevap):
            sonuc = asil(cevap)
            toplanan = getattr(yerel, "cikan", None)
            if toplanan is not None:
                toplanan.update(_cumle_anahtari(x.get("metin", ""))
                                for x in (getattr(cevap, "denetim", None) or {}).get("cikarilanlar", []))
            return sonuc

        d.dogrula = izlenen
        d._damitma_izleniyor = True

    # ------------------------------------------------------------------ kayıt
    def _islenenler(self) -> set[str]:
        """Kaldığı yerden sürdürme: daha önce işlenmiş soru kimlikleri."""
        islenen = set()
        for dosya in (self.cikti / "islenen.txt",):
            if dosya.is_file():
                islenen.update(x.strip() for x in dosya.read_text("utf-8").splitlines() if x.strip())
        return islenen

    def _yaz(self, kayitlar: list[dict], soru_id: str = "", sinav: dict | None = None) -> None:
        with self._yaz_kilit:
            with self.ornek_dosyasi.open("a", encoding="utf-8") as f:
                for k in kayitlar:
                    f.write(json.dumps(k, ensure_ascii=False) + "\n")
                    self.rapor.say(self.rapor.ornek, k["gorev"])
            if sinav:
                with self.sinav_dosyasi.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(sinav, ensure_ascii=False) + "\n")
            if soru_id:
                with (self.cikti / "islenen.txt").open("a", encoding="utf-8") as f:
                    f.write(soru_id + "\n")
                self.islenen.add(soru_id)

    @staticmethod
    def _ornek(c: Cagri, bolum: str, soru_id: str) -> dict:
        cevap = c.cevap
        v = _json_gecerli(cevap) if c.json else None
        if v is not None:                    # JSON sıkıştırılır: öğrenci boşluksuz yazar, CPU'da daha az belirteç
            cevap = json.dumps(_isaretsiz(v), ensure_ascii=False)
        return {"gorev": c.gorev, "messages": c.mesajlar, "cevap": cevap, "json": c.json, "bolum": bolum,
                "soru_id": soru_id}

    # ------------------------------------------------------------------ 1 çalışma soruları
    def sorular_uret(self, sinir: int, bitis: float) -> int:
        """Programın kendi soru üretme yordamı (GeceZekaCalismasi) öğretmenle çalışır; geçerli soru üreten çağrılar
        "soru" görevinin eğitim örneği olur."""
        from .oz_gelisim import GeceZekaCalismasi
        gz = GeceZekaCalismasi(self.s, self.bildir)
        eski_model = self.s.hat.model
        self.s.hat.model = self.ogretmen
        once = self._sentetik_sayisi()
        try:
            with self.ogretmen.kayit() as kayit:
                gz.sentetik_uret(sinir, bitis)
        finally:
            self.s.hat.model = eski_model
        uretilen = self._sentetik_sayisi() - once
        ornekler = []
        for c in kayit:
            v = _json_gecerli(c.cevap)
            sorular = [str(q.get("soru", "")).strip() for q in (v or {}).get("sorular", []) if isinstance(q, dict)]
            if c.gorev == "soru" and sorular and all(15 <= len(q) <= 300 for q in sorular):
                ornekler.append(self._ornek(c, "egitim", ""))
            else:
                self.rapor.say(self.rapor.atilan, "soru")
        self._yaz(ornekler)
        self.bildir(f"Çalışma sorusu: {uretilen} geçerli soru üretildi ({len(ornekler)} örnek)")
        return uretilen

    def _sentetik_sayisi(self) -> int:
        try:
            return self.s.kutuphane.db.execute("SELECT COUNT(*) FROM yz_sentetik WHERE durum='dogrulandi'").fetchone()[0]
        except Exception:  # noqa: BLE001
            return 0

    def soru_havuzu(self, ek_sorular: list[dict] | None = None) -> list[dict]:
        """İşlenmemiş sorular: programın ürettiği doğrulanmış çalışma soruları + (varsa) kullanıcı paketindeki
        gerçek sorular ve altın set."""
        havuz = []
        for r in self.s.kutuphane.db.execute(
                "SELECT id, soru, dayanak FROM yz_sentetik WHERE durum='dogrulandi' ORDER BY id").fetchall():
            havuz.append({"id": f"s{r['id']}", "soru": r["soru"], "dayanak": json.loads(r["dayanak"] or "[]")})
        for i, e in enumerate(ek_sorular or []):
            havuz.append({"id": e.get("id") or f"k{i}", "soru": e["soru"], "dayanak": e.get("dayanak", [])})
        return [h for h in havuz if h["id"] not in self.islenen]

    # ------------------------------------------------------------------ 2 danışma akışı
    def soru_isle(self, h: dict) -> None:
        """Bir soruyu programın danışma hattında öğretmenle cevaplar, çağrıları sınar ve kaydeder."""
        from ..ogrenme.degerlendirme import altin_sonucu
        bolum = bolum_sec(h["soru"])
        self._yerel.cikan = set()
        try:
            with self.ogretmen.kayit() as kayit:
                c = self.s.hat.cevapla(h["soru"], "derin", kayit=False)
        except Exception as e:  # noqa: BLE001
            self.rapor.say(self.rapor.atilan, "hata")
            log.warning("Soru işlenemedi: %s", e)
            self._yaz([], h["id"])
            return
        finally:
            cikan, self._yerel.cikan = self._yerel.cikan, None
        self.rapor.soru += 1
        sinav = {"soru": h["soru"], "beklenen_dayanak": h["dayanak"], "id": h["id"]} if bolum == "sinav" else None
        if bolum == "sinav":                          # sınav sorusunun hiçbir çağrısı eğitime girmez
            self._yaz([], h["id"], sinav)
            return
        gecti, _kritik = altin_sonucu(c, h["dayanak"], "")
        den = c.denetim or {}
        temiz = (c.durum.value == "Doğrulandı" and gecti and not den.get("alintiya_donus")
                 and not den.get("dogruluk_cikarilan") and not den.get("somutluk_cikarilan"))
        bulunan = {f"{k.pasaj.belge_kimlik}/{k.pasaj.madde_no}" for k in c.kaynaklar} | {
            k.pasaj.belge_kimlik for k in c.kaynaklar}
        dayanak_yok = bool(h["dayanak"]) and not any(d in bulunan for d in h["dayanak"])
        celiskili = c.durum.value == "Çelişkili"
        ornekler, hatalar = [], []
        # Sentez ve düzeltme: öğretmenin cevabından sınamada çıkarılan cümleler atılır (kalan her cümle doğrulanmış);
        # sonuç bölümü ayakta kalan ve cümlelerinin çoğu geçen cevap örnek olur. Sentez istemine, aynı kaynaklarla
        # yazılmış en son geçerli düzeltme hedef olarak verilir (öğrenci düzeltilmiş cevabı doğrudan yazmayı öğrenir).
        gecerli: dict[int, dict] = {}
        for i, k in enumerate(kayit):
            if k.gorev not in ("sentez", "duzeltme"):
                continue
            v = _json_gecerli(k.cevap)
            if v is None:
                continue
            durust_yok = (dayanak_yok and v.get("guven") == "hukum_yok"
                          and (v.get("dogrudan_cevap") is False or not v.get("kisa_cevap")))
            temiz_v, toplam, atilan = dogrulanmis_taslak(v, cikan)
            if durust_yok and not atilan:
                gecerli[i] = v
            elif (not dayanak_yok and not celiskili and v.get("dogrudan_cevap") is not False
                  and temiz_v.get("kisa_cevap") and toplam and atilan <= 0.4 * toplam):
                gecerli[i] = temiz_v
        son_duzeltme = max((i for i in gecerli if kayit[i].gorev == "duzeltme"), default=None)
        for i, k in enumerate(kayit):
            v = _json_gecerli(k.cevap) if k.json else None
            with self._yaz_kilit:
                self.rapor.cagri_say(k, bool(k.json and v is None))
            if k.json and v is None:
                self.rapor.say(self.rapor.atilan, f"{k.gorev}:bozuk")
                self._atilan_yaz(k, "bozuk")
                continue
            hedef = None
            if k.gorev == "cozumleme":
                ok = bool(v and v.get("personel_turu") and isinstance(v.get("alt_sorular", []), list))
            elif k.gorev in ("sentez", "duzeltme"):
                if (k.gorev == "sentez" and son_duzeltme is not None and son_duzeltme > i
                        and _kaynak_satirlari(kayit[son_duzeltme]) == _kaynak_satirlari(k)):
                    hedef = gecerli[son_duzeltme]
                else:
                    hedef = gecerli.get(i)
                ok = hedef is not None
            elif k.gorev == "elestiri":
                ok = temiz or bool(v and v.get("sorunlar"))      # gerçek sorun bulan eleştiri de değerli
            else:
                ok = False
            if ok:
                o = self._ornek(k, bolum, h["id"])
                if hedef is not None:
                    o["cevap"] = json.dumps(_isaretsiz(hedef), ensure_ascii=False)
                    if _json_gecerli(o["cevap"]) != _isaretsiz(v):
                        o["duzenlendi"] = True
                        self.rapor.say(self.rapor.ornek, f"{k.gorev}:ayiklanmis")
                ornekler.append(o)
            else:
                self.rapor.say(self.rapor.atilan, k.gorev)
                self._atilan_yaz(k, "sinama" if k.gorev in ("sentez", "duzeltme", "elestiri") else "gecersiz",
                                 {"durum": c.durum.value, "altin": gecti, "dayanak_yok": dayanak_yok,
                                  "alintiya": bool(den.get("alintiya_donus")), "cikan_cumle": len(cikan),
                                  "dogrudan": (v or {}).get("dogrudan_cevap"),
                                  "kisa_cevap": len((v or {}).get("kisa_cevap") or [])})
        for x in den.get("cikarilanlar", [])[:8]:
            hatalar.append(f"[{x.get('test', '')}] {x.get('metin', '')[:160]} — {x.get('neden', '')[:120]}")
        if temiz:
            self.rapor.gecen_cevap += 1
        if hatalar:
            ornekler += self._ders_ornekleri(h["soru"], hatalar, bolum, h["id"])
        self._yaz(ornekler, h["id"])

    def _atilan_yaz(self, k: "Cagri", neden: str, ek: dict | None = None, sinir: int = 12) -> None:
        """Atılan çağrının tanılama kaydı (her görev/neden için ilk birkaçı): ham çıktı, bitiş nedeni, süre."""
        anahtar = f"{k.gorev}:{neden}"
        with self._yaz_kilit:
            if self._atilan_sayac.get(anahtar, 0) >= sinir:
                return
            self._atilan_sayac[anahtar] = self._atilan_sayac.get(anahtar, 0) + 1
            son = k.mesajlar[-1].get("content", "") if k.mesajlar else ""
            with self.atilan_dosyasi.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"neden": anahtar, "bitis": k.bitis, "belirtec": k.belirtec, "sure": k.sure,
                                    "dusunce": k.dusunce, "istem_sonu": str(son)[-600:], "ham": k.ham,
                                    "cevap": k.cevap[:1500], **(ek or {})}, ensure_ascii=False) + "\n")

    def _ders_ornekleri(self, soru: str, hatalar: list[str], bolum: str, soru_id: str) -> list[dict]:
        """Öğretmen, sınamada çıkarılan cümlelerden yöntem dersi çıkarır; çekirdeğin ders süzgecinden geçen
        (sayı/madde içermeyen, ilkeyi zayıflatmayan) dersler örnek olur."""
        from ..cekirdek.dersler import ders_gecerli_mi
        with self.ogretmen.kayit() as kayit:
            try:
                self.s.dersler.hatadan_cikar(self.ogretmen, soru, hatalar, kaynak="damitma")
            except Exception:  # noqa: BLE001
                return []
        cikti = []
        for k in kayit:
            v = _json_gecerli(k.cevap) or {}
            dersler = [d for d in v.get("dersler", []) if isinstance(d, dict)]
            if k.gorev == "ders" and dersler and all(ders_gecerli_mi(str(d.get("ders", "")))[0] for d in dersler):
                cikti.append(self._ornek(k, bolum, soru_id))
            else:
                self.rapor.say(self.rapor.atilan, "ders")
        return cikti

    def sorulari_isle(self, havuz: list[dict], bitis: float, paralel: int = 4) -> None:
        bas = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, paralel)) as ex:
            bekleyen = set()
            sira = iter(havuz)
            for _ in range(paralel * 2):
                h = next(sira, None)
                if h is None:
                    break
                bekleyen.add(ex.submit(self.soru_isle, h))
            while bekleyen:
                bitti = next(as_completed(bekleyen))
                bekleyen.discard(bitti)
                if self.rapor.soru and self.rapor.soru % 20 == 0:
                    self.bildir(f"{self.rapor.ozet()} (geçen süre {(time.monotonic() - bas) / 60:.0f} dk)")
                if time.monotonic() < bitis:
                    h = next(sira, None)
                    if h is not None:
                        bekleyen.add(ex.submit(self.soru_isle, h))

    # ------------------------------------------------------------------ 3 resmî yazı
    def yazilar_uret(self, sinir: int, bitis: float, profil: dict | None = None) -> int:
        """Öğretmen kurgu bir gelen yazı ve birimin cevabını yazar; program yazı akışını öğretmenle çalıştırır.
        Sınamadan ve kontrol listesinden hatasız geçen yazının model çağrısı örnek olur."""
        from ..yazi.gelen import cozumle
        from ..yazi.hazirlayici import YaziHazirlayici, YaziIstegi
        profil = profil or {"idare": "TOKAT GAZİOSMANPAŞA ÜNİVERSİTESİ", "birim": "Personel Daire Başkanlığı",
                            "imza_ad": "Ad", "imza_soyad": "Soyad", "imza_unvan": "Daire Başkanı"}
        satirlar = self.s.kutuphane.db.execute(
            "SELECT m.madde_no, m.baslik, m.metin, b.baslik AS belge FROM maddeler m JOIN belgeler b ON b.id=m.belge_id"
            " WHERE m.yururluk_bitis IS NULL AND m.mulga=0 AND length(m.metin) > 80 ORDER BY RANDOM() LIMIT ?",
            (sinir,)).fetchall()
        eski_model = self.s.hat.model
        self.s.hat.model = self.ogretmen
        h = YaziHazirlayici(self.s.hat, self.s.dersler)
        n = 0
        try:
            for r in satirlar:
                if time.monotonic() > bitis:
                    break
                try:
                    ham = self.ogretmen.sohbet(
                        [{"role": "system", "content": sistem_cekirdegi(GELEN_YAZI_GOREVI)},
                         {"role": "user", "content": f"{r['belge']} — madde {r['madde_no']} {r['baslik'] or ''}\n"
                                                     f"{r['metin'][:1800]}"}],
                        max_tokens=900, sicaklik=0.7, json_sema=GELEN_YAZI_SEMASI)
                    v = _json_gecerli(ham) or {}
                    if len(str(v.get("gelen_yazi", ""))) < 200 or not str(v.get("talimat", "")).strip():
                        self.rapor.say(self.rapor.atilan, "gelen_yazi")
                        self._atilan_yaz(Cagri("ogretmen", [], ham, True), "gelen_yazi")
                        continue
                    gelen = cozumle(str(v["gelen_yazi"]))
                    tur = v.get("tur") if v.get("tur") in ("cevap", "gorus", "bilgi_isteme", "talep") else "cevap"
                    with self.ogretmen.kayit() as kayit:
                        sonuc = h.hazirla(YaziIstegi(tur=tur, talimat=str(v["talimat"]), gelen=gelen, profil=profil))
                except Exception as e:  # noqa: BLE001
                    self.rapor.say(self.rapor.atilan, "yazi:hata")
                    log.warning("Yazı örneği üretilemedi: %s", e)
                    continue
                kimlik = "y" + hashlib.md5(str(v.get("gelen_yazi", "")).encode("utf-8")).hexdigest()[:10]
                bolum = bolum_sec(str(v.get("gelen_yazi", "")))
                temiz = sonuc.model_kullanildi and not sonuc.cikarilanlar and sonuc.hata_sayisi == 0
                ornekler = []
                for k in kayit:
                    with self._yaz_kilit:
                        self.rapor.cagri_say(k, bool(k.json and _json_gecerli(k.cevap) is None))
                    if k.gorev in ("yazi", "yazi_duzeltme") and not temiz:
                        self._atilan_yaz(k, "yazi", {"model": sonuc.model_kullanildi, "hata": sonuc.hata_sayisi,
                                                     "cikarilan": [str(x)[:200] for x in sonuc.cikarilanlar][:5]})
                    if k.gorev in ("yazi", "yazi_duzeltme") and temiz and bolum == "egitim":
                        ornekler.append(self._ornek(k, bolum, kimlik))
                    elif k.gorev in ("cozumleme",) and bolum == "egitim" and _json_gecerli(k.cevap):
                        ornekler.append(self._ornek(k, bolum, kimlik))
                    elif k.gorev in ("yazi", "yazi_duzeltme"):
                        self.rapor.say(self.rapor.atilan, "yazi")
                self._yaz(ornekler)
                n += int(temiz)
                self.rapor.yazi += int(temiz)
        finally:
            self.s.hat.model = eski_model
        return n

    # ------------------------------------------------------------------ hepsi
    def calistir(self, sure_dk: float, soru_hedefi: int = 4000, yazi_orani: float = 0.15, paralel: int = 4,
                 ek_sorular: list[dict] | None = None, profil: dict | None = None) -> DamitmaRaporu:
        bas = time.monotonic()
        bitis = bas + sure_dk * 60
        eski_model = self.s.hat.model
        self.s.hat.model = self.ogretmen                # programın bütün yordamları öğretmenle çalışır
        try:
            return self._calistir(bas, bitis, soru_hedefi, yazi_orani, paralel, ek_sorular, profil)
        finally:
            self.s.hat.model = eski_model

    def _calistir(self, bas, bitis, soru_hedefi, yazi_orani, paralel, ek_sorular, profil) -> DamitmaRaporu:
        havuz = self.soru_havuzu(ek_sorular)
        if len(havuz) < soru_hedefi:
            self.bildir(f"Çalışma soruları üretiliyor ({len(havuz)} hazır, hedef {soru_hedefi})")
            pay = bas + (bitis - bas) * 0.25         # sürenin en çok dörtte biri soru üretimine
            self.sorular_uret(max(0, soru_hedefi - len(havuz)) // 2 + 1, pay)
            havuz = self.soru_havuzu(ek_sorular)
        yazi_bitis = bitis - (bitis - time.monotonic()) * yazi_orani
        self.bildir(f"{len(havuz)} soru öğretmenle cevaplanıyor (paralel {paralel})")
        self.sorulari_isle(havuz[:soru_hedefi], yazi_bitis, paralel)
        if yazi_orani > 0 and time.monotonic() < bitis:
            self.bildir("Resmî yazı örnekleri üretiliyor")
            self.yazilar_uret(400, bitis, profil)
        self.rapor.sure_sn = time.monotonic() - bas
        (self.cikti / "rapor.json").write_text(json.dumps(self.rapor.__dict__, ensure_ascii=False, indent=1), "utf-8")
        self.bildir("Damıtma bitti: " + self.rapor.ozet())
        return self.rapor


# ---------------------------------------------------------------------------- eğitim verisi hazırlama
GOREV_PAYLARI = {"sentez": 0.32, "cozumleme": 0.16, "elestiri": 0.10, "duzeltme": 0.10, "yazi": 0.12,
                 "yazi_duzeltme": 0.03, "soru": 0.08, "ders": 0.06, "diger": 0.0, "ogretmen": 0.0}


def ornekleri_oku(dosyalar: list[Path]) -> list[dict]:
    """Örnek dosyalarını okur; yinelenenleri (aynı istem) ve eğitim dışı görevleri ayıklar."""
    gorulen, cikti = set(), []
    for d in dosyalar:
        if not Path(d).is_file():
            continue
        for satir in Path(d).read_text("utf-8").splitlines():
            try:
                o = json.loads(satir)
            except ValueError:
                continue
            if o.get("bolum") != "egitim" or GOREV_PAYLARI.get(o.get("gorev"), 0) <= 0 or not o.get("cevap"):
                continue
            anahtar = hashlib.md5((json.dumps(o["messages"], ensure_ascii=False) + o["cevap"]).encode()).hexdigest()
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            cikti.append(o)
    return cikti


def dengele(ornekler: list[dict], toplam: int | None = None, tohum: int = 3407) -> list[dict]:
    """Görev paylarına göre dengeler: bir görev baskın olup diğer yordamları unutturmasın."""
    import random
    rnd = random.Random(tohum)
    gruplar: dict[str, list[dict]] = {}
    for o in ornekler:
        gruplar.setdefault(o["gorev"], []).append(o)
    toplam = toplam or len(ornekler)
    secilen = []
    for gorev, liste in gruplar.items():
        rnd.shuffle(liste)
        hedef = max(1, int(round(toplam * GOREV_PAYLARI.get(gorev, 0))))
        secilen += liste[:hedef] if len(liste) > hedef else liste
    rnd.shuffle(secilen)
    return secilen


def egitim_metinleri(ornekler: list[dict], sablon, uzunluk, en_cok_belirtec: int) -> tuple[list[dict], int]:
    """İstem + cevap çiftleri. sablon(messages) → modelin çalışırken gördüğü istem metni (sohbet şablonu,
    düşünme kapalı); uzunluk(metin) → belirteç sayısı. Sınırı aşanlar atılır. ([{prompt, completion}], atılan)"""
    cikti, atilan = [], 0
    for o in ornekler:
        istem = sablon(o["messages"])
        tamam = o["cevap"].strip()
        if uzunluk(istem) + uzunluk(tamam) + 8 > en_cok_belirtec:
            atilan += 1
            continue
        cikti.append({"prompt": istem, "completion": tamam, "gorev": o["gorev"]})
    return cikti, atilan
