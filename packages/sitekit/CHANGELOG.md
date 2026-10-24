# sitekit — o'zgarishlar tarixi

Semantik versiyalash.

## 0.1.0 — 2026-09-14

Birinchi reliz: reklama olib boradigan sahifani launch'dan oldin tekshirish.

### Qo'shildi
- `probe(url)`: sahifani bir marta ochib ko'radi va `SiteProbe` qaytaradi —
  natija (`ok`, `not_found`, `no_such_host`, `refused`, `timeout`, …),
  HTTP status, oxirgi manzil, sahifadagi Meta pixel ID lari va Google Tag
  Manager bor-yo'qligi.
- `SiteProbe.is_down`: faqat hamma uchun ishlamaydigan holatlar
  (`no_such_host`, `refused`, `not_found`). Bot himoyasi (403/503), vaqt
  tugashi va TLS xatosi bunga kirmaydi — sahifa odam uchun ochilishi mumkin.
- Manzil himoyasi: faqat `http`/`https`, faqat 80/443 port, har qadamda
  (yo'naltirishlar ham) DNS javobi tekshiriladi — ichki, loopback,
  link-local va boshqa global bo'lmagan manzilga ulanilmaydi. Yo'naltirish
  qo'lda, ko'pi bilan 5 ta. Sahifaning faqat birinchi 512 KB i o'qiladi.
- `trust_env=False`: proksi va sertifikat sozlamasi muhitdan o'qilmaydi.
