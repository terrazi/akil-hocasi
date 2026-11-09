"""PyInstaller giriş noktası: AkilHocasiKopru.exe (Chrome/Edge yerel mesajlaşma köprüsü) bu dosyadan üretilir.

Tarayıcı bu küçük konsol programını yalnızca Akıl Hocası Gözlemci eklentisi için çalıştırır; program
eşleştirme anahtarını ve bağlantı noktasını döndürür, gerekirse Akıl Hocası'nı tepside başlatır.
"""

import sys

from akil_hocasi.gozlem.eslestirme import kopru_main

if __name__ == "__main__":
    sys.exit(kopru_main())
