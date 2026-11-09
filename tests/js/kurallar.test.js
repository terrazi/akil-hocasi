// Akıl Hocası Gözlemci kuralları — Node yerleşik test çalıştırıcısı: node --test tests/js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const K = require(path.join(__dirname, "..", "..", "gozlemci_eklenti", "kurallar.js"));

test("kamu sistemleri ve giriş sayfaları engellenir", () => {
  for (const u of [
    "https://www.turkiye.gov.tr/x", "https://kbs.muhasebat.gov.tr/", "https://ebys.gop.edu.tr/envision/",
    "https://obs.gop.edu.tr/", "https://portal.gop.edu.tr/", "https://hitap.sgk.gov.tr/", "https://ekap.kik.gov.tr/",
    "https://personel.gop.edu.tr/giris", "https://kalite.gop.edu.tr/login?next=/", "bozuk adres",
  ]) assert.equal(K.sistemMi(u), true, u);
  for (const u of [
    "https://ebysyardim.gop.edu.tr/mevzuat", "https://kalite.gop.edu.tr/formlar",
    "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=657", "https://www.resmigazete.gov.tr/",
  ]) assert.equal(K.sistemMi(u), false, u);
});

test("beyaz liste: birincil, ikincil, kapsam dışı", () => {
  assert.ok(K.birincilMi("https://personel.gop.edu.tr/a"));
  assert.ok(K.ikincilMi("https://www.memurlar.net/haber/1"));
  assert.ok(!K.kapsamdaMi("https://ornek.com/"));
  assert.ok(!K.kapsamdaMi("ftp://gop.edu.tr/"));
  assert.ok(!K.birincilMi("https://gop.edu.tr.kotu.com/"));
});

test("uygulama kuralları yalnızca daraltabilir", () => {
  K.kurallariGuncelle({ birincil: ["gop.edu.tr", "kotu.com"], ikincil: [], sistem_alanlari: ["yeni-sistem.gov.tr"], sistem_anahtarlari: [], istisnalar: ["ebys.gop.edu.tr"] });
  assert.ok(!K.birincilMi("https://kotu.com/"));
  assert.ok(!K.birincilMi("https://www.mevzuat.gov.tr/"));
  assert.ok(K.sistemMi("https://ebys.gop.edu.tr/"));             // istisna listesine eklenemez
  assert.ok(K.sistemMi("https://a.yeni-sistem.gov.tr/"));
  K.kurallariGuncelle({});
  K.kurallariGuncelle({ birincil: K.BIRINCIL, ikincil: K.IKINCIL, istisnalar: K.ISTISNALAR });
  assert.ok(K.birincilMi("https://www.mevzuat.gov.tr/"));
  assert.ok(!K.sistemMi("https://ebysyardim.gop.edu.tr/"));
});

test("maskeleme", () => {
  const m = K.maskele("TC 10000000146 tel 0532 123 45 67 kart 4111-1111-1111-1111 IBAN TR33 0006 1005 1978 6457 8413 26 sabit 0356 252 16 16");
  assert.ok(!m.includes("10000000146") && !m.includes("123 45 67") && !m.includes("4111") && !m.includes("6457"));
  assert.ok(m.includes("[CEP TELEFONU]") && m.includes("[KART NO]") && m.includes("0356 252 16 16"));
});

test("adres sadeleştirme ve riskli bağlantılar", () => {
  assert.equal(K.adresSadelestir("/a?utm_source=x&id=3#b", "https://kalite.gop.edu.tr/"), "https://kalite.gop.edu.tr/a?id=3");
  assert.equal(K.adresSadelestir("javascript:void(0)", "https://kalite.gop.edu.tr/"), null);
  assert.equal(K.adresSadelestir("mailto:a@b.c", "https://kalite.gop.edu.tr/"), null);
  for (const [u, t] of [["https://x.gop.edu.tr/logout", ""], ["https://x.gop.edu.tr/kayit/sil?id=1", ""], ["https://x.gop.edu.tr/a", "Çıkış"], ["https://x.gop.edu.tr/wp-admin/", ""]]) {
    assert.ok(K.riskliBaglanti(u, t), u + " " + t);
  }
  assert.ok(!K.riskliBaglanti("https://x.gop.edu.tr/duyurular/silah-ruhsati-yonetmeligi", "Duyuru"));
  assert.ok(K.oturumIsareti([{ url: "https://x/a", metin: "Oturumu Kapat" }]));
  assert.ok(!K.oturumIsareti([{ url: "https://x/a", metin: "Duyurular" }]));
});

