/* Akıl Hocası Gözlemci — içerik betiği.
 * Yalnızca okur: hiçbir öğeye tıklamaz, form doldurmaz, sayfayı değiştirmez.
 * Kamu sistemi, parola alanı veya çıkış bağlantısı görülürse hiçbir içerik okunmaz.
 * Okuma kuralı (AHKurallar.sayfaOku) programın gömülü tarayıcı motoruyla ortaktır.
 */
(() => {
  "use strict";
  if (window.top !== window || window.__akilHocasiGozlem) return;
  window.__akilHocasiGozlem = true;

  const K = globalThis.AHKurallar;
  const EN_COK_GONDERIM = 5;
  let gonderim = 0;
  let sonOzet = "";
  let zamanlayici = null;
  let ilkPlan = 0;

  function ozet(kayit) {
    let h = 0;
    const m = kayit.metin;
    for (let i = 0; i < m.length; i += 7) h = (h * 31 + m.charCodeAt(i)) | 0;
    return kayit.url + "|" + m.length + "|" + h;
  }

  function gozle() {
    if (gonderim >= EN_COK_GONDERIM || !document.body) return;
    const sonuc = K.sayfaOku(document, location);
    if (sonuc.tur === "kapsam_disi") return;
    if (sonuc.tur === "engel") {
      gonderim = EN_COK_GONDERIM;                       // bu sayfa bir daha okunmaz
      chrome.runtime.sendMessage({ tur: "engel", url: sonuc.url, neden: sonuc.neden });
      return;
    }
    const o = ozet(sonuc.kayit);
    if (o === sonOzet) return;
    sonOzet = o;
    gonderim++;
    chrome.runtime.sendMessage({ tur: "sayfa", kayit: sonuc.kayit });
  }

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
