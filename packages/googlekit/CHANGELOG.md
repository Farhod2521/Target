# googlekit — o'zgarishlar tarixi

Semantik versiyalash. Sheets API — `v4`, Drive API — `v3`. Ikkala
versiya ham `sheets.py` dagi URL'larda turadi, boshqa hech qayerda emas.

## 0.3.0 — 2026-10-01

Google Ads ulanishi uchun.

### Qo'shildi
- `SCOPE_ADWORDS` — Google Ads akkauntlarini o'qish va yozish ruxsati
  (sensitive; verifikatsiyagacha faqat test foydalanuvchilar).
- `Grant.subject` — ID tokendagi `sub`: odamning o'zgarmas Google ID'si.
  Email o'zgarishi mumkin, shuning uchun «bitta odam — bitta kabinet»
  qoidasi shunga bog'lanadi.

## 0.2.0 — 2026-09-19

Mijozning o'z jadvaliga yozish uchun.

### Qo'shildi
- `SheetsClient.add_tab`: mavjud faylga sarlavhali varaq, bitta so'rovda.
  Varaq ID si oldindan tanlanadi, shuning uchun sarlavhasiz varaq hech
  qachon qolmaydi.
- `SheetsClient.file_info` va `DriveFile`: fayl savatchadami, jadvalmi,
  tahrirlash mumkinmi. Yozishni to'xtatadigan uch holat ekranda uch xil
  jumla bo'ladi.
- `Tab` va `Spreadsheet.tabs` / `titles`: varaq nomlari — band nomga
  ikkinchi varaq qo'shib bo'lmaydi.
- Drive chaqiruvlarida `supportsAllDrives=true`: umumiy diskdagi fayllar.
- `TabMissing` (`SheetMissing` ning bolasi): fayl joyida, yoziladigan
  varaq o'chirilgan. Tuzatish boshqa — varaqni o'sha faylga qayta qo'shsa
  bo'ladi, faylni esa yo'q.

### O'zgardi
- `Spreadsheet.sheet_ids` endi `tabs` dan hisoblanadigan xossa.

## 0.1.0 — 2026-09-10

Birinchi reliz: lidlarni mijozning o'z Google jadvaliga yozish uchun.

### Qo'shildi
- `oauth`: consent havolasi (`access_type=offline` + `prompt=consent` —
  ikkinchi ulanishda ham refresh token kelishi uchun), kodni tokenga
  almashtirish, refresh va revoke. Email alohida so'rov bilan emas,
  token javobidagi ID tokendan o'qiladi.
- `SheetsClient`: jadval yaratish, pastiga qator qo'shish, yangi ustun
  sarlavhalari, birinchi ustunni o'qish va savatchani tekshirish. Varaqqa
  hamma murojaat nomi bilan emas, `sheetId` bilan — foydalanuvchi varaqni
  qayta nomlasa ham yozish to'xtamaydi.
- Matnli katak doim `stringValue`: `=` bilan boshlangan javob formula
  bo'lmaydi, `+` bilan boshlangan telefon raqamga aylanmaydi.
- Xatolar chaqiruvchi nima qilishi bo'yicha ajratilgan: `AccessRevoked`,
  `PermissionMissing`, `SheetMissing`, `RateLimited`, `Unavailable` va
  `OutcomeUnknown` (so'rov ketgan, javob kelmagan — yozuv bo'lgan bo'lishi
  mumkin). 401 vaqtinchalik hisoblanadi: grant o'lganini faqat refresh
  aytadi.
- Ruxsat faqat `drive.file`: ilova faqat o'zi yaratgan faylni ko'radi.
- Yangi savol ustuni `insertDimension` bilan qo'yiladi: foydalanuvchi
  bizning ustunlardan keyin qo'shgan o'z ustuni o'ngga suriladi va
  saqlanadi, ustidan yozilmaydi.
- Varaq ID (`sheetId`) paketdan tashqarida string: `Spreadsheet.sheet_ids`,
  `append`, `add_columns`, `first_column`. Son faqat so'rov tanasida
  quriladi.
- 403 `accessNotConfigured` / `SERVICE_DISABLED` (Cloud loyihada API
  o'chiq) — `GoogleAPIError`, `PermissionMissing` emas: bu mijozning
  ruxsati emas, bizning sozlama.
- Katak shakllari (`serial`, matnli katak, sana formati) — `cells.py` da.
