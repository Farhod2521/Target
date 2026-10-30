# googleadskit — o'zgarishlar tarixi

Semantik versiyalash. Google Ads API versiyasi (`v25`) paket versiyasidan
alohida — u `client.py` dagi `API_VERSION` konstantasida.

## 0.8.0 — 2026-10-30

### Qo'shildi
- `GoogleAudiences.read_targeting`, `same_targeting` — `adskit` 0.25.0
  porti uchun; ikkalasi ham `PortNotAvailable`.

## 0.7.0 — 2026-10-16

### Qo'shildi
- `GoogleCampaigns.read_objects` (`adskit` 0.24.0) — har daraja uchun bitta
  GAQL so'rovi, `resource_name IN (...)` bo'yicha.

## 0.6.0 — 2026-10-08

### Qo'shildi
- `GoogleMetrics.fetch_people` — hozircha bo'sh ro'yxat; ekranlar kunlik
  qatorlarga qaytadi.

## 0.5.0 — 2026-10-02

### Qo'shildi
- `GoogleCampaigns.set_budget` — kampaniya byudjetining summasi joyida
  o'zgaradi (yangi byudjetga ko'chirilmaydi: Google shuni tavsiya qiladi,
  ko'chirish o'sha kungi sarfni unutadi). Faqat kampaniya darajasida.
- `GoogleCampaigns.delete` — obyekt butunlay o'chiriladi (`remove`).
- Kampaniya o'qilganda `shared_budget_id` (umumiy byudjet) va «byudjet
  yetmayapti» (`BUDGET_CONSTRAINED`) tavsiya sifatida.

### O'zgardi
- Yangi qidiruv kampaniyasi faqat hududda turganlarga ko'rsatiladi
  (`PRESENCE`), Google'ning «qiziqqanlar ham» defaulti emas.
- Yozuvlar `writes.py` ga, qatorlarni o'qish `rows.py` ga ajratildi.

## 0.4.1 — 2026-10-02

### Qo'shildi
- `country_target(client, customer_id, country_code)` — butun mamlakatning
  geo target'i ISO kodi bo'yicha (GAQL, nom qidiruvi emas).

## 0.4.0 — 2026-10-02

Qidiruv kampaniyasini yaratish uchun asboblar (port emas — Google'ning
o'z ketma-ketligi).

### Qo'shildi
- `launch`: `SearchCampaignSpec` (Google chegaralari oldindan tekshiriladi:
  3–15 sarlavha ≤30, 2–4 tavsif ≤90, kalit so'z ≤80 belgi/10 so'z, sayt
  majburiy, kamida bitta joy) va `create_search_campaign` — butun kampaniya
  bitta `googleAds:mutate` so'rovida, vaqtinchalik manfiy ID'lar bilan:
  yo hammasi, yo hech narsa. `validate_only` = Google'ning `validateOnly`.
  Qat'iy shakl: faqat Google qidiruv, «Ko'proq bosish» (`targetSpend`),
  ibora/aniq moslik, EU siyosiy reklama «yo'q», til cheklovi yo'q, darrov
  yoqilgan. Telefon berilsa — call asset kampaniyaga bog'lanadi.
- `GoogleAudiences` (`AudiencePort`): `find_locations`
  (`geoTargetConstants:suggest`, inglizcha nomlar). Qolgan metodlar Meta
  shaklida — `PortNotAvailable`.
- `keywords`: `keyword_volumes` (aniq kalit so'zlar uchun oylik qidiruv
  soni) va `keyword_ideas` (o'xshash so'zlar). Til yuborilmaydi — barcha
  tillar hisoblanadi.

## 0.3.0 — 2026-10-02

Kampaniyalar va kunlik raqamlar portlar orqali.

### Qo'shildi
- `GoogleCampaigns` (`CampaignControlPort`): kampaniya, reklama guruhi va
  reklamalar ro'yxati (o'chirilganlar — `REMOVED` — kirmaydi), `get_status`
  va `set_status`. `dry_run` — Google'ning `validateOnly`: so'rov to'liq
  tekshiriladi, hech narsa o'zgarmaydi. `count_adsets`, `get_preview`,
  `set_budget`, `set_end_time`, `set_spend_cap`, `delete` hozircha
  `PortNotAvailable` bilan rad etadi.
- `GoogleMetrics` (`MetricsPort`): kampaniya / guruh / reklama darajasida
  kunlik raqamlar. Pul micros'dan minor birlikka (`adskit.money`), CTR
  foizga. Google konversiyalari `results_reported` ga tushadi, hech qachon
  lidga emas. `fetch_breakdown` hozircha bo'sh ro'yxat qaytaradi (tungi sinxron har kecha «tugamadi» demasligi uchun).
- `resources`: ID — Google'ning resource name'i
  (`customers/{id}/campaigns/{id}`), chunki har chaqiruv mijoz ID sini
  talab qiladi va port faqat ref'ni uzatadi.
- Ikkala port ham `http=` qabul qiladi (test yoki umumiy pul).

## 0.2.0 — 2026-10-01

Google ulanishi `ConnectPort` sifatida.

### Qo'shildi
- `GoogleConnect(client_id=, client_secret=)` — rozilik oynasi
  (`openid email adwords`), kodni almashtirish va saqlangan refresh tokendan
  bir soatlik access token. Saqlanadigan narsa refresh token; odam `sub`
  bilan nomlanadi (email emas — u o'zgarishi mumkin).
- `googleadskit.adapter.bundle()` — registry uchun. Hozircha faqat `connect`
  haqiqiy, qolgan portlar `Unavailable` bilan nomi aytib rad etadi.
- Bog'liqlik: `googlekit` (Google'ning bitta OAuth kodi).

## 0.1.0 — 2026-10-01

Birinchi reliz: klient, xatolar va akkauntlar ro'yxati.

### Qo'shildi
- `AdsClient(token=, login_customer_id=)` — REST + httpx. `get`, `post` va
  `search` (GAQL, `nextPageToken` bo'yicha sahifalab). Developer token
  yuborilmaydi: 2026-09-09 dan beri ruxsat darajasi Cloud loyihasiga
  tegishli va Google bu sarlavhani e'tiborsiz qoldiradi.
- Xatolar: `GoogleAdsUnreachable` (so'rov yetib bormadi, qayta yuborish
  xavfsiz), `GoogleAdsOutcomeUnknown` (so'rov ketdi, javob kelmadi),
  `GoogleAdsAPIError` (Google rad etdi; HTTP holati, gRPC holati, sabablar
  ro'yxati, `requestId`, kvota uchun `retryDelay`).
- `translate_error` — Google xatosini `adskit` xatosiga o'giradi. Cloud
  loyihasi sozlamasidan kelgan rad etish `InvalidRequest` (mijozniki emas),
  yopilgan yoki to'liq ochilmagan akkaunt `AccountActionRequired`.
- `list_customer_ids`, `describe_customer`, `list_accounts` — grant to'g'ridan
  -to'g'ri yetadigan akkauntlar: nomi, valyutasi, vaqt zonasi, manager yoki
  test akkaunt ekani va holati. Ochilmaydigan eski akkaunt ro'yxatni
  yiqitmaydi, tashlab ketiladi.
