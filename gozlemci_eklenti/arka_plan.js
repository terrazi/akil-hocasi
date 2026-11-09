/* Akıl Hocası Gözlemci — arka plan çalışanı.
 * Pasif gözlem: kullanıcının gezdiği beyaz listedeki herkese açık resmî sayfaları uygulamaya iletir.
 * Aktif tarama: seçilen resmî sitede arka plan sekmesinde, yalnız aynı alandaki bağlantıları izleyerek
 * okur (tıklama, form, giriş yok); hız profili, robots.txt, yapı benzerliği süzgeci, durdur/devam.
 * Veri yalnızca bu bilgisayardaki Akıl Hocası uygulamasına (127.0.0.1) gider.
 */
"use strict";
importScripts("kurallar.js");
const K = self.AHKurallar;

const VARSAYILAN = { port: 47231, anahtar: "", pasif: true, hiz: "normal", enCokSayfa: 200, enCokDerinlik: 4 };
const ZAMAN_ASIMI = 25000;

// ------------------------------------------------------------------ yardımcılar
let kilit = Promise.resolve();
function sirayla(is) {
  const p = kilit.then(is, is);
  kilit = p.catch(() => {});
  return p;
}

async function ayarlar() {
  const { ayar } = await chrome.storage.local.get("ayar");
  return { ...VARSAYILAN, ...(ayar || {}) };
}

function bugun() {
  return new Date().toLocaleDateString("sv-SE");
}

async function durumGuncelle(degis) {
  return sirayla(async () => {
    const { durum } = await chrome.storage.local.get("durum");
    let d = durum || { baglanti: "bilinmiyor", sayac: {}, gun: bugun() };
    if (d.gun !== bugun()) d = { ...d, gun: bugun(), sayac: {} };
    degis(d);
    await chrome.storage.local.set({ durum: d });
    await rozet();
  });
}

function say(d, anahtar) {
  d.sayac = d.sayac || {};
  d.sayac[anahtar] = (d.sayac[anahtar] || 0) + 1;
}

async function rozet() {
  const { durum, tarama } = await chrome.storage.local.get(["durum", "tarama"]);
  if (tarama && tarama.durum === "calisiyor") {
    await chrome.action.setBadgeBackgroundColor({ color: "#2563EB" });
    await chrome.action.setBadgeText({ text: String(tarama.sayfa || 0) });
  } else if (!durum || durum.baglanti !== "bagli") {
    await chrome.action.setBadgeBackgroundColor({ color: "#B45309" });
    await chrome.action.setBadgeText({ text: "!" });
  } else {
    const n = (durum.sayac && durum.sayac.kabul) || 0;
    await chrome.action.setBadgeBackgroundColor({ color: "#15803D" });
    await chrome.action.setBadgeText({ text: n ? String(n) : "" });
  }
}

// ------------------------------------------------------------------ uygulama bağlantısı
async function api(yol, govde) {
  const a = await ayarlar();
  if (!a.anahtar) {
    await durumGuncelle((d) => { d.baglanti = "anahtar_yok"; });
    return null;
  }
  try {
    const r = await fetch(`http://127.0.0.1:${a.port}${yol}`, {
      method: govde ? "POST" : "GET",
      headers: { "Content-Type": "application/json", "X-AkilHocasi-Anahtar": a.anahtar },
      body: govde ? JSON.stringify(govde) : undefined,
      cache: "no-store",
    });
    if (r.status === 401) {
      await durumGuncelle((d) => { d.baglanti = "anahtar_hatali"; });
      return null;
    }
    if (!r.ok) {
      await durumGuncelle((d) => { d.baglanti = "bagli"; say(d, "hata"); });
      return null;
    }
    const j = await r.json();
    await durumGuncelle((d) => { d.baglanti = "bagli"; d.sonTemas = Date.now(); if (j.surum) d.surum = j.surum; });
    return j;
  } catch (_) {
    await durumGuncelle((d) => { d.baglanti = "kapali"; });
    return null;
  }
}

async function kurallariYenile() {
  const j = await api("/v1/durum");
  if (j && j.ok) {
    K.kurallariGuncelle(j);
    await chrome.storage.local.set({ kurallar: j, kurallarZamani: Date.now() });
  }
  return j;
}

