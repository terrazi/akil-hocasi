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
$("kaydet2").addEventListener("click", async () => {
  await kaydet();
  $("sonuc").textContent = "Tarama ayarları kaydedildi.";
});

yukle();
