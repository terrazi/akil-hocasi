"""Taslağın çıktıları: Word (.docx) taslak, ekranda önizleme (HTML) ve EBYS'ye aktarılacak düz metin.

Yerleşim Yönetmelik md. 7–24'e göre: A4, üst/sol/sağ 1,5 cm (logo varsa üst 0,5 cm), Times New Roman 12 ya da
Arial 11, başlık ortalı, sayı soldan ve tarih aynı satırda en sağda, konu sayının altında ve dikey ortayı
geçmeden, muhatap iki satır aşağıda ortalı, ilgi iki satır aşağıda, metin girintisi 1,25 cm ve iki yana yaslı,
imza 2–4 satır aşağıda en sağda ortalı, ek ve dağıtım solda, iletişim bilgileri sayfa altında çizgiyle ayrılmış.
Sayı, tarih, e-imza ve doğrulama kodu EBYS tarafından verilir: taslakta yer tutucu olarak gösterilir.
"""

from __future__ import annotations

import html
from pathlib import Path

from ..core.turkce import tr_upper
from .dil import baslik_birimi, kisi_adi, konu_bicimi, muhatap_bicimi
from .kurallar import PARAGRAF_GIRINTISI_CM, SAYFA, YAZI_TIPLERI, ilgi_satirlari
from .model import Imza, Yazi

SAYI_YER_TUTUCU = "[EBYS verecek]"
TARIH_YER_TUTUCU = "[e-imza tarihi]"


# ---------------------------------------------------------------- ortak parçalar
def baslik_satirlari(y: Yazi) -> list[str]:
    satirlar = [s for s in y.baslik if s.strip()] or ["T.C."]
    cikti = []
    for i, s in enumerate(satirlar):
        if i == 0:
            cikti.append("T.C." if s.replace(" ", "").upper() in ("T.C.", "TC", "T.C") else s)
        elif i == 1:
            cikti.append(tr_upper(s))                 # idare adı büyük harf (md. 10)
        else:
            cikti.append(baslik_birimi(s))            # birim: ilk harfler büyük
    return cikti


def sayi_metni(y: Yazi) -> str:
    return f"E-[DETSİS]-{y.dosya_kodu}-[kayıt no]" if y.dosya_kodu else SAYI_YER_TUTUCU


def muhatap_satirlari(y: Yazi) -> list[str]:
    if y.dagitimli and not y.muhatap.strip():
        return ["DAĞITIM YERLERİNE"]
    m = y.muhatap.strip()
    if y.kisiye or m.lower().startswith("sayın"):
        ad = m[5:].strip() if m.lower().startswith("sayın") else m
        satirlar = [f"Sayın {kisi_adi(ad)}"]
    else:
        satirlar = [muhatap_bicimi(m)] if m else ["[MUHATAP]"]
        if y.muhatap_birim.strip():
            satirlar.append(f"({baslik_birimi(y.muhatap_birim.strip().strip('()'))})")
    satirlar += [s for s in y.muhatap_adres if s.strip()]
    return satirlar


def imza_satirlari(i: Imza) -> list[str]:
    if not (i.ad or i.soyad or i.unvan):
        return ["[Ad SOYAD]", "[Unvan]"]
    ad = kisi_adi(i.ad, i.soyad)
    ilk = f"{i.on_unvan.strip()} {ad}".strip()
    satirlar = [ilk]
    if i.yetki.strip():
        satirlar.append(i.yetki.strip())
    if i.unvan.strip():
        satirlar.append(i.unvan.strip())
    return satirlar


def ek_satirlari(y: Yazi) -> list[str]:
    ekler = [e.strip() for e in y.ekler if e.strip()]
    if not ekler:
        return []
    if len(ekler) == 1:
        return [f"Ek: {ekler[0]}"]
    return ["Ek:"] + [f"{n}- {e}" for n, e in enumerate(ekler, 1)]


def metin_paragraflari(y: Yazi) -> list[str]:
    return [p.metin.strip() for p in y.paragraflar if p.metin.strip()]


def iletisim_satirlari(y: Yazi) -> tuple[list[str], list[str]]:
    il = y.iletisim
    sol = [x for x in (il.adres, " ".join(filter(None, [f"Telefon: {il.telefon}" if il.telefon else "",
                                                        f"Faks: {il.faks}" if il.faks else ""])),
                       " ".join(filter(None, [f"E-posta: {il.eposta}" if il.eposta else "",
                                              f"İnternet: {il.internet}" if il.internet else ""])),
                       f"KEP: {il.kep}" if il.kep else "") if x]
    sag = []
    if il.bilgi_ad or il.bilgi_unvan or il.bilgi_telefon:
        sag = ["Bilgi için: " + (kisi_adi(il.bilgi_ad) if il.bilgi_ad else ""),
               il.bilgi_unvan, f"Telefon: {il.bilgi_telefon}" if il.bilgi_telefon else ""]
    return sol, [s for s in sag if s]