async function kayitliKurallariYukle() {
  const { kurallar } = await chrome.storage.local.get("kurallar");
  if (kurallar) K.kurallariGuncelle(kurallar);
}
const hazir = kayitliKurallariYukle();

function uygulamayaGidecek(kayit, mod) {
  return { url: kayit.url, baslik: kayit.baslik, metin: kayit.metin, dosyalar: kayit.dosyalar || [], dil: kayit.dil || "", mod };
}

// ------------------------------------------------------------------ gelen sayfalar
chrome.runtime.onMessage.addListener((m, gonderen, yanit) => {
  if (gonderen.id !== chrome.runtime.id || !m || typeof m !== "object") return false;
  if (m.tur === "sayfa" || m.tur === "engel") {
    hazir.then(() => sayfaGeldi(m, gonderen.tab)).catch(() => {});
    return false;
  }
  if (m.tur === "acilir") {
    hazir.then(() => komut(m)).then(yanit, (e) => yanit({ hata: String(e && e.message || e) }));
    return true;
  }
  return false;
});

async function sayfaGeldi(m, sekme) {
  const { tarama } = await chrome.storage.local.get("tarama");
  const taramaSekmesi = !!(tarama && tarama.durum === "calisiyor" && sekme && sekme.id === tarama.tabId);
  if (m.tur === "engel") {
    await durumGuncelle((d) => say(d, "engel"));
    if (taramaSekmesi) await taramaSayfasiBitti(null, null, "engel");
    return;
  }
  const kayit = m.kayit || {};
  if (!K.kapsamdaMi(kayit.url) || K.sistemMi(kayit.url)) return;      // çalışanda da yeniden denetle
  if (taramaSekmesi) {
    const j = await api("/v1/gozlem", uygulamayaGidecek(kayit, "aktif"));
    if (j) await durumGuncelle((d) => say(d, j.karar));
    await taramaSayfasiBitti(kayit, j, j ? j.karar : "hata");
    return;
  }
  const a = await ayarlar();
  if (!a.pasif) return;
  const j = await api("/v1/gozlem", uygulamayaGidecek(kayit, "pasif"));
  if (j) await durumGuncelle((d) => say(d, j.karar));
}

// ------------------------------------------------------------------ aktif tarama
async function taramaOku() {
  const { tarama } = await chrome.storage.local.get("tarama");
  return tarama || null;
}

async function taramaYaz(t) {
  await chrome.storage.local.set({ tarama: t });
  await rozet();
}

async function sekmeyiKapat(t) {
  if (t && t.tabId != null) {
    try { await chrome.tabs.remove(t.tabId); } catch (_) { /* zaten kapalı */ }
    t.tabId = null;
  }
}

async function robotsGetir(koken) {
  try {
    const r = await fetch(koken + "/robots.txt", { cache: "no-store", credentials: "omit" });
    if (r.status >= 400 && r.status < 500) return { kurallar: [], not: "robots.txt yok" };
    if (!r.ok) return { kurallar: [{ izin: false, onek: "/" }], not: "robots.txt alınamadı; tarama yapılmadı" };
    return { kurallar: K.robotsAyristir(await r.text()), not: "" };
  } catch (_) {
    return { kurallar: [{ izin: false, onek: "/" }], not: "robots.txt alınamadı; tarama yapılmadı" };
  }
}

async function taramaBaslat(adres0) {
  const adres = K.adresSadelestir(adres0 || "");
  if (!adres || !K.birincilMi(adres) || K.sistemMi(adres)) {
    return { hata: "Bu adres taranamaz. Yalnız beyaz listedeki herkese açık resmî siteler taranır; kamu sistemleri ve giriş sayfaları taranmaz." };
  }
  const a = await ayarlar();
  if (!a.anahtar) return { hata: "Önce Ayarlar bölümüne Akıl Hocası'ndaki eşleştirme anahtarını girin." };
  const durum = await kurallariYenile();
  if (!durum) return { hata: "Akıl Hocası uygulamasına ulaşılamadı. Uygulamanın açık olduğundan emin olun." };
  if (!K.birincilMi(adres) || K.sistemMi(adres)) return { hata: "Bu adres uygulamanın güncel kurallarına göre taranamaz." };
  const eski = await taramaOku();
  await sekmeyiKapat(eski);
  const robots = await robotsGetir(new URL(adres).origin);
  const t = {
    durum: "calisiyor", kok: adres, kokHost: K.host(adres), baslangic: Date.now(), sonIlerleme: Date.now(),
    kuyruk: [{ url: adres, d: 0 }], gorulen: [adres], gecmis: [], sayfa: 0, sayac: {},
    enCok: Math.max(1, Math.min(5000, Number(a.enCokSayfa) || 200)), enCokDerinlik: Math.max(0, Math.min(10, Number(a.enCokDerinlik) || 4)),
    robots: robots.kurallar, robotsNotu: robots.not, tabId: null, bekleyen: null, neden: "",
  };
  await taramaYaz(t);
  sonrakiSayfa();
  return { ok: true };
}

