/* Akıl Hocası Gözlemci — içerik betiği.
 * Yalnızca okur: hiçbir öğeye tıklamaz, form doldurmaz, sayfayı değiştirmez.
 * Kamu sistemi, parola alanı veya çıkış bağlantısı görülürse hiçbir içerik okunmaz.
 */
(() => {
  "use strict";
  if (window.top !== window || window.__akilHocasiGozlem) return;
  window.__akilHocasiGozlem = true;

  const K = globalThis.AHKurallar;
  const EN_COK_METIN = 1500000;
  const EN_COK_GONDERIM = 5;
  let gonderim = 0;
  let sonOzet = "";
  let zamanlayici = null;

  function anaBolge() {
    return document.querySelector("main, article, [role='main'], #content, #icerik, #main-content, .content, .icerik, .page-content, .entry-content") || document.body;
  }

  function gizliMi(el) {
    if (el === document.body) return false;
    if (el.offsetParent !== null) return false;
    const stil = getComputedStyle(el);
    return stil.display === "none" || stil.visibility === "hidden";
  }

  function ozet(metin) {
    let h = 0;
    for (let i = 0; i < metin.length; i += 7) h = (h * 31 + metin.charCodeAt(i)) | 0;
    return location.href + "|" + metin.length + "|" + h;
  }

  function gozle() {
    if (gonderim >= EN_COK_GONDERIM || !document.body) return;
    const adres = location.href;
    if (!K.kapsamdaMi(adres)) return;
    if (K.sistemMi(adres)) {
      chrome.runtime.sendMessage({ tur: "engel", url: adres, neden: "kamu sistemi veya oturumlu uygulama" });
      return;
    }
    const baglantilar = Array.from(document.querySelectorAll("a[href]")).slice(0, 4000).map((a) => ({
      url: a.href,
      metin: (a.innerText || a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 200),
    }));
    if (document.querySelector("input[type='password']") || K.oturumIsareti(baglantilar)) {
      chrome.runtime.sendMessage({ tur: "engel", url: adres, neden: "oturum açık sayfa" });
      return;
    }

    const metin = K.maskele(K.metinCikar(anaBolge(), gizliMi)).slice(0, EN_COK_METIN);
    const o = ozet(metin);
    if (o === sonOzet) return;
    sonOzet = o;
    gonderim++;

    const dosyalar = [];
    const sayfalar = [];
    const host = location.hostname.toLowerCase();
    for (const b of baglantilar) {
      const u = K.adresSadelestir(b.url, adres);
      if (!u) continue;
      if (K.dosyaMi(u)) dosyalar.push({ url: u, metin: K.maskele(b.metin) });
      else if (K.host(u) === host) sayfalar.push({ url: u, metin: b.metin });
    }
    const h1 = document.querySelector("h1");
    chrome.runtime.sendMessage({
      tur: "sayfa",
      kayit: {
        url: adres,
        baslik: K.maskele(((h1 && h1.innerText) || document.title || "").trim()).slice(0, 300),
        metin,
        dil: document.documentElement.lang || "",
        dosyalar: dosyalar.slice(0, 300),
        baglantilar: sayfalar.slice(0, 600),
        imza: K.imzaCikar(document.body),
      },
    });
  }

  let ilkPlan = 0;
  function planla(gecikme) {
    const simdi = Date.now();
    if (zamanlayici && simdi - ilkPlan > 6000) return;   // sürekli değişen sayfada (kayan duyuru vb.) en geç 6 sn
    if (!zamanlayici) ilkPlan = simdi;
    clearTimeout(zamanlayici);
    zamanlayici = setTimeout(() => {
      zamanlayici = null;
      try { gozle(); } catch (_) { /* gözlem hatası sayfayı etkilemez */ }
    }, gecikme);
  }

  planla(1200);
  // Tek sayfa uygulamalarında içerik sonradan gelir: değişiklik durulunca yeniden bak (en çok 5 kez)
  new MutationObserver(() => { if (gonderim < EN_COK_GONDERIM) planla(2500); })
    .observe(document.documentElement, { childList: true, subtree: true });
})();