# ---------------------------------------------------------------- EBYS düz metni
def ebys_metni(y: Yazi) -> str:
    """enVision EBYS'de alan alan yapıştırılacak metin. Sayı, tarih ve imzayı EBYS verir."""
    bolumler = [f"KONU: {konu_bicimi(y.konu)}", "MUHATAP:\n" + "\n".join(muhatap_satirlari(y))]
    ilgiler = ilgi_satirlari(y)
    if ilgiler:
        bolumler.append("İLGİ:\n" + "\n".join(ilgiler))
    bolumler.append("METİN:\n" + "\n".join(metin_paragraflari(y)))
    if y.olur:
        bolumler.append("OLUR MAKAMI:\n" + "\n".join(imza_satirlari(y.olur)))
    ekler = ek_satirlari(y)
    if ekler:
        bolumler.append("EK:\n" + "\n".join(e.removeprefix("Ek: ").removeprefix("Ek:") for e in ekler if e != "Ek:"))
    if y.gereği or y.bilgi:
        d = "DAĞITIM:"
        if y.gereği:
            d += "\nGereği:\n" + "\n".join(y.gereği)
        if y.bilgi:
            d += "\nBilgi:\n" + "\n".join(y.bilgi)
        bolumler.append(d)
    if y.ivedilik:
        bolumler.append(f"İVEDİLİK: {y.ivedilik}" + (f" (cevap süresi: {y.cevap_suresi})" if y.cevap_suresi else ""))
    return "\n\n".join(bolumler)


# ---------------------------------------------------------------- önizleme (HTML)
def html_onizleme(y: Yazi) -> str:
    e = html.escape
    yazi_tipi = y.yazi_tipi if y.yazi_tipi in YAZI_TIPLERI else "Times New Roman"
    punto = YAZI_TIPLERI[yazi_tipi]
    parcalar = [f"<div style=\"font-family:'{yazi_tipi}'; font-size:{punto}pt; color:#111; line-height:1.25;\">"]
    parcalar.append("<div style='text-align:right; color:#9AA0B4; font-size:9pt;'>TASLAK — sayı, tarih ve e-imza "
                    "EBYS'de verilir</div>")
    if y.ivedilik:
        parcalar.append(f"<div style='text-align:right; color:#C62828;'>{e(y.ivedilik)}</div>")
    for s in baslik_satirlari(y):
        parcalar.append(f"<div style='text-align:center;'>{e(s)}</div>")
    parcalar.append("<br><br>")
    parcalar.append("<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                    f"<td>Sayı&nbsp;&nbsp;: <span style='color:#7A7F99;'>{e(sayi_metni(y))}</span></td>"
                    f"<td align='right' style='color:#7A7F99;'>{e(TARIH_YER_TUTUCU)}</td></tr></table>")
    parcalar.append(f"<div style='width:50%;'>Konu&nbsp;: {e(konu_bicimi(y.konu)) or '[Konu]'}</div><br><br>")
    for s in muhatap_satirlari(y):
        parcalar.append(f"<div style='text-align:center;'>{e(s)}</div>")
    ilgiler = ilgi_satirlari(y)
    if ilgiler:
        parcalar.append("<br><br><table cellspacing='0' cellpadding='0'>")
        for n, s in enumerate(ilgiler):
            parcalar.append(f"<tr><td valign='top' style='white-space:nowrap;'>{'İlgi&nbsp;&nbsp;&nbsp;:' if n == 0 else ''}"
                            f"&nbsp;</td><td>{e(s)}</td></tr>")
        parcalar.append("</table><br>")
    else:
        parcalar.append("<br><br>")
    for p in y.paragraflar:
        if not p.metin.strip():
            continue
        renk = "#B26A00" if p.tur == "yer_tutucu" or "[" in p.metin else "#111"
        atif = "".join(f"<sup style='color:#4F46E5;'>[{html.escape(k.lstrip('K'))}]</sup>" for k in p.kaynaklar)
        parcalar.append(f"<p style='text-indent:{PARAGRAF_GIRINTISI_CM}cm; text-align:justify; margin:0; color:{renk};'>"
                        f"{e(p.metin.strip())}{atif}</p>")
    parcalar.append("<br><br>")
    for s in imza_satirlari(y.imza):
        parcalar.append(f"<div style='margin-left:58%; text-align:center;'>{e(s)}</div>")
    if y.olur:
        parcalar.append("<br><div style='text-align:center;'>OLUR</div><div style='text-align:center; color:#7A7F99;'>"
                        f"{e(TARIH_YER_TUTUCU)}</div>")
        for s in imza_satirlari(y.olur):
            parcalar.append(f"<div style='text-align:center;'>{e(s)}</div>")
    ekler = ek_satirlari(y)
    if ekler:
        parcalar.append("<br>" + "".join(f"<div>{e(s)}</div>" for s in ekler))
    if y.gereği or y.bilgi:
        parcalar.append("<br><div>Dağıtım:</div><table width='100%' cellspacing='0' cellpadding='0'><tr>"
                        f"<td valign='top' width='50%'>{'Gereği:<br>' + '<br>'.join(map(e, y.gereği)) if y.gereği else ''}</td>"
                        f"<td valign='top'>{'Bilgi:<br>' + '<br>'.join(map(e, y.bilgi)) if y.bilgi else ''}</td>"
                        "</tr></table>")
    sol, sag = iletisim_satirlari(y)
    if sol or sag:
        parcalar.append("<br><hr style='border:0; border-top:1px solid #999;'>"
                        "<table width='100%' style='font-size:8pt; color:#333;'><tr>"
                        f"<td valign='top'>{'<br>'.join(map(e, sol))}</td>"
                        f"<td valign='top' align='right'>{'<br>'.join(map(e, sag))}</td></tr></table>")
    parcalar.append("</div>")
    return "".join(parcalar)


