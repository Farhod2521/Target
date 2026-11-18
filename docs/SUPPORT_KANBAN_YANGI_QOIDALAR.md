# Support kanbani: yangi qoidalar (2026-11-13)

Bu hujjat `OFFICE_V2_API.md` va `FRONTEND_KANBAN_MUDDAT.md` dagi Support qismini
almashtiradi. Sotuv doskasida o'zgarish yo'q, faqat 6-bo'limdagi uch tuzatish.

Migratsiya: `0052` (uchta ustun). Backend va front birga chiqariladi.

## 1. Kim nimani ko'radi

| Kim | Ko'radi |
|---|---|
| Support xodimi | Faqat o'ziga biriktirilgan zayavkalar. Navbatni (`Yangi`, mas'ulsiz) ko'rmaydi |
| Owner, superuser | Hamma zayavka, filtrlar bilan |

Birovning zayavkasi Support xodimiga `404` qaytaradi (ro'yxat, karta, izoh, muddat, tugmalar).

## 2. Ustunlar

| Kod | Nomi | Yakuniy | Qanday tushadi |
|---|---|---|---|
| `new` | Yangi | yo'q | zayavka ochilganda |
| `in_progress` | Ishlanmoqda | yo'q | «Zayavka olish», «Ishlayapman» |
| `waiting` | Mijoz kutilmoqda | yo'q | `wait`, vaqt majburiy |
| `unreachable` | Bog'lanib bo'lmadi | yo'q | `unreachable`, sabab majburiy (§4a) |
| `developer` | Dasturchiga berildi | yo'q | `to_developer`, izoh majburiy |
| `confirming` | Tasdiq kutilmoqda | yo'q | `resolve`, izoh majburiy |
| `resolved` | Hal qilindi | ha | mijoz «Ha» dedi |
| `closed` | Yopildi | ha | mijoz 24 soat javob bermadi |

Tugmalar (`actions` ro'yxati backenddan keladi, front o'zi hisoblamaydi):

| Ustun | Tugmalar |
|---|---|
| `new` | `start` |
| `in_progress` | `wait`, `unreachable`, `to_developer`, `resolve`, `release` |
| `waiting` | `start`, `unreachable`, `resolve`, `release` |
| `unreachable` | `start`, `release` |
| `developer` | `start`, `resolve` |
| `confirming`, `resolved`, `closed` | `reopen` |

## 3. «Zayavka olish»

`POST /api/v2/office/support/take` — tanasi yo'q, javob `CardDetailOut`.

- Bir bosishda bitta zayavka: `Yangi` da eng uzoq kutgan, mas'ulsiz zayavka. U xodimga biriktiriladi va `Ishlanmoqda` ga o'tadi.
- Xodimning `Ishlanmoqda` dagi zayavkalari 5 ta bo'lsa: `409 take_limit`.
- Navbat bo'sh bo'lsa: `409 no_ticket_to_take`.
- Kimda bor: `me.can.take_ticket` (Support, Owner, superuser).

Limit faqat `Ishlanmoqda` ni sanaydi. Quyidagilar limitdan oshsa ham o'tadi: Owner bergan zayavka, taymer tugab qaytgani, mijoz «Yo'q» degani, xodimning o'z zayavkasidagi «Ishlayapman».

`GET /api/v2/office/boards/support` javobida yangi maydon:

```json
"take": {"queue": 12, "working": 3, "limit": 5}
```

`queue` — navbatdagi mas'ulsiz zayavkalar, `working` — o'quvchining `Ishlanmoqda` dagilari. Sotuv doskasida `take: null`.

### 3a. Zayavka turlari (2026-11-18, migratsiya 0066)

Har bir Support xodimiga zayavka turlari belgilanadi: tur — zayavka kelgan sabab (`setup` Sozlash tugamadi, `from_sales`, `meta_error`, `survey`, `idle`, `ai`, `manual`). Default: hech narsa belgilanmagan = **hamma tur**.

- «Zayavka olish» avval xodimning o'z turidagi eng uzoq kutganini beradi; o'z turidan hech biri qolmasa — istalgan turdagi eng uzoq kutganini (ogohlantirishsiz).
- Zayavkada bir nechta ochiq sabab bo'lsa, ulardan biri xodimning turi bo'lsa — uniki. Olgan xodim hammasini hal qiladi.
- Hal qilingan sabab turga kirmaydi: faqat ochiq sabablar sanaladi.
- Owner va superuserning o'zi «Zayavka olish» bossa — hamma tur.

`take` da yangi maydon `own`: `queue` ning o'quvchi turiga tegishlilari (hamma turli xodimda `own == queue`).

```json
"take": {"queue": 12, "own": 4, "working": 3, "limit": 5}
```

Sozlamalar (faqat Owner va superuser, boshqalarga **404**):

- `GET /api/v2/office/boards/support/kinds` →
  `{"kinds": [{"value": "setup", "label": "Sozlash tugamadi"}, …], "members": [{"id", "name", "email", "kinds": ["setup", "ai"], "all": false}]}`.
  `members` — faol Support xodimlari; `all: true` — hech narsa belgilanmagan (hamma tur, keyin qo'shiladigan tur ham).
- `PUT /api/v2/office/boards/support/kinds/{member_id}` body `{"kinds": ["setup", "meta_error"]}` → bitta xodimning qatori (yuqoridagi shaklda).
  Hamma tur belgilansa `all: true` bo'lib saqlanadi. Bo'sh ro'yxat: **422** `no_kind_chosen`; noma'lum tur: **422** `unknown_kind`; Support xodimi emas: **404** `not_found`.

### 3b. Kunlik hisobot (2026-11-19)

`GET /api/v2/office/boards/support/report?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` (ikkalasi bo'sh — bugun; ko'pi bilan 1 yil, aks holda **422** `report_period_invalid`). Support xodimi faqat o'z qatorini, Owner va superuser hamma Support xodimini (va davrda zayavka bilan ishlagan boshqa xodimni ham) ko'radi; boshqalarga **404**.

Har bir qator (`total` va `days[]`, kunlar Toshkent vaqti bilan, faqat ish bo'lgan kunlar, yangisi birinchi):

| Maydon | Ma'nosi |
|---|---|
| `talked` | Gaplashgan har xil mijozlar: chatda yozgan yoki zayavkasida izoh, «Mijoz kutilmoqda», «Dasturchiga berish», «Hal qilindi» bosgan. Zayavka olish, voz kechish, «Bog'lanib bo'lmadi» — gaplashish emas. Qo'ng'iroqlar hozircha kirmaydi. |
| `messages` | Chatda yozgan xabarlari |
| `taken` | «Zayavka olish» bilan olgani |
| `solved` | «Hal qilindi» bosgani |
| `confirmed` / `denied` | Mijoz «Ha» / «Yo'q» degani — oxirgi «Hal qilindi» bosgan xodimga yoziladi |

Javob: `{"date_from", "date_to", "total": {...}, "members": [{"id", "name", "email", "total": {...}, "days": [{"day", ...}]}]}`. Davr bo'yicha `talked` har mijozni bir marta sanaydi.

### 3c. Staff botda xabarlar (2026-11-19)

Zayavka egasi (kartadagi `manager`) staff botda xabar oladi, agar:

- zayavka unga berilsa (Owner «Berish» yoki chat bilan birga);
- «Mijoz kutilmoqda» vaqti tugab qaytsa;
- mijoz chatga yozib qaytsa;
- mijoz «hal bo'lmadi» desa;
- ushlab turgan zayavkasiga yangi muammo kelsa;
- zayavka uning uchun qayta ochilsa.

O'zi qilgan ish haqida xabar bormaydi, egasiz zayavka (navbatdagi) haqida ham. Har daqiqalik tekshiruv bir zayavka bo'yicha bitta xabar yuboradi (qatorlari birga), har hodisa bir marta (`board_card_events.noticed_at`); bir soatdan eski hodisa yuborilmaydi. Staff bot ulanmagan xodimga xabar bormaydi.

Mijozning chat xabari nusxasi: ochiq zayavkasi kimda bo'lsa faqat o'shanga; hech kimda bo'lmasa yoki u staff botni ulamagan bo'lsa — hamma Support xodimiga (avvalgidek).

### 3d. «Dasturchiga berish» va «Tuzatildi» (2026-11-19)

- `to_developer` (izoh majburiy) zayavkani «Dasturchiga berildi»ga o'tkazadi va Developer sahifasida xato ochadi (`/api/v1/office/faults`, `url` = `ticket:<karta id>`, sarlavha «Support zayavkasi — Support dasturchiga berdi»). Ichida: Support izohi, ochiq muammolar va Meta'ning asl matni. Staff botda Engineer'ga boshqa xatolar kabi xabar boradi. 6 belgili raqam zayavka tarixidagi «Dasturchiga berildi» qatoriga yoziladi.
- Engineer `POST /api/v1/office/faults/{ref}/settle` («Tuzatildi — zayavkani yopish») bosganda: zayavka «Dasturchiga berildi»da bo'lsa, ochiq muammolar Engineer nomidan hal qilinadi va zayavka **«Hal qilindi»** ustuniga o'tib yopiladi (mijozdan so'ralmaydi). Tarixda `dev_fixed` («Dasturchi tuzatdi»), zayavka egasiga staff botda xabar boradi. Support zayavkani oldinroq ishga qaytarib olgan bo'lsa, u joyida qoladi, faqat tarixga `dev_fixed` yoziladi.

### 3e. «Bog'lanib bo'lmadi»da qayta qo'ng'iroq vaqti (2026-11-19)

`unreachable` endi `due_at` ni ixtiyoriy oladi (tugma `due: "optional"`). Vaqt kelganda zayavka o'zi `in_progress` ga, o'sha xodimga qaytadi: tarixda `call_again` («Qayta qo'ng'iroq vaqti keldi»), staff botda xabar. Vaqtsiz bo'lsa avvalgidek: mijoz yozmaguncha turadi.

### 3f. Chat va yakuniy ustunlar (2026-11-19)

- `GET /api/v1/office/support` qatorlari va `GET /api/v1/office/support/{id}` da `ticket`: `{id, column, column_label, manager, mine, closed}` yoki `null` (zayavka bo'lmagan).
- Support kanbanida «Hal qilindi» va «Yopildi» faqat oxirgi 7 kunni sanaydi va ko'rsatadi (`columns[].recent_days = 7`); qidiruvda hammasi chiqadi (`recent_days: null`).

## 4. Kutish taymeri

`wait` tugmasi vaqt so'raydi (`due_at`, majburiy). Vaqt kelganda zayavka o'zi `Ishlanmoqda` ga qaytadi, tarixga «Kutish vaqti tugadi» (`wait_over`) yoziladi. Mijoz Yordam chatiga yozsa, avvalgidek darhol qaytadi.

## 4a. «Bog'lanib bo'lmadi» (2026-11-17, migratsiya 0062)

Mijoz bilan bog'lanish imkoni yo'q (raqam xato, Telegramdan javob yo'q). Qayta qo'ng'iroq qilish — bu `waiting`, bu ustun emas.

- Tugma `unreachable`: `reason` — sabab `id` si, majburiy; `note` ixtiyoriy. Sabab yo'q yoki arxivda: `422 contact_reason_required`. Tarixga «Sabab. Izoh» bo'lib yoziladi, `due_at` olib tashlanadi.
- Karta `unreachable_reason` — sabab nomi; zayavka ustundan chiqishi bilan bo'shaydi.
- «Ko'chirish» (`POST /api/v2/office/cards/{id}/move`, Owner/superuser) bilan shu ustunga: `contact_reason` — sabab `id` si, majburiy (aks holda `422 contact_reason_required`). Tarixga «Sabab. Ko'chirish izohi». Boshqa ustunlarga `contact_reason` e'tiborsiz.
- Bu ustundagi zayavka 5 talik limitga kirmaydi. Mijoz Yordam chatga yozsa, zayavka o'zi `in_progress` ga, o'sha xodimga qaytadi.
- Sabablar ro'yxati — `GET /api/v2/office/boards/support/contact-reasons` → `{rows: [{id, name, position, is_archived}], may_edit}`. Support faqat faollarini ko'radi; Owner va superuser arxivdagilarini ham ko'radi va tahrirlaydi:
  - `POST .../contact-reasons` `{name, position?}` → `201`;
  - `PUT .../contact-reasons/{id}` `{name, position}`;
  - `POST .../contact-reasons/{id}/archive`, `.../restore`.
  Boshqalar uchun `403`. Sabab o'chirilmaydi, faqat arxivlanadi.
- Migratsiya ikki sabab yozadi: «Telefon raqam xato», «Telegramdan bog'lanib bo'lmadi».

## 5. Yopilishni mijoz tasdiqlaydi

1. Xodim `resolve` bosadi → zayavka `Tasdiq kutilmoqda` ga o'tadi (hali yopilmagan).
2. Bir daqiqa ichida mijozga «Muammoyingiz hal bo'ldimi?» savoli «Ha, hal bo'ldi» / «Yo'q» tugmalari bilan boradi: support botga; u ulanmagan bo'lsa asosiy botga. Qayerga ketgani tarixda yoziladi (`asked`).
3. Savol saytda ham turadi (kabinetning har sahifasida banner), javob berilguncha.
4. «Ha» → `Hal qilindi`. «Yo'q» → o'sha xodimga, `Ishlanmoqda` ga. 24 soat javob yo'q → `Yopildi`.

Mijoz tomoni (kabinet, `Authorization` mijozniki):

| So'rov | Javob |
|---|---|
| `GET /api/v2/support-ticket` | `{"question": {"asked_at", "expires_at"} \| null}` |
| `POST /api/v2/support-ticket/answer` `{"solved": true}` | `{"result": "solved" \| "reopened" \| "stale"}` |

`stale` — savolga javob berilgan yoki u endi so'ralmayapti; xato emas.

Tasdiq kutayotgan (`confirming`) yoki to'liq yopilgan (`resolved`, `closed`) zayavkaga yangi sabab kelsa, u xodimsiz «Yangi» navbatiga tushadi (keyingi «Zayavka olish» bosganga, turiga qarab, beriladi; 2026-11-18 dan `confirming` ham shunday). Oldingi xodim hal qilgan sabablar uning nomi bilan hal qilingan bo'lib qoladi; mijozga yuborilgan «Hal bo'ldimi?» savoli endi o'tmaydi. Mijozning o'z tugmasidagi Meta xatosi va chatdagi oddiy xabari yopilgan zayavkani ochmaydi: Meta xatosi tarixga `after_close` («Yopilgandan keyin keldi») bo'lib yoziladi. Support xodimi yopilgan zayavkani qo'lda ochsa, u o'ziga tushadi.

## 6. Zayavkani qo'lda ochish

`POST /api/v2/office/boards/support/cards` `{"user_id", "note", "staff_id"?}`

- `note` majburiy.
- Owner / superuser: `staff_id` bilan Support xodimini tanlaydi (limitga qaramaydi); zayavka o'sha xodimning `Yangi` sida turadi. `staff_id` siz navbatga tushadi.
- Support xodimi: zayavka o'ziga biriktiriladi va `Ishlanmoqda` ga tushadi. Limit to'lgan bo'lsa `409 take_limit`; mijoz bilan boshqa xodim ishlayotgan bo'lsa `409 ticket_held`.
- Xodimlar ro'yxati: `GET /api/v2/office/boards/support/staff` (faqat Owner / superuser).

Frontda bu ofisdagi mijoz sahifasida ham bor: «Zayavka ochish» tugmasi (xodim tanlash + izoh).

## 7. Sotuv bilan Support orasidagi tuzatishlar

- Sotuvdan o'tgan zayavka sababida endi menejer ismi va uning oxirgi 5 ta izohi turadi.
- Ofisdan to'lovsiz berilgan tarif: lid `Sotildi` ga o'tadi (tarixda «Tarif ofisdan berildi, to'lovsiz»), bir soatda sozlash tugamasa Support zayavkasi ochiladi.
- «To'lagan» hamma joyda tarif to'lovi degani: faqat qo'shimcha sahifa yoki o'rin sotib olgan ro'yxatdan o'tuvchi lid bo'lib qoladi.

## 8. Deploy

1. `alembic upgrade head` (0052; 2026-11-19 dan 0066 — zayavka turlari, `noticed_at`, `created_at` indeksi).
2. `api`, `worker-bot`, `beat` ni qayta ishga tushirish.
3. Front (ofis va kabinet) shu bilan birga chiqadi.

Tekshirilmagan: haqiqiy Telegram (support bot va asosiy botdagi tugmalar), production ma'lumotlari.
