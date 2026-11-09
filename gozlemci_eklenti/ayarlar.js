"use strict";
const $ = (id) => document.getElementById(id);
const VARSAYILAN = { port: 47231, anahtar: "", pasif: true, hiz: "normal", enCokSayfa: 200, enCokDerinlik: 4 };

async function oku() {
  const { ayar } = await chrome.storage.local.get("ayar");
  return { ...VARSAYILAN, ...(ayar || {}) };
}

async function yukle() {
  const a = await oku();
  $("anahtar").value = a.anahtar;
  $("port").value = a.port;
  $("hiz").value = a.hiz;
  $("enCokSayfa").value = a.enCokSayfa;
  $("enCokDerinlik").value = a.enCokDerinlik;
}

function sinirla(deger, alt, ust, varsayilan) {
  const n = Math.round(Number(deger));
  return Number.isFinite(n) ? Math.min(ust, Math.max(alt, n)) : varsayilan;
}

async function kaydet() {
  const a = await oku();
  const yeni = {
    ...a,
    anahtar: $("anahtar").value.trim(),
    port: sinirla($("port").value, 1024, 65535, VARSAYILAN.port),
    hiz: ["yavas", "normal", "hizli"].includes($("hiz").value) ? $("hiz").value : "normal",
    enCokSayfa: sinirla($("enCokSayfa").value, 1, 5000, VARSAYILAN.enCokSayfa),
    enCokDerinlik: sinirla($("enCokDerinlik").value, 0, 10, VARSAYILAN.enCokDerinlik),
  };
  await chrome.storage.local.set({ ayar: yeni });
  await yukle();
eslesmeyiGoster();
}

$("kaydet").addEventListener("click", async () => {
  await kaydet();
  $("sonuc").textContent = "Sınanıyor…";
  const r = await chrome.runtime.sendMessage({ tur: "acilir", komut: "sina" });
  if (r && r.sonuc && r.sonuc.ok) {
    $("sonuc").textContent = `Bağlandı: ${r.sonuc.uygulama} ${r.sonuc.surum}. Gözlem hazır.`;
    $("sonuc").style.color = "var(--yesil)";
  } else {
    const { durum } = await chrome.storage.local.get("durum");
    const neden = durum && durum.baglanti === "anahtar_hatali" ? "Anahtar uygulamadakiyle uyuşmuyor."
      : durum && durum.baglanti === "anahtar_yok" ? "Anahtar girilmedi."
        : "Uygulamaya ulaşılamadı. Akıl Hocası açık mı, bağlantı noktası doğru mu?";
    $("sonuc").textContent = neden;
    $("sonuc").style.color = "var(--kirmizi)";
  }
});
async function eslesmeyiGoster() {
  const { durum } = await chrome.storage.local.get("durum");
  const d = durum || {};
  const el = $("eslesme");
  if (d.kopru === "eslesti" && d.baglanti === "bagli") { el.textContent = "Eşleşti"; el.className = "rozet iyi"; }
  else if (d.kopru === "eslesti") { el.textContent = "Eşleşti · program kapalı"; el.className = "rozet uyari"; }
  else if (d.kopru === "yok") { el.textContent = "Köprü bulunamadı"; el.className = "rozet kotu"; }
  else if (d.kopru === "red") { el.textContent = d.kopruNotu || "Reddedildi"; el.className = "rozet uyari"; }
  else { el.textContent = "Denetleniyor"; el.className = "rozet notr"; }
}

$("yenidenEslestir").addEventListener("click", async () => {
  $("sonuc").textContent = "Eşleşiliyor…";
  const r = await chrome.runtime.sendMessage({ tur: "acilir", komut: "eslestir" });
  const s = await chrome.runtime.sendMessage({ tur: "acilir", komut: "sina" });
  await yukle();
eslesmeyiGoster();
  await eslesmeyiGoster();
  if (r && r.ok && s && s.sonuc && s.sonuc.ok) {
    $("sonuc").textContent = `Eşleşti ve bağlandı: ${s.sonuc.uygulama} ${s.sonuc.surum}.`;
    $("sonuc").style.color = "var(--yesil)";
  } else if (r && r.ok) {
    $("sonuc").textContent = "Eşleşti; Akıl Hocası açılıyor. Birkaç saniye sonra yeniden deneyin.";
    $("sonuc").style.color = "var(--sari)";
  } else {
    $("sonuc").textContent = "Köprü bulunamadı. Akıl Hocası kurulu değilse kurun; kuruluysa aşağıdan elle eşleştirin.";
    $("sonuc").style.color = "var(--kirmizi)";
  }
});

$("kaydet2").addEventListener("click", async () => {
  await kaydet();
  $("sonuc").textContent = "Tarama ayarları kaydedildi.";
});

yukle();
eslesmeyiGoster();