# ---------------------------------------------------------------- Word (.docx)
def docx_kaydet(y: Yazi, yol: str | Path) -> Path:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    yazi_tipi = y.yazi_tipi if y.yazi_tipi in YAZI_TIPLERI else "Times New Roman"
    punto = YAZI_TIPLERI[yazi_tipi]
    d = Document()
    bolum = d.sections[0]
    bolum.page_width, bolum.page_height = Cm(SAYFA["en_cm"]), Cm(SAYFA["boy_cm"])
    bolum.top_margin = Cm(SAYFA["ust_logo_cm"] if y.logo else SAYFA["ust_cm"])
    bolum.left_margin, bolum.right_margin = Cm(SAYFA["sol_cm"]), Cm(SAYFA["sag_cm"])
    bolum.bottom_margin = Cm(SAYFA["alt_cm"])
    bolum.header_distance, bolum.footer_distance = Cm(0.5), Cm(0.5)
    genislik_cm = SAYFA["en_cm"] - SAYFA["sol_cm"] - SAYFA["sag_cm"]

    stil = d.styles["Normal"]
    stil.font.name, stil.font.size = yazi_tipi, Pt(punto)
    rpr = stil.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(a), yazi_tipi)
    stil.paragraph_format.space_before = Pt(0)
    stil.paragraph_format.space_after = Pt(0)
    stil.paragraph_format.line_spacing = 1.0

    def par(metin: str = "", hiza=None, girinti_cm: float | None = None, sol_cm: float | None = None,
            asili_cm: float | None = None, renk: RGBColor | None = None, punto_: float | None = None):
        p = d.add_paragraph()
        if hiza is not None:
            p.alignment = hiza
        if girinti_cm is not None:
            p.paragraph_format.first_line_indent = Cm(girinti_cm)
        if sol_cm is not None:
            p.paragraph_format.left_indent = Cm(sol_cm)
        if asili_cm is not None:
            p.paragraph_format.first_line_indent = Cm(-asili_cm)
        if metin:
            r = p.add_run(metin)
            if renk is not None:
                r.font.color.rgb = renk
            if punto_:
                r.font.size = Pt(punto_)
        return p

    gri = RGBColor(0x7A, 0x7F, 0x99)
    # Üst bilgi: taslak uyarısı (EBYS'ye aktarılırken kaldırılır)
    ust = bolum.header.paragraphs[0]
    ust.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = ust.add_run("TASLAK — Sayı, tarih ve e-imza EBYS tarafından verilir")
    r.font.size, r.font.color.rgb = Pt(8), RGBColor(0x9A, 0xA0, 0xB4)

    if y.ivedilik:                                                        # md. 26: sağ üstte kırmızı
        par(y.ivedilik, WD_ALIGN_PARAGRAPH.RIGHT, renk=RGBColor(0xC6, 0x28, 0x28))
    if y.gizlilik:
        par(y.gizlilik, WD_ALIGN_PARAGRAPH.CENTER)
    for s in baslik_satirlari(y):                                         # md. 10
        par(s, WD_ALIGN_PARAGRAPH.CENTER)
    par()
    par()                                                                 # md. 11: iki satır boşluk
    p = par()                                                             # sayı solda, tarih aynı satırda en sağda
    p.paragraph_format.tab_stops.add_tab_stop(Cm(1.1))
    p.paragraph_format.tab_stops.add_tab_stop(Cm(genislik_cm), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run("Sayı\t: ")
    p.add_run(sayi_metni(y)).font.color.rgb = gri
    p.add_run("\t")
    p.add_run(TARIH_YER_TUTUCU).font.color.rgb = gri
    p = par(f"Konu\t: {konu_bicimi(y.konu) or '[Konu]'}", sol_cm=1.45, asili_cm=1.45)     # md. 13
    p.paragraph_format.tab_stops.add_tab_stop(Cm(1.1))
    p.paragraph_format.right_indent = Cm(genislik_cm / 2)                # dikey orta hizayı geçmez
    par()
    par()                                                                 # md. 14: iki satır boşluk
    for s in muhatap_satirlari(y):
        par(s, WD_ALIGN_PARAGRAPH.CENTER)
    ilgiler = ilgi_satirlari(y)
    par()
    if ilgiler:
        par()                                                             # md. 15: iki satır boşluk
        for n, s in enumerate(ilgiler):
            p = par(("İlgi\t: " if n == 0 else "\t  ") + s, sol_cm=1.45, asili_cm=1.45)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(1.1))
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        par()                                                             # md. 16: ilgi ile metin arası bir satır
    else:
        par()                                                             # ilgi yoksa muhatapla metin arası iki satır
    for m in metin_paragraflari(y):                                      # md. 16: 1,25 cm girinti, iki yana yaslı
        par(m, WD_ALIGN_PARAGRAPH.JUSTIFY, girinti_cm=PARAGRAF_GIRINTISI_CM)
    par()
    par()                                                                 # md. 17: 2–4 satır boşluk
    for s in imza_satirlari(y.imza):
        par(s, WD_ALIGN_PARAGRAPH.CENTER, sol_cm=genislik_cm * 0.58)
    if y.olur:                                                            # md. 20
        par()
        par("OLUR", WD_ALIGN_PARAGRAPH.CENTER)
        par(TARIH_YER_TUTUCU, WD_ALIGN_PARAGRAPH.CENTER, renk=gri)
        for s in imza_satirlari(y.olur):
            par(s, WD_ALIGN_PARAGRAPH.CENTER)
    ekler = ek_satirlari(y)
    if ekler:                                                             # md. 18
        par()
        for s in ekler:
            par(s)
    if y.gereği or y.bilgi:                                               # md. 19
        par()
        par("Dağıtım:")
        t = d.add_table(rows=1, cols=2)
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        for hucre, baslik, liste in ((t.rows[0].cells[0], "Gereği:", y.gereği), (t.rows[0].cells[1], "Bilgi:", y.bilgi)):
            hucre.paragraphs[0].text = baslik if liste else ""
            for s in liste:
                hucre.add_paragraph(s)
    # Alt bilgi: iletişim bilgileri (md. 24), üstte çizgi
    sol, sag = iletisim_satirlari(y)
    alt = bolum.footer
    if sol or sag:
        t = alt.add_table(rows=1, cols=2, width=Cm(genislik_cm))
        for hucre, satirlar, hiza in ((t.rows[0].cells[0], sol, WD_ALIGN_PARAGRAPH.LEFT),
                                      (t.rows[0].cells[1], sag, WD_ALIGN_PARAGRAPH.RIGHT)):
            hucre.paragraphs[0].text = ""
            for n, s in enumerate(satirlar):
                p = hucre.paragraphs[0] if n == 0 else hucre.add_paragraph()
                p.alignment = hiza
                rr = p.add_run(s)
                rr.font.size = Pt(8)
        cizgi = alt.paragraphs[0]
        ppr = cizgi._p.get_or_add_pPr()
        kenar = OxmlElement("w:pBdr")
        ust_k = OxmlElement("w:bottom")
        for a, v in (("w:val", "single"), ("w:sz", "4"), ("w:space", "1"), ("w:color", "808080")):
            ust_k.set(qn(a), v)
        kenar.append(ust_k)
        ppr.append(kenar)
    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    d.core_properties.title = konu_bicimi(y.konu) or "Resmî yazı taslağı"
    d.core_properties.comments = "Akıl Hocası TASLAK — sayı, tarih ve e-imza EBYS tarafından verilir"
    d.save(str(yol))
    return yol
