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
| `developer` | Dasturchiga berildi | yo'q | `to_developer`, izoh majburiy |
| `confirming` | Tasdiq kutilmoqda | yo'q | `resolve`, izoh majburiy |
| `resolved` | Hal qilindi | ha | mijoz «Ha» dedi |
| `closed` | Yopildi | ha | mijoz 24 soat javob bermadi |

Tugmalar (`actions` ro'yxati backenddan keladi, front o'zi hisoblamaydi):

| Ustun | Tugmalar |
|---|---|
| `new` | `start` |
| `in_progress` | `wait`, `to_developer`, `resolve`, `release` |
| `waiting` | `start`, `resolve`, `release` |
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

## 4. Kutish taymeri

`wait` tugmasi vaqt so'raydi (`due_at`, majburiy). Vaqt kelganda zayavka o'zi `Ishlanmoqda` ga qaytadi, tarixga «Kutish vaqti tugadi» (`wait_over`) yoziladi. Mijoz Yordam chatiga yozsa, avvalgidek darhol qaytadi.

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

Yopilgan (`resolved`, `closed`) yoki tasdiq kutayotgan zayavkaga yangi sabab kelsa, u qayta ochiladi va o'sha xodimga qaytadi.

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

1. `alembic upgrade head` (0052).
2. `api`, `worker-bot`, `beat` ni qayta ishga tushirish.
3. Front (ofis va kabinet) shu bilan birga chiqadi.

Tekshirilmagan: haqiqiy Telegram (support bot va asosiy botdagi tugmalar), production ma'lumotlari.