test("robots.txt", () => {
  const r = K.robotsAyristir("User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nDisallow: /gizli/\nAllow: /gizli/acik\nDisallow: /*.php$\n");
  assert.ok(K.robotsIzinli(r, "/duyurular"));
  assert.ok(!K.robotsIzinli(r, "/gizli/x"));
  assert.ok(K.robotsIzinli(r, "/gizli/acik/1"));
  assert.ok(!K.robotsIzinli(r, "/ara.php"));
  assert.ok(K.robotsIzinli(r, "/ara.php?x=1"));
  assert.ok(K.robotsIzinli(K.robotsAyristir("User-agent: *\nDisallow:\n"), "/her/sey"));
  assert.ok(!K.robotsIzinli(K.robotsAyristir("User-agent: akilhocasi\nDisallow: /\nUser-agent: *\nAllow: /\n"), "/a"));
});

test("yol kalıbı, benzerlik ve genişletme süzgeci", () => {
  assert.equal(K.yolKalibi("https://x.gop.edu.tr/duyuru/123?sayfa=2"), "x.gop.edu.tr/duyuru/:n?sayfa=*");
  assert.equal(K.yolKalibi("https://x.gop.edu.tr/haber-2024-001"), "x.gop.edu.tr/:id");
  assert.equal(K.benzerlik(["a", "b"], ["a", "b"]), 1);
  assert.equal(K.benzerlik(["a", "b"], ["c"]), 0);
  const imza = ["0:body", "1:div.icerik", "2:h1"];
  const gecmis = Array.from({ length: 5 }, () => ({ kalip: "k", imza }));
  assert.equal(K.genisletilsinMi(imza, "k", gecmis.slice(0, 4)), true);
  assert.equal(K.genisletilsinMi(imza, "k", gecmis), false);
  assert.equal(K.genisletilsinMi(imza, "baska", gecmis), true);
});

function dugum(etiket, ozellik, ...cocuklar) {
  return {
    nodeType: 1, tagName: etiket, childNodes: cocuklar.map((c) => (typeof c === "string" ? { nodeType: 3, nodeValue: c } : c)),
    get children() { return this.childNodes.filter((c) => c.nodeType === 1); },
    getAttribute(ad) { return ad in (ozellik || {}) ? ozellik[ad] : null; },
  };
}

test("metin çıkarma: menü, form ve gizli öğeler atlanır", () => {
  const govde = dugum("BODY", {},
    dugum("NAV", {}, "Ana Sayfa Menü"),
    dugum("DIV", { class: "main-menu" }, "Menü öğesi"),
    dugum("MAIN", {},
      dugum("H1", {}, "Yıllık İzin"),
      dugum("P", {}, "Personelin ", dugum("B", {}, "yıllık izni"), " birim amirince verilir."),
      dugum("TABLE", {}, dugum("TR", {}, dugum("TD", {}, "Süre"), dugum("TD", {}, "20 gün"))),
      dugum("P", { hidden: "" }, "Gizli metin"),
      dugum("FORM", {}, dugum("INPUT", {}), "Form metni"),
      dugum("SCRIPT", {}, "var x=1;")),
    dugum("FOOTER", {}, "Telif"));
  const m = K.metinCikar(govde);
  assert.ok(m.includes("Yıllık İzin") && m.includes("Personelin yıllık izni birim amirince verilir."));
  assert.ok(m.includes("Süre | 20 gün"));
  for (const yok of ["Menü", "Gizli", "Form metni", "var x", "Telif"]) assert.ok(!m.includes(yok), yok);
  const imza = K.imzaCikar(govde);
  assert.ok(imza.includes("0:body") && imza.includes("1:div.main-menu"));
});

test("tarama bağlantıları: aynı alan, güvenli, dosya değil, tekrarsız", () => {
  const b = [
    { url: "https://kalite.gop.edu.tr/formlar", metin: "Formlar" },
    { url: "https://kalite.gop.edu.tr/formlar#ust", metin: "Formlar" },
    { url: "https://kalite.gop.edu.tr/logout", metin: "Çıkış" },
    { url: "https://kalite.gop.edu.tr/depo/a.pdf", metin: "PDF" },
    { url: "https://kalite.gop.edu.tr/resim.jpg", metin: "Resim" },
    { url: "https://personel.gop.edu.tr/", metin: "Başka alt alan" },
    { url: "https://kalite.gop.edu.tr/giris", metin: "Giriş" },
    { url: "https://kalite.gop.edu.tr/duyurular?utm_source=x", metin: "Duyurular" },
  ];
  assert.deepEqual(K.taramaBaglantilari(b, "https://kalite.gop.edu.tr/", "kalite.gop.edu.tr"),
    ["https://kalite.gop.edu.tr/formlar", "https://kalite.gop.edu.tr/duyurular"]);
});

test("hız profilleri sapma içinde kalır", () => {
  for (let i = 0; i < 50; i++) {
    const n = K.bekleme("hizli");
    assert.ok(n >= 900 && n <= 2100, String(n));
  }
  assert.ok(K.bekleme("bilinmeyen") >= 1800);
});
