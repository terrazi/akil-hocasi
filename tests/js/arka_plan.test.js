// Arka plan çalışanı: sahte Chrome API ile uçtan uca site taraması benzetimi.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const EKLENTI = path.join(__dirname, "..", "..", "gozlemci_eklenti");

function ortamKur({ robots = "User-agent: *\nDisallow: /gizli/\n", uygulamaAcik = true } = {}) {
  const depo = {};
  const dinleyiciler = { mesaj: [], kaldirildi: [], alarm: [], kurulum: [], baslangic: [] };
  const gezintiler = [];
  const gonderilen = [];
  const zamanlayicilar = [];
  let sekmeNo = 0;
  const durum = { uygulamaAcik };

  const chrome = {
    runtime: {
      id: "ext",
      onMessage: { addListener: (f) => dinleyiciler.mesaj.push(f) },
      onInstalled: { addListener: (f) => dinleyiciler.kurulum.push(f) },
      onStartup: { addListener: (f) => dinleyiciler.baslangic.push(f) },
      openOptionsPage: () => {},
    },
    storage: {
      local: {
        get: async (anahtarlar) => {
          const liste = typeof anahtarlar === "string" ? [anahtarlar] : anahtarlar;
          const s = {};
          for (const a of liste) if (a in depo) s[a] = JSON.parse(JSON.stringify(depo[a]));
          return s;
        },
        set: async (o) => { for (const [a, v] of Object.entries(o)) depo[a] = JSON.parse(JSON.stringify(v)); },
        remove: async (a) => { delete depo[a]; },
      },
    },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    alarms: { create: () => {}, onAlarm: { addListener: (f) => dinleyiciler.alarm.push(f) } },
    tabs: {
      create: async ({ url }) => { sekmeNo += 1; gezintiler.push({ sekme: sekmeNo, url }); return { id: sekmeNo, url }; },
      update: async (id, { url }) => { gezintiler.push({ sekme: id, url }); return { id, url }; },
      remove: async (id) => { setImmediate(() => dinleyiciler.kaldirildi.forEach((f) => f(id))); },
      onRemoved: { addListener: (f) => dinleyiciler.kaldirildi.push(f) },
    },
  };

  async function fetchSahte(adres, secenek = {}) {
    const u = new URL(adres);
    const yanit = (kod, govde, metin) => ({ status: kod, ok: kod >= 200 && kod < 300, json: async () => govde, text: async () => metin || "" });
    if (u.pathname === "/robots.txt") return robots === null ? yanit(404, {}) : yanit(200, {}, robots);
    if (u.hostname === "127.0.0.1") {
      if (!durum.uygulamaAcik) throw new TypeError("Failed to fetch");
      if (secenek.headers["X-AkilHocasi-Anahtar"] !== "anahtar") return yanit(401, {});
      if (u.pathname === "/v1/durum") return yanit(200, { ok: true, uygulama: "Akıl Hocası", surum: "0.1.0" });
      if (u.pathname === "/v1/gozlem") {
        const g = JSON.parse(secenek.body);
        gonderilen.push(g);
        return yanit(200, { karar: "kabul", kuyruga_alinan: g.dosyalar.length });
      }
    }
    return yanit(404, {});
  }

  const baglam = {
    chrome, fetch: fetchSahte, console, URL, Date, Math, JSON, Promise, Set, Array, Object, Number, String, RegExp,
    setTimeout: (f, ms) => { zamanlayicilar.push({ f, ms }); return zamanlayicilar.length; },
    clearTimeout: () => {},
  };
  baglam.self = baglam;
  baglam.globalThis = baglam;
  baglam.importScripts = (dosya) => vm.runInContext(fs.readFileSync(path.join(EKLENTI, dosya), "utf8"), baglam, { filename: dosya });
  vm.createContext(baglam);
  vm.runInContext(fs.readFileSync(path.join(EKLENTI, "arka_plan.js"), "utf8"), baglam, { filename: "arka_plan.js" });

  async function bosalt(n = 40) {
    for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r));
  }
  async function zamanlayicilariCalistir() {
    const hepsi = zamanlayicilar.splice(0);
    for (const z of hepsi) z.f();
    await bosalt();
  }
  function mesaj(m, gonderen = { id: "ext" }) {
    return new Promise((cozum) => {
      let yanitlandi = false;
      for (const f of dinleyiciler.mesaj) {
        const asenkron = f(m, gonderen, (y) => { yanitlandi = true; cozum(y); });
        if (!asenkron && !yanitlandi) cozum(undefined);
      }
    });
  }
  const komut = (k, ek = {}) => mesaj({ tur: "acilir", komut: k, ...ek });
  return { depo, gezintiler, gonderilen, zamanlayicilar, durum, dinleyiciler, bosalt, zamanlayicilariCalistir, mesaj, komut };
}