function bitir(t, neden) {
  t.durum = "bitti";
  t.neden = neden;
  t.bitis = Date.now();
  t.bekleyen = null;
}

function sonrakiSayfa() {
  return sirayla(async () => {
    const t = await taramaOku();
    if (!t || t.durum !== "calisiyor" || t.bekleyen) return;
    let oge = null;
    while (t.kuyruk.length && t.sayfa < t.enCok) {
      const aday = t.kuyruk.shift();
      const u = new URL(aday.url);
      if (K.robotsIzinli(t.robots, u.pathname + u.search) && !K.sistemMi(aday.url)) { oge = aday; break; }
      t.sayac.robots = (t.sayac.robots || 0) + 1;
    }
    if (!oge) {
      bitir(t, t.sayfa >= t.enCok ? "Sayfa sınırına ulaşıldı" : (t.robotsNotu && t.sayfa === 0 ? t.robotsNotu : "Sitedeki erişilebilir sayfalar tamamlandı"));
      await sekmeyiKapat(t);
      await taramaYaz(t);
      return;
    }
    t.bekleyen = { url: oge.url, d: oge.d, zaman: Date.now() };
    let sekme = null;
    if (t.tabId != null) {
      try { sekme = await chrome.tabs.update(t.tabId, { url: oge.url }); } catch (_) { sekme = null; }
    }
    if (!sekme) {
      sekme = await chrome.tabs.create({ url: oge.url, active: false });
      t.tabId = sekme.id;
    }
    await taramaYaz(t);
    setTimeout(zamanAsimiDenetle, ZAMAN_ASIMI + 500);
  });
}

async function taramaSayfasiBitti(kayit, cevap, karar) {
  const ilerle = await sirayla(async () => {
    const t = await taramaOku();
    if (!t || t.durum !== "calisiyor" || !t.bekleyen) return false;     // geç gelen ikinci bildirim
    const derinlik = t.bekleyen.d;
    t.bekleyen = null;
    t.sayfa++;
    t.sonIlerleme = Date.now();
    t.sayac[karar] = (t.sayac[karar] || 0) + 1;
    const { durum } = await chrome.storage.local.get("durum");
    if (karar === "hata" && !cevap && (!durum || durum.baglanti !== "bagli")) {
      t.durum = "duraklatildi";
      t.neden = "Akıl Hocası uygulamasına ulaşılamadı; uygulama açılınca Devam'a basın.";
      t.kuyruk.unshift({ url: (kayit && kayit.url) || t.kok, d: derinlik });
      t.sayfa--;
      await sekmeyiKapat(t);
      await taramaYaz(t);
      return false;
    }
    if (kayit) {
      const kalip = K.yolKalibi(kayit.url);
      if (derinlik < t.enCokDerinlik && K.genisletilsinMi(kayit.imza, kalip, t.gecmis)) {
        const gorulen = new Set(t.gorulen);
        for (const u of K.taramaBaglantilari(kayit.baglantilar, kayit.url, t.kokHost)) {
          if (gorulen.has(u) || t.kuyruk.length >= 3000) continue;
          gorulen.add(u);
          t.kuyruk.push({ url: u, d: derinlik + 1 });
        }
        t.gorulen = Array.from(gorulen).slice(-8000);
      } else if (derinlik < t.enCokDerinlik) {
        t.sayac.benzer = (t.sayac.benzer || 0) + 1;
      }
      t.gecmis.push({ kalip, imza: kayit.imza || [] });
      if (t.gecmis.length > 300) t.gecmis.shift();
    }
    await taramaYaz(t);
    return true;
  });
  if (ilerle) {
    const a = await ayarlar();
    setTimeout(sonrakiSayfa, K.bekleme(a.hiz));
  }
}

