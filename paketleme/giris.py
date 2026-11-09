"""PyInstaller giriş noktası: AkilHocasi.exe bu dosyadan üretilir."""

import sys

if __name__ == "__main__":
    try:
        from akil_hocasi.uygulama import main
    except Exception:
        # Öz testte içe aktarma hatası pencere açıp beklemesin, rapora yazılsın
        import traceback
        for arg in sys.argv[1:]:
            if arg.startswith("--oz-test="):
                with open(arg.split("=", 1)[1], "w", encoding="utf-8") as f:
                    f.write("SONUÇ: BAŞARISIZ (içe aktarma)\n" + traceback.format_exc())
                sys.exit(1)
        raise
    sys.exit(main())