// Benzetilen site: kök sayfa, iki bölüm, 12 duyuru (aynı şablon), riskli ve kapsam dışı bağlantılar
const KOK = "https://kalite.gop.edu.tr/";
const DUYURU_IMZA = ["0:body", "1:div.sablon", "2:div.duyuru", "3:h1", "3:p.tarih"];

function sayfa(adres) {
  const u = new URL(adres);
  const b = (yol, metin = "bağlantı") => ({ url: new URL(yol, KOK).toString(), metin });
  if (u.pathname === "/") {
    return {
      imza: ["0:body", "1:div.anasayfa", "2:ul.liste"],
      baglantilar: [
        b("/formlar", "Formlar"), b("/mevzuat", "Mevzuat"), b("/logout", "Çıkış"), b("/gizli/rapor", "Rapor"),
        b("/depo/form.docx", "TOGÜ.FRM.001"), b("https://ebys.gop.edu.tr/envision", "EBYS"),
        b("https://personel.gop.edu.tr/", "Personel"), b("/giris", "Giriş"),
        ...Array.from({ length: 12 }, (_, i) => b(`/duyuru/${i + 1}`, `Duyuru ${i + 1}`)),
      ],
      dosyalar: [{ url: KOK + "depo/form.docx", metin: "TOGÜ.FRM.001" }],
    };
  }
  if (u.pathname.startsWith("/duyuru/")) {
    const n = Number(u.pathname.split("/")[2]);
    return { imza: DUYURU_IMZA, baglantilar: [b(`/duyuru/${n + 100}`, "İlgili duyuru"), b("/", "Ana sayfa")], dosyalar: [] };
  }
  return { imza: ["0:body", "1:div.bolum", "2:table"], baglantilar: [b("/", "Ana sayfa")], dosyalar: [] };
}

async function sayfayiBildir(o) {
  const son = o.gezintiler[o.gezintiler.length - 1];
  const s = sayfa(son.url);
  await o.mesaj({ tur: "sayfa", kayit: { url: son.url, baslik: "Sayfa", metin: "Metin ".repeat(60), dosyalar: s.dosyalar, baglantilar: s.baglantilar, imza: s.imza } },
    { id: "ext", tab: { id: son.sekme } });
  await o.bosalt();
}

async function taramayiSur(o, adim = 200) {
  for (let i = 0; i < adim; i++) {
    await o.bosalt();
    const t = o.depo.tarama;
    if (!t || t.durum !== "calisiyor") return t;
    if (t.bekleyen) await sayfayiBildir(o);
    else await o.zamanlayicilariCalistir();
  }
  return o.depo.tarama;
}

test("site taraması: güvenli bağlantılar, robots, benzer şablon süzgeci ve bitiş", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar", hiz: "hizli", enCokSayfa: 100, enCokDerinlik: 3 };
  const r = await o.komut("taramaBaslat", { url: KOK });
  assert.equal(r.ok, true);
  const t = await taramayiSur(o);
  assert.equal(t.durum, "bitti", JSON.stringify(t.neden));
  const gidilen = o.gezintiler.map((g) => g.url);
  for (const yasak of ["/logout", "/gizli/", ".docx", "ebys.gop.edu.tr", "personel.gop.edu.tr", "/giris"]) {
    assert.ok(!gidilen.some((u) => u.includes(yasak)), "gidilmemeliydi: " + yasak);
  }
  assert.ok(gidilen.includes(KOK + "formlar") && gidilen.includes(KOK + "mevzuat"));
  // Aynı şablondaki duyurular 5 kez görüldükten sonra bağlantıları açılmaz: 12 duyurunun tamamı değil, ilk 5'in "ilgili" bağlantıları sıraya girer
  const ilgili = gidilen.filter((u) => /\/duyuru\/1\d\d$/.test(u));
  assert.ok(ilgili.length <= 5, "benzer şablon süzgeci: " + ilgili.length);
  assert.ok(t.sayac.benzer >= 1);
  assert.equal(t.sayac.robots, 1);
  assert.ok(o.gonderilen.every((g) => g.mod === "aktif"));
  assert.equal(o.gonderilen[0].dosyalar.length, 1);                 // dosya bağlantısı uygulamaya bildirildi
  assert.ok(o.gonderilen.every((g) => !("baglantilar" in g) && !("imza" in g)));
});