async function zamanAsimiDenetle() {
  const gec = await sirayla(async () => {
    const t = await taramaOku();
    if (!t || t.durum !== "calisiyor" || !t.bekleyen || Date.now() - t.bekleyen.zaman < ZAMAN_ASIMI) return false;
    t.bekleyen = null;
    t.sayfa++;
    t.sayac.zamanasimi = (t.sayac.zamanasimi || 0) + 1;
    t.sonIlerleme = Date.now();
    await taramaYaz(t);
    return true;
  });
  if (gec) sonrakiSayfa();
}

chrome.tabs.onRemoved.addListener((sekmeNo) => {
  sirayla(async () => {
    const t = await taramaOku();
    if (t && t.tabId === sekmeNo) {
      t.tabId = null;
      if (t.durum === "calisiyor") {
        t.durum = "duraklatildi";
        t.neden = "Tarama sekmesi kapatıldı. Devam'a basarak sürdürebilirsiniz.";
        if (t.bekleyen) { t.kuyruk.unshift({ url: t.bekleyen.url, d: t.bekleyen.d }); t.bekleyen = null; }
      }
      await taramaYaz(t);
    }
  });
});

// ------------------------------------------------------------------ açılır pencere komutları
async function komut(m) {
  switch (m.komut) {
    case "durum": {
      const { durum, tarama } = await chrome.storage.local.get(["durum", "tarama"]);
      const a = await ayarlar();
      return { durum: durum || {}, tarama: tarama ? { ...tarama, gorulen: undefined, gecmis: undefined, robots: undefined, kuyrukSayisi: tarama.kuyruk.length, kuyruk: undefined } : null, ayar: { ...a, anahtar: a.anahtar ? "ayarlı" : "" } };
    }
    case "sina":
      return { sonuc: await kurallariYenile() };
    case "pasif": {
      const a = await ayarlar();
      await chrome.storage.local.set({ ayar: { ...a, pasif: !!m.acik } });
      return { ok: true };
    }
    case "taramaBaslat":
      return taramaBaslat(m.url);
    case "taramaDuraklat":
      return sirayla(async () => {
        const t = await taramaOku();
        if (!t || t.durum !== "calisiyor") return { ok: true };
        t.durum = "duraklatildi";
        t.neden = "Kullanıcı duraklattı.";
        if (t.bekleyen) { t.kuyruk.unshift({ url: t.bekleyen.url, d: t.bekleyen.d }); t.bekleyen = null; }
        await sekmeyiKapat(t);
        await taramaYaz(t);
        return { ok: true };
      });
    case "taramaDevam": {
      const r = await sirayla(async () => {
        const t = await taramaOku();
        if (!t || t.durum !== "duraklatildi") return { ok: false };
        t.durum = "calisiyor";
        t.neden = "";
        t.sonIlerleme = Date.now();
        await taramaYaz(t);
        return { ok: true };
      });
      if (r.ok) sonrakiSayfa();
      return r;
    }
    case "taramaSifirla":
      return sirayla(async () => {
        const t = await taramaOku();
        await sekmeyiKapat(t);
        await chrome.storage.local.remove("tarama");
        await rozet();
        return { ok: true };
      });
    default:
      return { hata: "bilinmeyen komut" };
  }
}

// ------------------------------------------------------------------ yaşam döngüsü
chrome.runtime.onInstalled.addListener(async (ayrinti) => {
  chrome.alarms.create("nabiz", { periodInMinutes: 1 });
  if (ayrinti.reason === "install") chrome.runtime.openOptionsPage();
  await rozet();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("nabiz", { periodInMinutes: 1 });
  kurallariYenile();
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "nabiz") return;
  await hazir;
  const { kurallarZamani } = await chrome.storage.local.get("kurallarZamani");
  if (!kurallarZamani || Date.now() - kurallarZamani > 30 * 60 * 1000) await kurallariYenile();
  // Çalışan uykudan uyandıysa yarım kalan taramayı sürdür
  const t = await taramaOku();
  if (t && t.durum === "calisiyor") {
    if (t.bekleyen) await zamanAsimiDenetle();
    else if (Date.now() - t.sonIlerleme > 20000) sonrakiSayfa();
  }
});
