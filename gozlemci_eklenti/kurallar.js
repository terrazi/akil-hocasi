/* Akıl Hocası Gözlemci — ortak kurallar.
 * İçerik betiği, arka plan çalışanı ve Node testleri aynı dosyayı kullanır.
 * Kural: yalnızca herkese açık resmî sayfalar okunur; kamu sistemleri, oturum açık sayfalar,
 * formlar ve düğmeler hiçbir koşulda gözlenmez veya tıklanmaz. Uygulama aynı kuralları ayrıca uygular.
 * Listeler uygulamadaki Python listeleriyle testle eşitlenir (tests/test_gozlemci_eklenti.py).
 */
(function (kok) {
  "use strict";

  const BIRINCIL = ["resmigazete.gov.tr", "mevzuat.gov.tr", "gop.edu.tr", "yok.gov.tr", "hmb.gov.tr", "sgk.gov.tr", "sayistay.gov.tr", "danistay.gov.tr", "kik.gov.tr", "kaysis.gov.tr", "kvkk.gov.tr", "csgb.gov.tr", "tccb.gov.tr"];
  const IKINCIL = ["memurlar.net"];
  const SISTEM_ALANLARI = ["turkiye.gov.tr", "kbs.gov.tr", "muhasebat.gov.tr", "uyap.gov.tr", "kep.tr", "ekap.kik.gov.tr"];
  const SISTEM_ANAHTARLARI = ["ebys", "envision", "obs", "pbs", "hys", "mys", "kbs", "hitap", "ekap", "edevlet", "giris", "login", "portal", "oturum", "webmail", "mail", "sso", "cas", "auth", "uyap", "kep", "bank", "bordro", "intranet"];
  const ISTISNALAR = ["ebysyardim.gop.edu.tr"];
  const SISTEM_YOLLARI = /\/(?:login|giris|oturum|signin|sign-in|account|hesabim|auth|sso)(?:\/|$|\?)/i;

  const DOSYA_UZANTILARI = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods"];
  const ATLA_UZANTILARI = /\.(?:jpe?g|png|gif|webp|svg|ico|bmp|tiff?|mp[34]|avi|mov|wmv|webm|zip|rar|7z|exe|msi|apk|iso|css|js|json|xml|rss|ics|pptx?)(?:$|\?)/i;
  // Riskli eylem bağlantıları (v6 eklentisindeki NAV_DENY/BLOCK_WORDS mantığı): asla izlenmez
  const RISKLI_YOL = /(?:logout|log-out|signout|sign-out|cikis|çıkış|oturumu?-?kapat|delete|sil(?:me)?(?:\/|$|\?|=)|remove|kaldir|onayla|approve|submit|gonder|kaydet|save|update|guncelle|odeme|payment|basvur|apply|sepet|cart|yazdir|print|share|paylas|wp-admin|admin|panel|mailto:|tel:|javascript:)/i;
  const RISKLI_METIN = /^(?:çıkış|çıkış yap|oturumu kapat|logout|sign out|sil|kaldır|onayla|gönder|kaydet|başvur|öde|yazdır|paylaş)$/i;
  const OTURUM_METNI = /(?:çıkış yap|oturumu kapat|oturumu sonlandır|log ?out|sign ?out|hesabım|profilim)/i;
  const OTURUM_YOLU = /(?:logout|signout|cikis|oturumkapat|oturum-kapat)/i;
  const IZLEME_PARAMETRELERI = /^(?:utm_[a-z]+|fbclid|gclid|yclid|mc_[a-z]+|_ga|ref|share)$/i;

  const HIZ = { yavas: { bekle: 6000, sapma: 2000 }, normal: { bekle: 3000, sapma: 1200 }, hizli: { bekle: 1500, sapma: 600 } };

  let kurallar = { birincil: BIRINCIL, ikincil: IKINCIL, sistem_alanlari: SISTEM_ALANLARI, sistem_anahtarlari: SISTEM_ANAHTARLARI, istisnalar: ISTISNALAR };

  /** Uygulamadan gelen kurallar yalnızca daraltabilir: yerleşik engeller her zaman geçerlidir. */
  function kurallariGuncelle(durum) {
    if (!durum || typeof durum !== "object") return kurallar;
    const dizi = (x) => (Array.isArray(x) ? x.filter((v) => typeof v === "string").map((v) => v.toLowerCase()) : []);
    const birlesik = (a, b) => Array.from(new Set([...a, ...b]));
    const birincil = dizi(durum.birincil).length ? dizi(durum.birincil).filter((d) => BIRINCIL.includes(d)) : BIRINCIL;
    const ikincil = dizi(durum.ikincil).length ? dizi(durum.ikincil).filter((d) => IKINCIL.includes(d)) : IKINCIL;
    kurallar = {
      birincil,
      ikincil,
      sistem_alanlari: birlesik(SISTEM_ALANLARI, dizi(durum.sistem_alanlari)),
      sistem_anahtarlari: birlesik(SISTEM_ANAHTARLARI, dizi(durum.sistem_anahtarlari)),
      istisnalar: dizi(durum.istisnalar).filter((d) => ISTISNALAR.includes(d)),
    };
    return kurallar;
  }

  function urlAyristir(adres) {
    try { return new URL(adres); } catch (_) { return null; }
  }

  function host(adres) {
    const u = urlAyristir(adres);
    return u ? u.hostname.toLowerCase() : "";
  }

  function eslesir(h, liste) {
    return liste.some((b) => h === b || h.endsWith("." + b));
  }

  function birincilMi(adres) { return eslesir(host(adres), kurallar.birincil); }
  function ikincilMi(adres) { return eslesir(host(adres), kurallar.ikincil); }
  function kapsamdaMi(adres) {
    const u = urlAyristir(adres);
    return !!u && (u.protocol === "https:" || u.protocol === "http:") && (birincilMi(adres) || ikincilMi(adres));
  }

  /** Kamu sistemi veya oturumlu uygulama mı? Şüphede "evet" döner (güvenli taraf). */
  function sistemMi(adres) {
    const u = urlAyristir(adres);
    if (!u) return true;
    const h = u.hostname.toLowerCase();
    if (kurallar.istisnalar.includes(h)) return false;
    if (eslesir(h, kurallar.sistem_alanlari)) return true;
    const etiketler = h.split(".").slice(0, -2);
    for (const e of etiketler) {
      for (const k of kurallar.sistem_anahtarlari) {
        if (e === k || e.startsWith(k + "-") || e.endsWith("-" + k)) return true;
      }
    }
    return SISTEM_YOLLARI.test(u.pathname || "/");
  }

  function dosyaMi(adres) {
    const u = urlAyristir(adres);
    if (!u) return false;
    const yol = u.pathname.toLowerCase();
    return DOSYA_UZANTILARI.some((x) => yol.endsWith(x));
  }

  /** Adresi sadeleştirir: #parça ve izleme parametreleri atılır; http(s) dışı adresler null. */
  function adresSadelestir(href, taban) {
    let u;
    try { u = new URL(href, taban); } catch (_) { return null; }
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    u.hash = "";
    for (const ad of Array.from(u.searchParams.keys())) {
      if (IZLEME_PARAMETRELERI.test(ad)) u.searchParams.delete(ad);
    }
    return u.toString();
  }

  function riskliBaglanti(adres, metin) {
    return RISKLI_YOL.test(adres || "") || RISKLI_METIN.test((metin || "").trim());
  }

  /** Sayfada oturum açık olduğunu gösteren çıkış/hesap bağlantısı var mı? */
  function oturumIsareti(baglantilar) {
    return (baglantilar || []).some((b) => OTURUM_METNI.test(b.metin || "") || OTURUM_YOLU.test(b.url || ""));
  }

  /** TC kimlik, IBAN, kart numarası ve cep telefonunu maskeler (kurumsal e-posta ve sabit hat kalır). */
  function maskele(metin) {
    return String(metin || "")
      .replace(/\bTR\d{2}(?:[ ]?[A-Z0-9]){22}\b/gi, (m) => m.slice(0, 4) + " **** **** **** **** ** " + m.replace(/\s/g, "").slice(-2))
      .replace(/(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)/g, "[KART NO]")
      .replace(/(?<!\d)[1-9]\d{10}(?!\d)/g, (m) => m.slice(0, 3) + "******" + m.slice(-2))
      .replace(/(?<!\d)(?:\+?90[\s.-]?|0)?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)/g, "[CEP TELEFONU]");
  }

  /** Aynı şablondaki sayfaları gruplamak için yol kalıbı: sayılar ve sorgu değerleri yer tutucu olur. */
  function yolKalibi(adres) {
    const u = urlAyristir(adres);
    if (!u) return "";
    const yol = u.pathname.split("/").map((p) => (/^\d+$/.test(p) ? ":n" : /\d{3,}/.test(p) ? ":id" : p.toLowerCase())).join("/");
    const sorgu = Array.from(u.searchParams.keys()).sort().map((k) => k.toLowerCase() + "=*").join("&");
    return u.hostname.toLowerCase() + yol + (sorgu ? "?" + sorgu : "");
  }

  /** Yapı benzerliği (v6'daki screenSimilarity'nin Jaccard kısmı). */
  function benzerlik(a, b) {
    const A = new Set(a || []), B = new Set(b || []);
    if (!A.size && !B.size) return 1;
    let kesisim = 0;
    for (const x of A) if (B.has(x)) kesisim++;
    return kesisim / (A.size + B.size - kesisim);
  }

  /** Aynı kalıpta ve yapıca çok benzer sayfalar yeterince görüldüyse bağlantıları yeniden açılmaz. */
  function genisletilsinMi(imza, kalip, gecmis, esik = 0.9, sinir = 5) {
    let benzer = 0;
    for (const g of gecmis || []) {
      if (g.kalip === kalip && benzerlik(g.imza, imza) >= esik) benzer++;
      if (benzer >= sinir) return false;
    }
    return true;
  }

  /** robots.txt: "*" ve "AkilHocasi" için Allow/Disallow önekleri. */
  function robotsAyristir(metin) {
    const gruplar = [];
    let grup = null, sonAjan = false;
    for (const satir0 of String(metin || "").split(/\r?\n/)) {
      const satir = satir0.replace(/#.*$/, "").trim();
      const m = /^([A-Za-z-]+)\s*:\s*(.*)$/.exec(satir);
      if (!m) continue;
      const alan = m[1].toLowerCase(), deger = m[2].trim();
      if (alan === "user-agent") {
        if (!sonAjan) { grup = { ajanlar: [], kurallar: [] }; gruplar.push(grup); }
        grup.ajanlar.push(deger.toLowerCase());
        sonAjan = true;
      } else {
        sonAjan = false;
        if (grup && (alan === "allow" || alan === "disallow")) grup.kurallar.push({ izin: alan === "allow", onek: deger });
      }
    }
    const ozel = gruplar.filter((g) => g.ajanlar.some((a) => a.includes("akilhocasi")));
    const secilen = ozel.length ? ozel : gruplar.filter((g) => g.ajanlar.includes("*"));
    return secilen.flatMap((g) => g.kurallar).filter((k) => k.onek !== "" || !k.izin);
  }

  function robotsIzinli(kurallarListesi, yol) {
    let enUzun = -1, izin = true;
    for (const k of kurallarListesi || []) {
      if (k.onek === "") continue;                       // "Disallow:" boş = her şey serbest
      const desen = new RegExp("^" + k.onek.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\\\$$/, "$"));
      if (desen.test(yol) && (k.onek.length > enUzun || (k.onek.length === enUzun && k.izin))) {
        enUzun = k.onek.length;
        izin = k.izin;
      }
    }
    return izin;
  }

  const ATLA_ETIKETLER = new Set(["NAV", "HEADER", "FOOTER", "ASIDE", "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "FORM", "IFRAME", "SVG", "CANVAS", "BUTTON", "SELECT", "INPUT", "TEXTAREA", "OBJECT", "VIDEO", "AUDIO"]);
  const BLOK_ETIKETLER = new Set(["P", "DIV", "SECTION", "ARTICLE", "MAIN", "LI", "UL", "OL", "TR", "TABLE", "TBODY", "THEAD", "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "PRE", "DL", "DT", "DD", "FIGCAPTION", "HR", "ADDRESS", "CENTER"]);
  const ATLA_SINIF = /(?:^|[\s_-])(?:menu|navbar|nav|breadcrumb|cookie|cerez|sidebar|social|sosyal|share|paylas|footer|header|banner|popup|modal)(?:$|[\s_-])/i;

  /** DOM benzeri ağaçtan okunur düz metin çıkarır; menüler, formlar ve gizli öğeler atlanır. */
  function metinCikar(dugum, gizliMi) {
    const parcalar = [];
    const yuru = (d) => {
      if (!d) return;
      if (d.nodeType === 3) { parcalar.push(d.nodeValue || ""); return; }
      if (d.nodeType !== 1) return;
      const etiket = (d.tagName || d.nodeName || "").toUpperCase();
      if (ATLA_ETIKETLER.has(etiket)) return;
      const al = (ad) => (typeof d.getAttribute === "function" ? d.getAttribute(ad) : null);
      if (al("hidden") !== null || al("aria-hidden") === "true" || al("role") === "navigation") return;
      if (ATLA_SINIF.test(al("class") || "") || ATLA_SINIF.test(al("id") || "")) return;
      if (gizliMi && gizliMi(d)) return;
      if (etiket === "BR") { parcalar.push("\n"); return; }
      const blok = BLOK_ETIKETLER.has(etiket);
      if (blok) parcalar.push("\n");
      for (const c of d.childNodes || []) yuru(c);
      if (etiket === "TD" || etiket === "TH") parcalar.push(" | ");
      if (blok) parcalar.push("\n");
    };
    yuru(dugum);
    return parcalar.join("").replace(/[ \t ]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  /** Sayfa yapısı imzası: ilk 5 düzeydeki etiket+ilk sınıf kümesi (en çok 150 öğe). */
  function imzaCikar(dugum) {
    const kume = new Set();
    const yuru = (d, derinlik) => {
      if (!d || d.nodeType !== 1 || derinlik > 5 || kume.size >= 150) return;
      const etiket = (d.tagName || d.nodeName || "").toLowerCase();
      const sinif = ((typeof d.getAttribute === "function" && d.getAttribute("class")) || "").trim().split(/\s+/)[0] || "";
      kume.add(derinlik + ":" + etiket + (sinif ? "." + sinif.toLowerCase() : ""));
      for (const c of d.children || d.childNodes || []) yuru(c, derinlik + 1);
    };
    yuru(dugum, 0);
    return Array.from(kume);
  }

  /** Aktif taramada sıraya alınacak bağlantılar: aynı alan, riskli değil, dosya değil, sistem değil. */
  function taramaBaglantilari(baglantilar, sayfaAdresi, kokHost) {
    const cikti = [];
    const gorulen = new Set();
    for (const b of baglantilar || []) {
      const adres = adresSadelestir(b.url, sayfaAdresi);
      if (!adres || gorulen.has(adres)) continue;
      gorulen.add(adres);
      if (host(adres) !== kokHost) continue;
      if (dosyaMi(adres) || ATLA_UZANTILARI.test(adres)) continue;
      if (riskliBaglanti(adres, b.metin) || sistemMi(adres)) continue;
      cikti.push(adres);
    }
    return cikti;
  }

  function bekleme(hiz) {
    const p = HIZ[hiz] || HIZ.normal;
    return Math.round(p.bekle + (Math.random() * 2 - 1) * p.sapma);
  }

  const AHKurallar = {
    BIRINCIL, IKINCIL, SISTEM_ALANLARI, SISTEM_ANAHTARLARI, ISTISNALAR, DOSYA_UZANTILARI, HIZ,
    kurallariGuncelle, birincilMi, ikincilMi, kapsamdaMi, sistemMi, dosyaMi, adresSadelestir, riskliBaglanti,
    oturumIsareti, maskele, yolKalibi, benzerlik, genisletilsinMi, robotsAyristir, robotsIzinli, metinCikar,
    imzaCikar, taramaBaglantilari, bekleme, host,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = AHKurallar;
  else kok.AHKurallar = AHKurallar;
})(typeof globalThis !== "undefined" ? globalThis : this);