test("sayfa sınırı ve ikinci bildirimin yok sayılması", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar", hiz: "hizli", enCokSayfa: 3, enCokDerinlik: 3 };
  await o.komut("taramaBaslat", { url: KOK });
  await o.bosalt();
  await sayfayiBildir(o);
  await sayfayiBildir(o);                                              // aynı sayfadan geç gelen ikinci bildirim
  assert.equal(o.depo.tarama.sayfa, 1);
  const t = await taramayiSur(o);
  assert.equal(t.durum, "bitti");
  assert.equal(t.sayfa, 3);
  assert.equal(t.neden, "Sayfa sınırına ulaşıldı");
});

test("kamu sistemi ve beyaz liste dışı adres taranamaz; anahtarsız başlamaz", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar" };
  assert.ok((await o.komut("taramaBaslat", { url: "https://ebys.gop.edu.tr/" })).hata);
  assert.ok((await o.komut("taramaBaslat", { url: "https://www.memurlar.net/" })).hata);
  assert.ok((await o.komut("taramaBaslat", { url: "https://ornek.com/" })).hata);
  o.depo.ayar = { anahtar: "" };
  assert.match((await o.komut("taramaBaslat", { url: KOK })).hata, /eşleştirme anahtarı/);
  assert.equal(o.gezintiler.length, 0);
});

test("uygulama kapanınca tarama duraklar, açılınca devam eder", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar", hiz: "hizli", enCokSayfa: 50, enCokDerinlik: 1 };
  await o.komut("taramaBaslat", { url: KOK });
  await o.bosalt();
  await sayfayiBildir(o);
  await o.zamanlayicilariCalistir();
  o.durum.uygulamaAcik = false;
  await sayfayiBildir(o);
  assert.equal(o.depo.tarama.durum, "duraklatildi");
  assert.match(o.depo.tarama.neden, /ulaşılamadı/);
  const kalan = o.depo.tarama.kuyruk.length;
  o.durum.uygulamaAcik = true;
  assert.equal((await o.komut("taramaDevam")).ok, true);
  const t = await taramayiSur(o);
  assert.equal(t.durum, "bitti");
  assert.ok(t.sayfa >= kalan);
});

test("tarama sekmesi kapatılınca duraklar; sıfırla temizler", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar", hiz: "hizli" };
  await o.komut("taramaBaslat", { url: KOK });
  await o.bosalt();
  o.dinleyiciler.kaldirildi.forEach((f) => f(o.depo.tarama.tabId));
  await o.bosalt();
  assert.equal(o.depo.tarama.durum, "duraklatildi");
  assert.equal(o.depo.tarama.kuyruk[0].url, KOK);                       // yarım kalan sayfa başa döndü
  await o.komut("taramaSifirla");
  assert.equal(o.depo.tarama, undefined);
});

test("pasif gözlem: açıkken gönderir, kapalıyken göndermez; tarama sekmesi dışındaki sayfa pasif sayılır", async () => {
  const o = ortamKur();
  o.depo.ayar = { anahtar: "anahtar", pasif: true };
  const kayit = { url: "https://personel.gop.edu.tr/duyuru", baslik: "D", metin: "x".repeat(300), dosyalar: [], baglantilar: [], imza: [] };
  await o.mesaj({ tur: "sayfa", kayit }, { id: "ext", tab: { id: 99 } });
  await o.bosalt();
  assert.equal(o.gonderilen.length, 1);
  assert.equal(o.gonderilen[0].mod, "pasif");
  assert.equal(o.depo.durum.sayac.kabul, 1);
  await o.komut("pasif", { acik: false });
  await o.mesaj({ tur: "sayfa", kayit }, { id: "ext", tab: { id: 99 } });
  await o.bosalt();
  assert.equal(o.gonderilen.length, 1);
  // Kamu sistemi adresi çalışanda da süzülür (içerik betiği atlansa bile)
  await o.komut("pasif", { acik: true });
  await o.mesaj({ tur: "sayfa", kayit: { ...kayit, url: "https://ebys.gop.edu.tr/x" } }, { id: "ext", tab: { id: 99 } });
  await o.mesaj({ tur: "sayfa", kayit }, { id: "baska-eklenti", tab: { id: 99 } });
  await o.bosalt();
  assert.equal(o.gonderilen.length, 1);
});

test("robots.txt alınamazsa tarama yapılmaz", async () => {
  const o = ortamKur({ robots: "User-agent: *\nDisallow: /\n" });
  o.depo.ayar = { anahtar: "anahtar", hiz: "hizli" };
  await o.komut("taramaBaslat", { url: KOK });
  const t = await taramayiSur(o);
  assert.equal(t.durum, "bitti");
  assert.equal(o.gezintiler.length, 0);
  assert.equal(t.sayac.robots, 1);
});
