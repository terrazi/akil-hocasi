"use strict";
const K = globalThis.AHKurallar;
const $ = (id) => document.getElementById(id);

const BAGLANTI = {
  bagli: ["Bağlı", "iyi", ""],
  kapali: ["Kapalı", "kotu", "Akıl Hocası uygulaması açık değil. Uygulama açılınca gözlem kendiliğinden sürer."],
  anahtar_yok: ["Eşleştirilmedi", "uyari", "Ayarlar'a Akıl Hocası > Ayarlar > Tarayıcı gözlemcisi bölümündeki eşleştirme anahtarını yapıştırın."],
  anahtar_hatali: ["Anahtar hatalı", "kotu", "Eşleştirme anahtarı uygulamadakiyle uyuşmuyor. Ayarlar'dan yeniden girin."],
  bilinmiyor: ["Denetleniyor", "notr", ""],
};
const TARAMA = { calisiyor: ["Taranıyor", "iyi"], duraklatildi: ["Duraklatıldı", "uyari"], bitti: ["Bitti", "notr"] };

let sekmeAdresi = "";

function gonder(komut, ek = {}) {
  return chrome.runtime.sendMessage({ tur: "acilir", komut, ...ek });
}

function rozet(el, [yazi, sinif]) {
  el.textContent = yazi;
  el.className = "rozet " + sinif;
}

function sekmeDegerlendir(adres) {
  if (!adres) return ["Bu sayfa gözlem kapsamı dışında (yalnız beyaz listedeki resmî siteler).", false];
  if (K.sistemMi(adres)) return ["Kamu sistemi veya giriş sayfası: gözlenmez, taranmaz.", false];
  if (K.ikincilMi(adres)) return ["İkincil kaynak: yalnız başlık ve soru ipuçları alınır, site taranmaz.", false];
  if (K.birincilMi(adres)) return ["Birincil resmî kaynak: gözlenir ve taranabilir.", true];
  return ["Bu site beyaz listede değil.", false];
}

async function yenile() {
  const r = await gonder("durum");
  if (!r) return;
  const d = r.durum || {};
  const b = BAGLANTI[d.baglanti] || BAGLANTI.bilinmiyor;
  rozet($("baglanti"), b);
  $("baglantiNotu").hidden = !b[2];
  $("baglantiNotu").textContent = b[2];
  const s = d.sayac || {};
  $("sKabul").textContent = s.kabul || 0;
  $("sAyni").textContent = (s.ayni || 0) + (s.tekrar || 0);
  $("sIpucu").textContent = s.ipucu || 0;
  $("sRet").textContent = (s.ret || 0) + (s.engel || 0);
  $("pasif").checked = !!r.ayar.pasif;

  const t = r.tarama;
  $("taramaKarti").hidden = !t;
  if (t) {
    rozet($("taramaRozeti"), TARAMA[t.durum] || ["", "notr"]);
    $("taramaKok").textContent = t.kok;
    $("taramaCubuk").style.width = Math.min(100, Math.round((100 * t.sayfa) / Math.max(1, t.enCok))) + "%";
    const sc = t.sayac || {};
    $("taramaBilgi").textContent = `${t.sayfa}/${t.enCok} sayfa · sırada ${t.kuyrukSayisi} · eklenen ${sc.kabul || 0} · güncel ${(sc.ayni || 0) + (sc.tekrar || 0)} · benzer şablon ${sc.benzer || 0}`;
    $("taramaNeden").textContent = t.neden || (t.durum === "calisiyor" ? "Sekme arka planda açık; kapatırsanız tarama duraklar." : "");
    $("duraklat").hidden = t.durum !== "calisiyor";
    $("devam").hidden = t.durum !== "duraklatildi";
  }
  const [yazi, taranabilir] = sekmeDegerlendir(sekmeAdresi);
  $("sekmeDurumu").textContent = yazi;
  $("tara").disabled = !taranabilir || (t && t.durum === "calisiyor");
}

async function baslat() {
  const { kurallar } = await chrome.storage.local.get("kurallar");
  if (kurallar) K.kurallariGuncelle(kurallar);
  const [sekme] = await chrome.tabs.query({ active: true, currentWindow: true });
  sekmeAdresi = (sekme && sekme.url && K.kapsamdaMi(sekme.url)) ? sekme.url : "";
  $("sekmeAdresi").textContent = sekmeAdresi || "—";
  await yenile();
  setInterval(yenile, 1500);
}

$("pasif").addEventListener("change", (e) => gonder("pasif", { acik: e.target.checked }));
$("tara").addEventListener("click", async () => {
  $("tara").disabled = true;
  const r = await gonder("taramaBaslat", { url: sekmeAdresi });
  if (r && r.hata) { $("sekmeDurumu").textContent = r.hata; }
  await yenile();
});
$("duraklat").addEventListener("click", () => gonder("taramaDuraklat").then(yenile));
$("devam").addEventListener("click", () => gonder("taramaDevam").then(yenile));
$("sifirla").addEventListener("click", () => gonder("taramaSifirla").then(yenile));
$("ayarlar").addEventListener("click", () => chrome.runtime.openOptionsPage());

baslat();
