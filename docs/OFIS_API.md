# Ofis API — frontend uchun qo'llanma

Xodimlar paneli (ofis) uchun to'liq API ma'lumotnomasi: har bir yo'l, rol,
filtr, qidiruv, sahifalash va maydon. Bu fayl o'z-o'zicha yetarli.

- **Qo'lda yozilgan qismlar** (1–10-bo'limlar) ekranlar qanday ishlashini aytadi.
- **A-ilova** — barcha yo'llar ro'yxati, **B-ilova** — har bir so'rov va javob
  maydoni. Ilovalar kodning OpenAPI sxemasidan yaratilgan, maydon izohlari
  shuning uchun inglizcha.

Swagger: backend'ning `/docs` sahifasi, `office` va `sales` bo'limlari.

---

## 0. Umumiy qoidalar

| Narsa | Qiymat |
|---|---|
| Prefiks | Hamma yo'l `/api/v1/office` ostida. Bu faylda yo'llar qisqa yozilgan: `/customers` = `/api/v1/office/customers` |
| Avtorizatsiya | `Authorization: Bearer <access_token>` |
| Format | JSON. Fayl yuboriladigan chat yo'llari `multipart/form-data` |
| Sana-vaqt | ISO 8601, UTC. Filtrdagi sana `YYYY-MM-DD` |
| Pul | `*_minor` — butun son, eng kichik birlikda (tiyin yoki sent). Valyutalar hech qachon qo'shilmaydi, shuning uchun summalar `[{currency, amount_minor}]` ro'yxati bo'lib keladi |
| Foiz | `ctr_percent` — tayyor matn (`"4.00"`); bo'sh satr hisoblab bo'lmaganini bildiradi |
| Server matnlari | `detail`, `message`, `label`, `hint` o'zgarishsiz ko'rsatiladi, frontend tarjima qilmaydi |
| Tanlov ro'yxatlari | `periods[]`, `states[]`, `sorts[]`, `plans[]`, `kinds[]` kabilar javobda keladi: `{value, label}`. Filtr chiplarini shulardan chizing, qattiq yozmang |

**Token.** `401` kelsa `POST /api/v1/auth/refresh` (`{"refresh_token": "..."}`)
yangi juftlik beradi. U ham `401` bersa — login sahifasiga.

**Xatolar:**

| Status | Ma'nosi | Nima qilish kerak |
|---|---|---|
| `400` | Qoida buzildi | `detail`ni ko'rsating, `code` bo'yicha tarmoqlang |
| `401` | Token yo'q yoki eskirgan | Refresh |
| `404` | Topilmadi **yoki ruxsat yo'q** | Ofisda ruxsat yo'qligi ham `404` |
| `409` | Holat to'g'ri kelmaydi | `detail`ni ko'rsating |
| `422` | Maydon xatosi | Pastdagi ikki shakldan biri |
| `429` | Juda ko'p urinish | Kutib qayta urinish |

```json
{"detail": "Bu so'rov allaqachon hal qilingan", "code": "..."}
```

`422` ikki xil keladi. `detail` matn bo'lsa, `problems` kalitlari — maydon nomlari:

```json
{"detail": "...", "code": "invalid_input", "problems": {"code": "..."}}
```

`detail` massiv bo'lsa — FastAPI tekshiruvi:

```json
{"detail": [{"loc": ["body", "reason"], "msg": "...", "type": "value_error"}]}
```

---

## Filtr, qidiruv va sahifalash — bir qarashda

| Yo'l | Qidiruv | Filtrlar | Tartib | Sahifalash |
|---|---|---|---|---|
| `GET /customers` | `q` | `state`, `plan`, `joined_from`, `joined_to`, `manager` | `sort` | `offset` + `as_of`, 50 tadan |
| `GET /customers/{id}/ads` | — | `period`, `since`, `until` | yangisi birinchi | yo'q |
| `GET /customers/{id}/ads/{launch_id}` | — | `period`, `since`, `until`, `bar` | — | yo'q |
| `GET /journal` | — | `kind` | yangisi birinchi | `offset`, 50 tadan |
| `GET /promo` | `q` | `tab` | navbat: eskisi birinchi; `answered`: yangisi birinchi | `offset`, 20 tadan |
| `GET /support` | — | `state` | `waiting`: eng uzoq kutgan birinchi; `all`: yangisi birinchi | `offset`, 20 tadan |
| `GET /support/{id}` | — | — | — | `page`, bo'sh = eng yangi sahifa |
| `GET /dashboard` | — | `period`, `since`, `until` | — | yo'q |
| `GET /dashboard/takings` | — | `period`, `since`, `until`, `bar` | — | yo'q |
| `GET /payments/invoices` | `q` | `state` | yangisi birinchi | `offset`, 50 tadan |
| `GET /payments/subscriptions` | `q` | `state` | eng tez tugaydigani birinchi | `offset`, 50 tadan |
| `GET /sales` va doska yo'llari | `q` | `g`, `m` | qo'lda: `POST /sales/order` | ustun 40 tagacha |
| `GET /sales/pool` | `q` | `g`, `m` | — | `offset` = `pool_next`, 40 tadan |
| `GET /sales/holds` | — | — | — | `page`, 50 tadan |
| `GET /sales/report` | — | `oy`, `m` | — | yo'q |

Sahifalash ikki xil:
- **`offset`:** keyingi sahifa uchun javobdagi `next_offset` (`has_more` `true`
  bo'lsa) yuboriladi. Mijozlar ro'yxatida birinchi javobdagi `as_of` ham
  qaytariladi, shunda ro'yxat varaqlash davomida siljimaydi.
- **`page`:** oddiy sahifa raqami.

Davr filtri uch joyda bor, qiymatlari farq qiladi:

| Yo'l | `period` qiymatlari | Standart |
|---|---|---|
| `/customers/{id}/ads...` | `today`, `7`, `month`, `30`, `all`, `range` | `month` |
| `/dashboard...` | `today`, `7`, `30`, `month`, `year`, `range` | `30` |

`range`da `since` va `until` majburiy. Noto'g'ri bo'lsa standart davr o'qiladi
va sababi `window.refused`da keladi — uni xabar sifatida ko'rsating. Noma'lum
`period` standart davrga aylanadi, xato qaytmaydi. Javobdagi `window` qaysi
davr haqiqatda o'qilganini aytadi.

---


## 1. Rollar va ruxsat

| Rol | Kod |
|---|---|
| Qo'llab-quvvatlash | `Support` |
| Moliya | `Finance` |
| Developer | `Engineer` |
| Egasi | `Owner` |
| Sotuv menejeri | `Sales` |
| Sotuv boshlig'i | `SalesLead` |

- Ruxsati yo'q xodim (yoki oddiy mijoz) so'rasa — **`404`**, `403` emas.
  Ruxsat bo'lmagan tugma chizilmaydi.
- Superuser hamma rolga ega.

### `GET /me`

Har ekran ochilishida. Menyu va tugmalar shundan chiziladi.

```json
{
  "user": {"id": "…", "name": "Aziz", "email": "aziz@…"},
  "roles": [{"value": "Support", "label": "Qo'llab-quvvatlash"}],
  "can": {
    "give": true,            // tarif, kun, o'rin, to'lov, referal
    "grant": false,          // pul: hamyon, promo kodlar
    "owner": false,          // jamoa, jurnal, To'lovlar, sahifa qo'shish, mijozni o'chirish
    "superuser": false,      // mijoz parolini o'rnatish, hisobni bo'shatish
    "engineer": false,
    "answer_support": true,
    "answer_feedback": false,
    "sell": false,
    "lead_sales": false
  },
  "waiting": {"promos": 2, "asks": 0, "feedback": 0, "support": 5, "arizas": 0}
}
```

`waiting` — menyu yonidagi raqamlar. Eshigi yo'q bo'lim uchun `0`.
`can` qiymatlari bo'yicha menyu va tugmalar chiziladi; ruxsat bo'lmagan yo'l `404` qaytaradi.

### `GET /journal?kind=&offset=` — faqat Owner

Xodimlar amallari, yangisi birinchi, 50 tadan. `kind` bo'sh bo'lsa faqat
amallar (karta ochilgani kabi o'qishlar yashirin). `kinds[]` — filtr chiplari.

---

## 2. Mijozlar ro'yxati — `GET /customers`

Support, Finance, Owner. Xodimlar va CRM menejer loginlari chiqmaydi.

| Parametr | Ma'nosi |
|---|---|
| `q` | Email, ism, telefon, hisob raqami (`TA-…`), reklama akkaunti yoki sahifa ID |
| `state` | `trouble`, `trial`, `active`, `expiring`, `lapsed`, `never` (`states[]`) |
| `plan` | Tarif kodi (`plans[]`) |
| `joined_from`, `joined_to` | `YYYY-MM-DD`, ofis vaqti, ikkalasi ham kiradi |
| `manager` | Sotuv menejeri ID yoki `none` (`managers[]`) |
| `sort` | bo'sh (holatga qarab), `joined`, `expires`, `last_login` (`sorts[]`) |
| `offset` | Keyingi sahifa: javobdagi `next_offset` |
| `as_of` | Keyingi sahifada birinchi javobdagi `as_of` ni qaytaring |

Qator (`rows[]`):

| Maydon | |
|---|---|
| `customer` | `id`, `name`, `email`, `phone` |
| `is_blocked`, `joined_at`, `last_login_at` | |
| `business` | `name`, `direction` |
| `term` | `state` (`trial`/`active`/`lapsed`/`never`), `label`, `plan`, `days_left`, `expires_at`, `ended_on` |
| `trouble` | Eng yomon muammo: `kind`, `label`, `what`, `urgent`, `since` yoki `null` |
| `pages` | `used` / `allowed` (`allowed` faqat aktiv tarifda) |
| `running` | Hozir ishlayotgan kampaniyalar (faqat platformada yaratilgan) |
| `spend`, `leads` | Shu oy; sarf valyuta bo'yicha `[{currency, amount_minor}]` |
| `paid_total` | Jami to'lagan, valyuta bo'yicha |
| `paid_before` | O'chirilgan akkaunt shu email bilan to'lagan — kartada eski cheklar bor |
| `sales_manager` | Ochiq sotuv kartasi menejeri yoki `null` |

Muammo turlari (`trouble.kind`): `connection` (Facebook uzilgan),
`account_blocked`, `payment_due` (Meta'da qarz), `lead_gap`, `sweep`,
`launch`, `hold`, `expiring`, `setup`. `urgent: true` — qizil.

---

## 3. Mijoz kartasi — `GET /customers/{id}`

Ochilishi jurnalga yoziladi (30 daqiqada bir marta). Bloklar:

| Blok | Nima |
|---|---|
| `profile` | Ism, email, telefon, til, ro'yxatdan o'tgan, oxirgi kirish, bloklanganmi, sozlash tugagan vaqt |
| `businesses[]` | Nomi, yo'nalishi, sahifasi, shahar, telefon, sayt |
| `subscription` / `lapsed` | Aktiv obuna, yo'q bo'lsa oxirgisi |
| `limits` | Sahifalar, CRM o'rinlari, ishlayotgan reklama, AI budjeti, bugungi savollar, sinovda qolgan ishga tushirishlar |
| `plan_picker` | Har tarif uchun mijoz to'laydigan summa (`due_minor`), `waits` — arzonroq tarif hozir berilmaydi |
| `meta` | Facebook ulanishi: holat, profil nomi, muddat, oxirgi xato kodi |
| `ad_accounts[]`, `pages[]`, `pixels[]` | Sahifa ichida juftliklar va Instagram akkauntlari |
| `telegram`, `agent` | Bot ulanganmi, AI agent yoqilganmi |
| `money` | Jami to'lov, oxirgi 6 hisob, oxirgi 10 obuna o'zgarishi, eski cheklar |
| `referral` | Rejim, kim taklif qilgan, nechta taklif qilgan, hamyon, oxirgi 6 to'lov |
| `sales` | Ochiq sotuv kartasi, yopilganlar soni, izohlar, qo'ng'iroq taqiqi |
| `problems[]`, `traces[]` | Mijozning barcha muammolari; ofisning oxirgi 6 amali |

Token, parol, fingerprint, karta raqami, Telegram `chat_id` **hech qachon
kelmaydi**.

### `GET /customers/{id}/ads?period=&since=&until=`

`period`: `today`, `7`, `month` (standart), `30`, `all`, `range`. `range`da
`since` va `until` (YYYY-MM-DD) ham yuboriladi; noto'g'ri bo'lsa standart davr
qaytadi va sababi `window.refused`da yoziladi. Faqat platforma yaratgan
kampaniyalar. `all` dan boshqa davrda sarfi, natijasi yo'q va to'xtagan
reklamalar yashiriladi (`hidden` — nechtasi).

| Maydon | Ma'nosi |
|---|---|
| `window` | Haqiqatda o'qilgan davr: `period`, `since`, `until`, `refused`, `periods[]` |
| `running` | Hozir ishlayotgan reklamalar, davrdan qat'i nazar |
| `summary[]` | Har valyuta uchun jami: sarf, ko'rsatish, bosish, lid, CTR, CPM, CPC, lid narxi. Valyutalar qo'shilmaydi |
| `rows[]` | Har kampaniya: nomi, maqsad, holat, sarf, natija, `impressions`, `reach`, `clicks`, `link_clicks`, `leads`, `ctr_percent`, `cpm_minor`, `cpc_minor` |

`reach` — `null` bo'lishi mumkin: shu davr uchun Meta sanamagan.

### `GET /customers/{id}/ads/{launch_id}?period=&since=&until=&bar=`

Bitta reklama to'liq. `period` ro'yxatdagidek. `launch_id` — `rows[]`dagi
qiymat; boshqa mijozniki bo'lsa `404`. `bar`: `day`, `week`, `month`; bo'sh
bo'lsa davr uzunligiga qarab tanlanadi (javobda `bar`, tanlovlar `bars_offered`).

| Maydon | Ma'nosi |
|---|---|
| `row` | Ro'yxatdagi qator. Kampaniya yaratilmagan bo'lsa `null` |
| `campaign` | Meta'dagi kampaniya: nomi, objective, holat, byudjet, muammo |
| `figures` | Davr jamisi: `sums`, `reach`, `result`, `leads`, `qualified`, `synced_at`, `lifetime_leads` (butun davr). Kampaniya yo'q bo'lsa `null` |
| `bars[]` | Grafik uchun kun, hafta yoki oy bo'yicha, eskisi birinchi. Davrda hech narsa bo'lmasa bo'sh |
| `groups[]` | Guruhlar va ichidagi reklamalar: holat, hozirgi auditoriya, davrdagi ko'rsatkichlar |
| `settings` | Ishga tushirishdagi sozlamalar: maqsad, byudjet, muddat, `audience`, tugma, `decisions[]`, `ads[]` |
| `live` | Meta'dagi holat: `status`, `step`, `error`, `delivery_note`, `ads[]`, `forms[]` |
| `siblings[]` | Shu kampaniyaga yozilgan boshqa launch'lar. Sozlamalari o'z `launch_id`si bilan ochiladi |

`sums` barcha joyda bir xil: `spend_minor`, `impressions`, `clicks`,
`link_clicks`, `landing_page_views`, `leads_reported`, `results_reported`,
`recallers`, `profile_visits`, `video_plays`, `video_thruplays`, `reactions`,
`comments`, `shares`, `saves`, `ctr_percent`, `cpm_minor`, `cpc_minor`.
`figures.reach_is_exact: false` bo'lsa "kamida shuncha odam" deb yoziladi.

**Kim tanlagan** — `settings.decisions[]`: `key`, `label`, `value`, `by`
(`ai`, `owner` yoki bo'sh), `by_label`. `key`: `campaign_type`,
`conversion_event`, `audience`, `interests`, `placement`, `form`, `button`.
Forma uchun `value` to'rtta jumladan biri: "AI tayyor formani tanladi",
"Mijoz tayyor formani tanladi", "AI yangi forma yozdi", "Mijoz savollarni
o'zi yozdi". Matn uchun `settings.ads[].words_by`: `ai` — AI yozgani
o'zgarmagan, `owner` — mijoz yozgan yoki o'zgartirgan, bo'sh — o'z matni yo'q.
Eski launch'da yozuv bo'lmasa `by` bo'sh keladi va "Noma'lum" ko'rsatiladi.

**Post** — `live.ads[].post` (`null` bo'lsa post yo'q): `external_id`, `url`,
`kind_label`, `text`, `picture`. `url` bo'sh bo'lishi mumkin — unda "Postni
ochish" tugmasi chizilmaydi. Mijoz ishga tushirishda tanlagan tayyor post
`settings.ads[].post_url`da. Post ochiq bo'lmasa (faqat reklama uchun
yaratilgan) Facebook havolani ochmasligi mumkin; ko'rinishi uchun pastdagi
preview ishlatiladi.

### `GET /customers/{id}/ads/{launch_id}/preview/{ad_id}?tries=`

Meta'ning o'z ko'rinishi, `ad_id` — `live.ads[].external_id`. Birinchi so'rov
olishni navbatga qo'yadi. `polling: true` bo'lsa `poll_seconds`dan keyin
javobdagi `tries` bilan qayta so'raladi. `src` kelganda `iframe`da chiziladi,
`width` va `height` o'lchami. `gave_up: true` — urinishlar tugadi.

---

## 4. Kartadagi amallar — `POST /customers/{id}/…`

Hammasida `reason` (1–500 belgi) majburiy — jurnalga yoziladi (o'chirishdan
tashqari). Javob: `{"message": "…"}` — xabar qatorida ko'rsating va kartani
qayta o'qing. Rad etish — odatdagi xato javobi (`400`/`422` + `problems`).

**"Pul to'landimi?"** (`plan`, `days`, `slots`, `pages/{page_id}/add`):
`paid: true` bo'lsa `amount` (butun birlikda, masalan `"100000"`) va
`method` (`cash`, `transfer`, `card`) majburiy, `pay_reference` ixtiyoriy.
To'langan bo'lsa hisob (invoice) yoziladi va dashboard'da hisoblanadi.

| Yo'l | Rol | Body |
|---|---|---|
| `plan` | Admin | `plan` (kod), + to'lov |
| `days` | Admin | `days` (1–120), + to'lov |
| `slots` | Admin | `pages` (1–20), `take` (olib qo'yish), + to'lov (`take` bilan emas) |
| `payment` | Admin | `amount`, `method`, `pay_reference` — mavjud kirish uchun pul |
| `referral` | Admin | `mode`: `auto`, `open`, `closed` |
| `receipts` | Admin | — eski cheklarni ulaydi, hech narsa bermaydi |
| `payout` | Finance, Owner | `amount`, `currency`, `method` (`card`, `bank`, `cash`), `pay_reference` |
| `pages/{page_id}/add` | Owner | + to'lov — tarifdan tashqari bitta o'rin va sahifa |
| `pages/{page_id}/move` | Admin | `target` (sahifa ID) — o'rinni boshqa sahifaga beradi |
| `pages/{page_id}/account` | Admin | `current`, `target` (akkaunt external ID) |
| `pages/{page_id}/remove-pair` | Admin | `account` (akkaunt external ID) |
| `password` | Owner + superuser | `new_password1`, `new_password2` — mijoz hamma qurilmada chiqariladi |
| `delete` | Owner | `email` — mijoz emailini qayta yozing. Javob: `message`, `rows`, `receipts_kept` |

Admin = Support, Finance, Owner.

---

## 5. Promo — `/promo`

Ko'rish va so'rovlarga javob: Support, Finance, Owner. Kod yaratish,
tahrirlash, o'chirish: faqat Finance va Owner (`can.grant`).

### `GET /promo?tab=&q=&offset=`

| Parametr | Ma'nosi |
|---|---|
| `tab` | bo'sh — navbat (javob kutayotganlar, eskisi birinchi); `answered` — javob berilganlar (yangisi birinchi) |
| `q` | Ism, email yoki kod |
| `offset` | Keyingi sahifa: `next_offset` (20 tadan) |

Javob:
- `requests[]` — `customer`, `code`, `kind_label`, `offers` (`days`, `pages`, `plan`).
  `refused_before` — oldin necha marta rad etilgan (faqat navbatda).
  `status`, `decided_at`, `decided_by`, `decision_note`.
- `current[]` — ishlayotgan va rejalashtirilgan kodlar; `finished[]` — o'chiq,
  muddati yoki limiti tugaganlar. `status`: `live`, `scheduled`, `spent`,
  `expired`, `off`. `used` / `max_uses`, `percent` — to'lish chizig'i (0 = cheklovsiz).
- `kinds[]`, `discount_kinds[]`, `scopes[]`, `plans[]` — forma tanlovlari.
- `currency` — chegirma summasi va `min_amount` shu valyutada, **butun birlikda**.

### So'rovlar

| Yo'l | Body | |
|---|---|---|
| `POST /promo/requests/{id}/approve` | — | Kod hozir nima bersa shuni beradi |
| `POST /promo/requests/{id}/refuse` | `reason` | Sabab mijozga ko'rinadi |

Allaqachon javob berilgan so'rov — `400` ("Bu so'rov allaqachon hal qilingan").

### Kodlar

| Yo'l | |
|---|---|
| `GET /promo/codes/{id}` | Tahrir formasi uchun |
| `POST /promo/codes` | `kind` + maydonlar. Javob: `message`, `id` |
| `PUT /promo/codes/{id}` | Maydonlar; `kind` o'zgarmaydi |
| `DELETE /promo/codes/{id}` | Ishlatilgan kod o'chirilmaydi (`400`) — `is_active: false` qiling |

Umumiy maydonlar: `code` (katta harfga o'tadi), `description`, `is_active`,
`starts_at`, `expires_at` (zonasiz yuborilsa ofis vaqti), `max_uses`,
`max_uses_per_user` (0 = cheklovsiz), `note`.

| `kind` | O'z maydonlari | Qoidalar |
|---|---|---|
| `plan` | `grant_days`, `plan` (kod), `needs_approval` | Kun yoki tarif; `expires_at` va `max_uses` majburiy |
| `slots` | `grant_pages`, `needs_approval` | Sahifa soni; `expires_at` va `max_uses` majburiy |
| `discount` | `discount_kind` (`percent`/`amount`), `discount_value`, `scope`, `min_amount` | Foiz 1–99; tasdiq bilan bo'lmaydi |

Boshqa turning maydonlari e'tiborsiz qoldiriladi. Xatolar `422` + `problems`
(maydon nomi bo'yicha). Har bir yozish jurnalga tushadi (nima nimadan nimaga o'zgargani bilan).

---

## 6. Chat (yordam) — `/support`

Faqat Support va Owner (`can.answer_support`). Suhbatni o'qish va fayl
yuklab olish jurnalga yoziladi (30 daqiqada bir marta).

| Yo'l | |
|---|---|
| `GET /support?state=&offset=` | Navbat. `state`: `waiting` (standart, eng uzoq kutgan birinchi) yoki `all` (yangisi birinchi). 20 tadan |
| `GET /support/{id}?page=` | Bitta suhbat (eng yangi sahifa). Ochilishi o'qildi deb belgilaydi — mijozda ikkinchi belgi chiqadi |
| `POST /support/{id}/messages` | Javob. Mijoz tomonidagi bilan bir xil `multipart`: `body`, `attachments`, `voice` + `voice_seconds`, `sticker`, `reply_to`, `send_key`, `nonce` |
| `POST /support/{id}/settle` | Navbatdan olish ("javob shart emas"). Mijoz yozsa qaytadi |
| `PATCH /support/messages/{id}` | O'z javobini tahrirlash (`body`) |
| `DELETE /support/messages/{id}` | O'z javobini o'chirish |
| `GET /support/files/{id}`, `GET /support/messages/{id}/file` | Fayl. `<img>` uchun `?token=`, ko'rsatish uchun `?view=1` |
| `GET /support/customers/{customer_id}` | Mijoz kartasidagi "Chat": suhbati bo'lsa o'sha, bo'lmasa bo'sh (`conversation_id: null`) |
| `POST /support/customers/{customer_id}/messages` | Ofisning birinchi xabari — suhbatni ochadi |

Xabar shakli mijoz chati bilan bir xil (`who` — ofisda hamkasb ismi yoki
mijoz ismi; fayl `url`lari ofis yo'llari).

**Socket:** `ws_path` + `?token=<access>` (`/api/v1/office/support/{id}/ws`).
Mijoz socket'i bilan bir xil freymlar: yuborish `{"body"|"sticker", "nonce",
"reply_to"}`, `{"typing": true}`, `{"read": true}`; qabul qilish `message`,
`replace`, `read` (mijoz o'qidi), `typing`, `error`.

### Telegram orqali support (frontend uchun ish yo'q)

- Mijoz yozgan har bir xabar xodimlar botini ulagan har bir Support/Owner
  xodimiga nusxa bo'lib boradi (fayllari bilan). Nusxaga «Reply» qilinsa —
  javob mijoz chatiga tushadi.
- Kim javob bersa (ofisdan yoki Telegram'dan), barcha nusxalar «✅ Javob
  berildi — kim, qachon» deb yangilanadi. Javob berilgan nusxaga yana reply
  qilinsa, bot «baribir yuborilsinmi?» deb so'raydi.
- Mijozning Telegram'i ulangan bo'lsa, ofis javob berganda unga bitta xabar
  boradi (o'qimaguncha qayta bormaydi).
- Mijoz botida `/yordam` dan keyingi yozilgan matn support chatga tushadi.
- Webhook'lar: `POST /webhooks/telegram/` va `/webhooks/telegram/staff/`
  (Django bilan bir xil yo'l va secret).

---

## 7. Dashboard — `/dashboard`

Support, Finance, Owner. **Pul** (`takings`, `payments`, `activity.ai_cost`)
faqat Finance va Owner'ga keladi, boshqalarga `null` (`sees_money: false`).

### `GET /dashboard?period=&since=&until=`

`period`: `today`, `7`, `30` (standart), `month`, `year`, `range`
(`since` + `until`, `YYYY-MM-DD`). Butun ekran shu oynaga qarab hisoblanadi;
"oldingi davr" — xuddi shuncha kun undan oldin.

| Blok | Nima |
|---|---|
| `window` | Tanlangan oyna, ustun o'lchami (`unit`: `day`/`week`/`month`), `refused` — oraliq noto'g'ri bo'lsa sababi |
| `takings` | Pul kartasi (pastda) |
| `customers` | `total`, `joined` (+ oldingi davr va `%`), `trial`, `paying`, `expiring` (7 kun), `churned` (davrda tugab qaytmagan), `joined_paid` / `conversion_pct`, `setup_unfinished`, `meta_missing` |
| `activity` | `running` kampaniyalar, `launched` / `failed` launch'lar, `spend` (mijozlar reklama sarfi, valyuta bo'yicha), `leads` (+ oldingi davr), `ai_cost` |
| `waiting` | `promos`, `support` + `support_oldest`, `asks`, `feedback`, `arizas`, `holds` — har biri o'z ekraniga havola |
| `problems` | `total`, `urgent`, eng jiddiy 6 tasi (`customer_id` — kartaga havola) |
| `payments` | Oxirgi 10 to'lov |
| `sales` | Menejer bo'yicha: davrda sotilgan, hozir ochiq kartalar |

Faqat platforma yaratgan kampaniyalar hisoblanadi; xodimlar va CRM loginlari
mijoz hisoblanmaydi.

### `GET /dashboard/takings?period=&since=&until=&bar=` — Finance, Owner

Faqat pul kartasi (filtr yoki ustun bosilganda shuni qayta o'qing).

- `bars[]` — `key`, `label`, `hint`, `height_pct`, `is_current`, `amount_minor`, `payments`, `signups`.
- `bar=<key>` bosilsa `shown` — o'sha ustun, aks holda butun oyna:
  `amount_minor`, `payments`, `signups`, `average_minor`, `online_minor`,
  `manual_minor`, `plans[]` (`name`, `payments`, `amount_minor`, `share_pct`).
- `before_minor`, `change_pct` — oldingi davrga nisbatan.
- `unpaid`, `unpaid_minor` — hozir to'lanmagan hisoblar; `given_free` — davrda bepul berilganlar.
- `currency` — oynadagi to'lovlarning asosiy valyutasi; boshqa valyutadagi to'lov qo'shilmaydi.

---

## 7a. To'lovlar — `/payments`

Faqat **Owner va super admin** ko'radi, boshqa rollarga `404` (Finance ham
kirmaydi). Menyuni `can.owner` bilan ko'rsating. Owner uchun ekran faqat
o'qish uchun: "Bo'shatish" tugmasi faqat `can.superuser` bo'lsa chiziladi.

| Yo'l | |
|---|---|
| `GET /payments/summary` | Yuqoridagi raqamlar, qotgan hisoblar, 7 kunda tugaydigan obunalar |
| `GET /payments/invoices?state=&q=&offset=` | Hisoblar, yangisi birinchi. `state`: `open`, `paid`, `closed` (`states[]`). `q`: hisob raqami, email, ism, telefon |
| `GET /payments/subscriptions?state=&q=&offset=` | Jonli obunalar, eng tez tugaydigani birinchi. `state`: `unpaid` — pullik tarifda, lekin birorta to'lov yozilmagan. `q`: email, ism, telefon |
| `POST /payments/holds/{id}/release` | Faqat super admin. Body: `reason`. `id` — `holds[].id`. Hisob yana to'lanadigan bo'ladi (muddati o'tmagan bo'lsa). Urinish endi hisobni ushlamayotgan bo'lsa `400` |

`summary.totals`: `earned` (shu oy tushgan pul, valyuta bo'yicha), `unpaid` (soni),
`unpaid_sums` (valyuta bo'yicha), `stuck` (12 soatdan ortiq qotgan), `refunded`
(shu oy qaytarilgan, soni).

`invoices.rows[]`: karta hisobi maydonlari + `id`, `customer` (o'chirilgan
akkauntda `null`), `email`, `transaction` — oxirgi to'lov urinishi: `id`,
`provider`, `external_id`, `state`. Qo'lda yozilgan to'lovda `null`.

Ro'yxatda o'chirish yo'q. Test to'lovi serverda buyruq bilan o'chiriladi:

```bash
python -m tools.erase_payment <transaction.id yoki hisob raqami>        # faqat ko'rsatadi
python -m tools.erase_payment <transaction.id yoki hisob raqami> --yes  # o'chiradi
```

---

## 8. Sotuv doskasi — `/sales`

Rollar: `Sales`, `SalesLead`, `Owner` (`can.sell`). Sozlamalar, jamoa natijalari
va boshqa menejerlarni ko'rish — `SalesLead` va `Owner` (`can.lead_sales`).
Javobdagi `is_lead`, `is_owner` ham shuni aytadi.

**Doska filtrlari** — deyarli barcha `/sales` yo'llari qabul qiladi, javob shu
filtrga mos qaytadi:

| Parametr | Ma'nosi |
|---|---|
| `g` | Navbat chipi: `all` (standart), `ariza`, `problem`, `new`, `back`, `ending` yoki segment `key`i (`chips[]`dan) |
| `q` | Ism, telefon yoki email bo'yicha qidiruv |
| `m` | Faqat boshliq uchun: bitta menejer kartalari (user ID) |

| Yo'l | |
|---|---|
| `GET /sales` | Doska: ustunlar, navbat, chiplar |
| `GET /sales/pool?offset=` | Navbat davomi. `offset` = oxirgi `pool_next`; `null` bo'lsa tugadi |
| `GET /sales/pulse?cursor=` | Polling. O'zgarmagan bo'lsa `204`, o'zgargan bo'lsa ustunlar va yangi `cursor` |
| `GET /sales/cards/{client_id}` | Bitta karta qayerda turishi |
| `GET /sales/clients/{client_id}` | Mijoz oynasi (dialog) |
| `POST /sales/clients/{client_id}/take` | Kartani olish |
| `POST /sales/clients/{client_id}/outcome` | Natija yozish (pastda) |
| `POST /sales/clients/{client_id}/drop` | Kartani boshqa ustunga sudrash |
| `POST /sales/clients/{client_id}/note` | Izoh: `body`, 2000 belgigacha |
| `POST /sales/clients/{client_id}/give-back` | Kartani navbatga qaytarish |
| `POST /sales/order` | Ustun ichidagi tartib: `stage`, `c` (karta ID'lari). Javob `204` |
| `GET /sales/mine` | Menejerning o'z oyi |
| `GET /sales/team` | Reyting |
| `GET /sales/report?oy=&m=` | Hisobot. `oy` = `YYYY-MM`, standart shu oy; `m` — menejer sotuvlari |
| `GET /sales/holds?page=` | Qo'ng'iroq taqiqlari |
| `POST /sales/holds/{id}/lift` | Taqiqni olish |
| `GET` / `POST /sales/settings` | Qoidalar: `ending_days` (1–60), `percent` (0–100, faqat Owner, `may_set_percent`) |
| `POST /sales/settings/reasons` | Rad sababi: `label`, javob `201` |
| `POST /sales/settings/reasons/{id}` | `action`: `archive`, `restore`; bo'sh bo'lsa `label` bilan nomini o'zgartiradi |
| `POST /sales/settings/segments` | Navbat segmenti: `plan`, `days` (1–365), javob `201` |
| `DELETE /sales/settings/segments/{id}` | Segmentni o'chirish |

**Ustunlar (`stage`):** `taken` Olindi, `no_answer` Javob bermadi, `callback`
Qayta aloqa, `thinking` O'ylab ko'radi, `using` Foydalanmoqda, `awaiting` To'lov
kutilmoqda.

**`outcome` qiymatlari:** `no_answer`, `callback`, `thinking`, `using`,
`awaiting`, `lost`. Qo'shimcha maydonlar: `callback_at`, `reason` (rad sababi
ID), `term` (`30`, `90`, `never` — qo'ng'iroq taqiqi), `note`.

**`drop`:** `to` — yuqoridagi `stage` yoki `lost`; `from` — qayerdan (navbatdan
olingan bo'lsa `pool` yoki bo'sh). `to` `callback`, `thinking`, `lost` bo'lsa
`outcome` maydonlari ham yuboriladi.

---

## 9. Hali API yo'q ekranlar

Bu yo'llar **hali yo'q**, menyuda ularni ko'rsatmang yoki "tez orada" deb yozing:

| Ekran | Holat |
|---|---|
| Hamyon (pul yechish navbati, to'lash, rad etish) | Yo'q. Faqat qo'lda yozish bor: `POST /customers/{id}/payout` |
| So'rovnomalar (yaratish, javoblar, Excel) | Yo'q |
| Fikrlar va testimonial'lar | Yo'q |
| Statistika (platforma bo'yicha) | Yo'q |
| Developer ekrani | Yo'q |
| Jamoa (rollarni boshqarish) | Yo'q |
| Xodim Telegram'ini ulash | Yo'q |
| Mijozni bloklash | Yo'q. `is_blocked` faqat o'qiladi |

`/me` dagi `waiting.asks` va `waiting.feedback` hisoblanadi, lekin ochadigan
ekrani yo'q: raqamni havolasiz ko'rsating.

## 10. Reklama bo'yicha cheklovlar

- Ro'yxatda faqat Meta reklamalari bor, Google reklamalari yo'q.
- Yaratilmay qolgan reklama ro'yxatga chiqmaydi. `launch_id` ma'lum bo'lsa,
  detal `row: null`, `figures: null` va `live.error` bilan ochiladi.

---


## A-ilova. Barcha yo'llar

`*` — majburiy parametr. Yo'llar `/api/v1/office` ostida. Javob va so'rov turlari B-ilovada.


### Mijozlar

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/customers` | Support, Finance, Owner | `q`, `state`, `plan`, `joined_from`, `joined_to`, `manager`, `sort`, `offset`, `as_of` | — | 200 CustomersOut |
| GET | `/customers/{customer_id}` | Support, Finance, Owner | — | — | 200 CustomerCardOut |
| GET | `/customers/{customer_id}/ads` | Support, Finance, Owner | `period`, `since`, `until` | — | 200 CustomerAdsOut |
| GET | `/customers/{customer_id}/ads/{launch_id}` | Support, Finance, Owner | `period`, `since`, `until`, `bar` | — | 200 CustomerAdOut |
| GET | `/customers/{customer_id}/ads/{launch_id}/preview/{ad_id}` | Support, Finance, Owner | `tries` | — | 200 AdFrameOut |
| POST | `/customers/{customer_id}/days` | Support, Finance, Owner | — | DaysIn | 200 MessageOut |
| POST | `/customers/{customer_id}/delete` | Owner | — | DeleteIn | 200 DeletedOut |
| POST | `/customers/{customer_id}/pages/{page_id}/account` | Support, Finance, Owner | — | PageAccountIn | 200 MessageOut |
| POST | `/customers/{customer_id}/pages/{page_id}/add` | Owner | — | PaidIn | 200 MessageOut |
| POST | `/customers/{customer_id}/pages/{page_id}/move` | Support, Finance, Owner | — | MovePageIn | 200 MessageOut |
| POST | `/customers/{customer_id}/pages/{page_id}/remove-pair` | Support, Finance, Owner | — | RemovePairIn | 200 MessageOut |
| POST | `/customers/{customer_id}/password` | Owner | — | PasswordIn | 200 MessageOut |
| POST | `/customers/{customer_id}/payment` | Support, Finance, Owner | — | PaymentIn | 200 MessageOut |
| POST | `/customers/{customer_id}/payout` | Finance, Owner | — | PayoutIn | 200 MessageOut |
| POST | `/customers/{customer_id}/plan` | Support, Finance, Owner | — | PlanIn | 200 MessageOut |
| POST | `/customers/{customer_id}/receipts` | Support, Finance, Owner | — | ReasonIn | 200 MessageOut |
| POST | `/customers/{customer_id}/referral` | Support, Finance, Owner | — | ReferralIn | 200 MessageOut |
| POST | `/customers/{customer_id}/slots` | Support, Finance, Owner | — | SlotsIn | 200 MessageOut |

### Dashboard

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/dashboard` | Support, Finance, Owner | `period`, `since`, `until` | — | 200 DashboardOut |
| GET | `/dashboard/takings` | Finance, Owner | `period`, `since`, `until`, `bar` | — | 200 TakingsOut |
| GET | `/payments/summary` | Owner | — | — | 200 PaymentsSummaryOut |
| GET | `/payments/invoices` | Owner | `state`, `q`, `offset` | — | 200 PaymentInvoicesOut |
| GET | `/payments/subscriptions` | Owner | `state`, `q`, `offset` | — | 200 PaymentSubscriptionsOut |
| POST | `/payments/holds/{attempt_id}/release` | Super admin | — | ReasonIn | 200 MessageOut |

### Jurnal

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/journal` | Owner | `kind`, `offset` | — | 200 JournalOut |

### Menyu

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/me` | Hamma xodim | — | — | 200 MeOut |

### Promo

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/promo` | Support, Finance, Owner | `tab`, `q`, `offset` | — | 200 PromoOut |
| POST | `/promo/codes` | Finance, Owner | — | NewCodeIn | 200 CreatedOut |
| GET | `/promo/codes/{code_id}` | Support, Finance, Owner | — | — | 200 PromoCodeOut |
| PUT | `/promo/codes/{code_id}` | Finance, Owner | — | CodeIn | 200 MessageOut |
| DELETE | `/promo/codes/{code_id}` | Finance, Owner | — | — | 200 MessageOut |
| POST | `/promo/requests/{request_id}/approve` | Support, Finance, Owner | — | — | 200 MessageOut |
| POST | `/promo/requests/{request_id}/refuse` | Support, Finance, Owner | — | RefuseIn | 200 MessageOut |

### Sotuv

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/sales` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 SalesBoardOut |
| GET | `/sales/cards/{client_id}` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 PlacementOut |
| GET | `/sales/clients/{client_id}` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 DialogOut |
| POST | `/sales/clients/{client_id}/drop` | Sales, SalesLead, Owner | `g`, `m`, `q` | DropIn | 200 MovedOut |
| POST | `/sales/clients/{client_id}/give-back` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 MovedOut |
| POST | `/sales/clients/{client_id}/note` | Sales, SalesLead, Owner | `g`, `m`, `q` | NoteIn | 200 DialogOut |
| POST | `/sales/clients/{client_id}/outcome` | Sales, SalesLead, Owner | `g`, `m`, `q` | OutcomeIn | 200 MovedOut |
| POST | `/sales/clients/{client_id}/take` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 DialogOut |
| GET | `/sales/holds` | SalesLead, Owner | `page` | — | 200 HoldsOut |
| POST | `/sales/holds/{hold_id}/lift` | SalesLead, Owner | — | — | 200 SalesMessageOut |
| GET | `/sales/mine` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 MineOut |
| POST | `/sales/order` | Sales, SalesLead, Owner | — | ReorderIn | 204 — |
| GET | `/sales/pool` | Sales, SalesLead, Owner | `offset`, `g`, `m`, `q` | — | 200 PoolOut |
| GET | `/sales/pulse` | Sales, SalesLead, Owner | `cursor`, `g`, `m`, `q` | — | 200 SalesPulseOut, 204 bo'sh |
| GET | `/sales/report` | SalesLead, Owner | `oy`, `m` | — | 200 SalesReportOut |
| GET | `/sales/settings` | SalesLead, Owner | `g`, `m`, `q` | — | 200 SalesSettingsOut |
| POST | `/sales/settings` | SalesLead, Owner | `g`, `m`, `q` | RuleIn | 200 RuleSavedOut |
| POST | `/sales/settings/reasons` | SalesLead, Owner | — | SalesReasonIn | 201 ReasonSavedOut |
| POST | `/sales/settings/reasons/{reason_id}` | SalesLead, Owner | — | ReasonChangeIn | 200 ReasonSavedOut |
| POST | `/sales/settings/segments` | SalesLead, Owner | — | SegmentIn | 201 SegmentSavedOut |
| DELETE | `/sales/settings/segments/{segment_id}` | SalesLead, Owner | — | — | 200 SalesMessageOut |
| GET | `/sales/team` | Sales, SalesLead, Owner | `g`, `m`, `q` | — | 200 TeamOut |

### Chat

| Metod | Yo'l | Rol | Query | Body | Javob |
|---|---|---|---|---|---|
| GET | `/support` | Support, Owner | `state`, `offset` | — | 200 SupportQueueOut |
| GET | `/support/customers/{customer_id}` | Support, Owner | — | — | 200 SupportThreadOut |
| POST | `/support/customers/{customer_id}/messages` | Support, Owner | — | SupportStartForm (multipart) | 201 SentOut |
| GET | `/support/files/{attachment_id}` | Support, Owner | `view`, `token` | — | 200 fayl |
| PATCH | `/support/messages/{message_id}` | Support, Owner | — | EditIn | 200 SupportMessageOut |
| DELETE | `/support/messages/{message_id}` | Support, Owner | — | — | 200 SupportMessageOut |
| GET | `/support/messages/{message_id}/file` | Support, Owner | `view`, `token` | — | 200 fayl |
| GET | `/support/{conversation_id}` | Support, Owner | `page` | — | 200 SupportThreadOut |
| POST | `/support/{conversation_id}/messages` | Support, Owner | — | SupportSendForm (multipart) | 201 SentOut |
| POST | `/support/{conversation_id}/settle` | Support, Owner | — | — | 200 MessageOut |


### Socket

| Yo'l | Rol | Ulash |
|---|---|---|
| `WS /support/{conversation_id}/ws` | Support, Owner | `?token=<access>` |


---

## B-ilova. Maydonlar

`Majburiy: ha` — maydon doim keladi yoki so'rovda shart. `\| null` — qiymat `null` bo'lishi mumkin. So'rov shakllari `In` yoki `Form`, javob shakllari `Out` bilan tugaydi.


### AdAccountOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `currency` | string | ha |  |  |
| `is_active` | boolean | ha |  | Chosen in the cabinet. |
| `may_advertise` | boolean \| null | ha |  |  |
| `payment_due` | boolean \| null | ha |  |  |
| `balance_minor` | integer | ha |  |  |
| `synced_at` | datetime \| null | ha |  |  |

### AdBarOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `key` | date | ha |  |  |
| `label` | string | ha |  |  |
| `hint` | string | ha |  |  |
| `sums` | AdSumsOut | ha |  |  |
| `reach` | integer | ha |  | The widest day: at least this many people. |
| `leads` | integer | ha |  |  |
| `qualified` | integer | ha |  |  |
| `results` | integer | ha |  |  |
| `result_cost_minor` | integer \| null | ha |  |  |

### AdCampaignOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `objective` | string | ha |  |  |
| `delivery_label` | string | ha |  |  |
| `is_running` | boolean | ha |  |  |
| `daily_budget_minor` | integer \| null | ha |  |  |
| `spend_cap_minor` | integer \| null | ha |  |  |
| `currency` | string | ha |  |  |
| `created_at` | datetime \| null | ha |  |  |
| `problem` | string | ha |  |  |

### AdCurrencyOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `currency` | string | ha |  |  |
| `spend_minor` | integer | ha |  |  |
| `impressions` | integer | ha |  |  |
| `clicks` | integer | ha |  |  |
| `link_clicks` | integer | ha |  |  |
| `leads` | integer | ha |  |  |
| `ctr_percent` | string | ha |  |  |
| `cpm_minor` | integer \| null | ha |  |  |
| `cpc_minor` | integer \| null | ha |  |  |
| `lead_cost_minor` | integer \| null | ha |  |  |

### AdDecisionOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `key` | string | ha |  | `campaign_type`, `conversion_event`, `audience`, `interests`, `placement`, `form` or `button`. |
| `label` | string | ha |  |  |
| `value` | string | ha |  |  |
| `by` | string | ha |  | `ai`, `owner`, or empty when it was not recorded. |
| `by_label` | string | ha |  |  |

### AdFiguresOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `sums` | AdSumsOut | ha |  |  |
| `reach` | integer | ha |  |  |
| `reach_is_exact` | boolean | ha |  | False: at least this many people. |
| `result` | AdResultOut | ha |  |  |
| `leads` | integer | ha |  |  |
| `qualified` | integer | ha |  |  |
| `synced_at` | datetime \| null | ha |  |  |
| `lifetime_leads` | AdLifetimeLeadsOut | ha |  |  |

### AdFrameOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `src` | string | ha |  | Meta's preview address, for an iframe. |
| `width` | integer | ha |  |  |
| `height` | integer | ha |  |  |
| `polling` | boolean | ha |  | Ask again in `poll_seconds` with `tries`. |
| `tries` | integer | ha |  |  |
| `poll_seconds` | integer | ha |  |  |
| `gave_up` | boolean | ha |  |  |

### AdGroupOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `delivery_label` | string | ha |  |  |
| `optimization_goal` | string | ha |  |  |
| `daily_budget_minor` | integer \| null | ha |  |  |
| `is_learning` | boolean | ha |  |  |
| `problem` | string | ha |  |  |
| `audience` | AudienceOut \| null | ha |  | As the last sync saw it. |
| `sums` | AdSumsOut | ha |  |  |
| `leads` | integer | ha |  |  |
| `lead_cost_minor` | integer \| null | ha |  |  |
| `ads` | AdLineOut[] | ha |  |  |

### AdLifetimeLeadsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `total` | integer | ha |  |  |
| `tests` | integer | ha |  |  |
| `organic` | integer | ha |  |  |
| `first_at` | datetime \| null | ha |  |  |
| `last_at` | datetime \| null | ha |  |  |

### AdLineOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `delivery_label` | string | ha |  |  |
| `quality_ranking` | string | ha |  |  |
| `sums` | AdSumsOut | ha |  |  |
| `leads` | integer | ha |  |  |
| `lead_cost_minor` | integer \| null | ha |  |  |

### AdLiveOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `status` | string | ha |  |  |
| `step` | string | ha |  |  |
| `error` | string | ha |  |  |
| `delivery_note` | string | ha |  |  |
| `qualified` | boolean | ha |  |  |
| `ads` | LiveAdOut[] | ha |  |  |
| `forms` | LiveFormOut[] | ha |  |  |

### AdPostOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `url` | string | ha |  | Empty when this post has no address we know. |
| `kind_label` | string | ha |  |  |
| `text` | string | ha |  |  |
| `picture` | string | ha |  |  |

### AdResultOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `label` | string | ha |  | Empty for a result this screen cannot count. |
| `count` | integer | ha |  |  |
| `cost_minor` | integer \| null | ha |  |  |
| `cost_label` | string | ha |  |  |
| `note` | string | ha |  |  |

### AdRowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `launch_id` | string | ha |  |  |
| `campaign_external_id` | string | ha |  |  |
| `campaign_name` | string | ha |  |  |
| `started_at` | datetime \| null | ha |  |  |
| `goal` | string | ha |  |  |
| `page` | string | ha |  |  |
| `delivery_label` | string | ha |  |  |
| `is_running` | boolean | ha |  |  |
| `spend_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `results` | integer | ha |  | What it was bought for: leads, calls, chats... |
| `result_word` | string | ha |  |  |
| `result_cost_minor` | integer \| null | ha |  |  |
| `result_cost_label` | string | ha |  |  |
| `note` | string | ha |  | Instead of a figure this screen cannot count. |
| `impressions` | integer | ha |  |  |
| `reach` | integer \| null | ha |  | Null when nobody counted this window. |
| `clicks` | integer | ha |  |  |
| `link_clicks` | integer | ha |  |  |
| `leads` | integer | ha |  |  |
| `ctr_percent` | string | ha |  | Empty before the first impression. |
| `cpm_minor` | integer \| null | ha |  |  |
| `cpc_minor` | integer \| null | ha |  |  |

### AdSettingsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `goal` | string | ha |  |  |
| `goal_text` | string | ha |  | The customer's own words about the goal. |
| `offer_text` | string | ha |  |  |
| `link_url` | string | ha |  |  |
| `phone` | string | ha |  |  |
| `campaign_name` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `page` | string | ha |  |  |
| `currency` | string | ha |  |  |
| `daily_budget_minor` | integer \| null | ha |  |  |
| `daily_min_minor` | integer \| null | ha |  |  |
| `daily_max_minor` | integer \| null | ha |  |  |
| `total_cap_minor` | integer \| null | ha |  |  |
| `max_result_cost_minor` | integer \| null | ha |  |  |
| `start_date` | date \| null | ha |  |  |
| `end_date` | date \| null | ha |  |  |
| `audience_lower` | integer \| null | ha |  |  |
| `audience_upper` | integer \| null | ha |  |  |
| `audience` | AudienceOut | ha |  |  |
| `button` | string | ha |  |  |
| `conversion_event` | string | ha |  |  |
| `url_tags` | string | ha |  |  |
| `attribution` | string | ha |  |  |
| `frequency_cap` | object \| null | ha |  |  |
| `buys_qualified_leads` | boolean | ha |  |  |
| `decisions` | AdDecisionOut[] | ha |  | Who settled each part. |
| `ads` | LaunchAdOut[] | ha |  |  |

### AdSiblingOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `launch_id` | string | ha |  |  |
| `started_at` | datetime | ha |  |  |

### AdSumsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `spend_minor` | integer | ha |  |  |
| `impressions` | integer | ha |  |  |
| `clicks` | integer | ha |  |  |
| `link_clicks` | integer | ha |  |  |
| `landing_page_views` | integer | ha |  |  |
| `leads_reported` | integer | ha |  | The provider's count. |
| `results_reported` | integer | ha |  |  |
| `recallers` | integer | ha |  |  |
| `profile_visits` | integer | ha |  |  |
| `video_plays` | integer | ha |  |  |
| `video_thruplays` | integer | ha |  |  |
| `reactions` | integer | ha |  |  |
| `comments` | integer | ha |  |  |
| `shares` | integer | ha |  |  |
| `saves` | integer | ha |  |  |
| `ctr_percent` | string | ha |  |  |
| `cpm_minor` | integer \| null | ha |  |  |
| `cpc_minor` | integer \| null | ha |  |  |

### AdWindowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `period` | string | ha |  |  |
| `since` | date | ha |  |  |
| `until` | date | ha |  |  |
| `refused` | string | ha |  | Why a typed stretch was not read; else empty. |
| `periods` | ChoiceOut[] | ha |  |  |

### AgentOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `is_enabled` | boolean | ha |  |  |
| `last_run_at` | datetime \| null | ha |  |  |

### AiOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `spent_minor` | integer | ha |  |  |
| `limit_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `entitled` | boolean | ha |  | False: no live plan, never granted. |

### AmountOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `currency` | string | ha |  |  |
| `amount_minor` | integer | ha |  |  |

### AudienceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `places` | string[] | ha |  |  |
| `excluded_places` | string[] | ha |  |  |
| `ages` | string | ha |  |  |
| `genders` | string | ha |  |  |
| `interests` | string[][] | ha |  | Blocks: AND between, OR within. |
| `excluded_interests` | string[] | ha |  |  |
| `placements` | string[] | ha |  | Empty: the provider chooses. |
| `devices` | string[] | ha |  |  |
| `own_lists` | string[] | ha |  |  |
| `excluded_lists` | string[] | ha |  |  |
| `is_automatic` | boolean | ha |  |  |

### BarOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `key` | string | ha |  | Pass as `bar` to read its figures. |
| `label` | string | ha |  |  |
| `hint` | string | ha |  |  |
| `height_pct` | integer | ha |  |  |
| `is_current` | boolean | ha |  | Today is in it: not finished yet. |
| `amount_minor` | integer | ha |  |  |
| `payments` | integer | ha |  |  |
| `signups` | integer | ha |  |  |

### BillOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `number` | string | ha |  |  |
| `plan` | string | ha |  |  |
| `amount_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `paid_at` | datetime \| null | ha |  |  |
| `source` | string | ha |  |  |
| `manager` | PersonOut \| null | ha |  |  |

### BusinessLineOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `name` | string | ha |  |  |
| `direction` | string | ha |  | The business type, in Uzbek. |

### BusinessOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `direction` | string | ha |  |  |
| `page_id` | string \| null | ha |  |  |
| `city` | string | ha |  |  |
| `country_code` | string | ha |  |  |
| `contact_phone` | string | ha |  |  |
| `website` | string | ha |  |  |

### CanOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `give` | boolean | ha |  | Plan, days, slots, a payment, the referral switch (Support, Finance, Owner). |
| `grant` | boolean | ha |  | Money: payouts, holds, promo codes (Finance, Owner). |
| `owner` | boolean | ha |  | The roster, the journal, adding a page, deleting. |
| `superuser` | boolean | ha |  | Setting a customer's password. |
| `engineer` | boolean | ha |  | The faults console. |
| `answer_support` | boolean | ha |  | The support chat queue. |
| `answer_feedback` | boolean | ha |  | The feedback queue. |
| `sell` | boolean | ha |  | The sales board. |
| `lead_sales` | boolean | ha |  | The sales lead's screens: holds, settings. |

### CardInvoiceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `number` | string | ha |  |  |
| `kind` | string | ha |  |  |
| `kind_label` | string | ha |  |  |
| `status` | string | ha |  |  |
| `status_label` | string | ha |  |  |
| `plan` | PlanLineOut \| null | ha |  |  |
| `amount_minor` | integer | ha |  | Money paid, Hamyon and credit left out. |
| `wallet_minor` | integer | ha |  |  |
| `credit_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `period_days` | integer | ha |  |  |
| `pages` | integer | ha |  |  |
| `seats` | integer | ha |  |  |
| `manual_method` | string | ha |  | Set when the office wrote it down. |
| `recorded_by` | PersonOut \| null | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `paid_at` | datetime \| null | ha |  |  |

### CardSalesOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `claim` | object \| null | ha |  | The open sales card, as the sales board draws it. |
| `closed` | integer | ha |  |  |
| `lines` | object[] | ha |  | The latest 10 sales notes. |
| `hold` | object \| null | ha |  | A do-not-call hold. |

### ChipOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `key` | string | ha |  |  |
| `label` | string | ha |  |  |
| `count` | integer | ha |  |  |

### ChoiceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `value` | string | ha |  |  |
| `label` | string | ha |  |  |

### ClientCardOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `subject_id` | string | ha |  |  |
| `client` | PooledOut \| null | ha |  |  |
| `consult` | SalesConsultOut \| null | ha |  |  |
| `claim` | SalesCardOut \| null | ha |  |  |
| `queued_group` | string \| null | ha |  |  |
| `history` | SalesHistoryLine[] | ha |  |  |
| `bills` | BillOut[] | ha |  |  |
| `paid_count` | integer | ha |  |  |
| `facebook` | string | ha |  |  |
| `facebook_name` | string | ha |  |  |
| `telegram` | string | ha |  |  |
| `launches` | integer | ha |  |  |

### CodeIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  | kamida 1, ko'pi 32 |
| `description` | string | yo'q | `""` | ko'pi 255 |
| `is_active` | boolean | yo'q | `true` |  |
| `starts_at` | datetime \| null | yo'q |  | Empty: works at once. |
| `expires_at` | datetime \| null | yo'q |  |  |
| `max_uses` | integer | yo'q | `0` | 0 = no ceiling. min 0.0, max 2147483647.0 |
| `max_uses_per_user` | integer | yo'q | `1` | 0 = no ceiling. min 0.0, max 32767.0 |
| `note` | string | yo'q | `""` | ko'pi 5000 |
| `grant_days` | integer | yo'q | `0` | Kind `plan`. min 0.0, max 32767.0 |
| `plan` | string | yo'q | `""` | Kind `plan`: a plan code, or empty. |
| `grant_pages` | integer | yo'q | `0` | Kind `slots`. min 0.0, max 32767.0 |
| `needs_approval` | boolean | yo'q | `false` | Kinds `plan` and `slots`. |
| `discount_kind` | PromoDiscountKind \| null | yo'q |  | Kind `discount`: `percent` or `amount`. |
| `discount_value` | integer | yo'q | `0` | A percent 1-99, or whole units. min 0.0, max 1000000000000.0 |
| `scope` | PromoScope | yo'q | `"both"` |  |
| `min_amount` | integer | yo'q | `0` | Whole units; 0 = any. min 0.0, max 1000000000000.0 |

### ComposerOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `max_body_chars` | integer | ha |  |  |
| `max_upload_mb` | integer | ha |  |  |
| `max_send_mb` | integer | ha |  |  |
| `max_files` | integer | ha |  |  |
| `max_voice_seconds` | integer | ha |  |  |
| `typing_beat_ms` | integer | ha |  | How often to send `{"typing": true}`. |
| `typing_shown_ms` | integer | ha |  | How long to show the other side typing. |
| `allowed_suffixes` | string[] | ha |  |  |
| `voice_suffixes` | string[] | ha |  |  |
| `stickers` | StickerOut[] | ha |  |  |

### CreatedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  | What happened, to show in the message strip. |
| `id` | string | ha |  |  |

### CustomerAdOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `launch_id` | string | ha |  |  |
| `window` | AdWindowOut | ha |  |  |
| `bar` | string | ha |  | `day`, `week` or `month`: the size of one bar. |
| `bars_offered` | ChoiceOut[] | ha |  |  |
| `row` | AdRowOut \| null | ha |  | Null: the launch made no campaign. |
| `campaign` | AdCampaignOut \| null | ha |  |  |
| `figures` | AdFiguresOut \| null | ha |  |  |
| `bars` | AdBarOut[] | ha |  | Oldest first. |
| `groups` | AdGroupOut[] | ha |  |  |
| `siblings` | AdSiblingOut[] | ha |  | Launches in the same campaign. |
| `settings` | AdSettingsOut | ha |  |  |
| `live` | AdLiveOut | ha |  |  |

### CustomerAdsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `period` | string | ha |  |  |
| `periods` | ChoiceOut[] | ha |  |  |
| `window` | AdWindowOut | ha |  |  |
| `running` | integer | ha |  | Delivering now, whatever the window. |
| `totals` | AmountOut[] | ha |  | Spend per currency, never summed. |
| `summary` | AdCurrencyOut[] | ha |  | All figures, one per currency. |
| `hidden` | integer | ha |  | Adverts left out: quiet over this window. |
| `rows` | AdRowOut[] | ha |  |  |

### CustomerCardOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `profile` | ProfileOut | ha |  |  |
| `businesses` | BusinessOut[] | ha |  |  |
| `subscription` | SubscriptionOut \| null | ha |  |  |
| `lapsed` | SubscriptionOut \| null | ha |  | The last one, when none is live. |
| `limits` | LimitsOut | ha |  |  |
| `plan_picker` | PlanPickerOut | ha |  |  |
| `meta` | MetaOut \| null | ha |  |  |
| `ad_accounts` | AdAccountOut[] | ha |  |  |
| `pages` | PageOut[] | ha |  |  |
| `pixels` | PixelOut[] | ha |  |  |
| `telegram` | TelegramOut \| null | ha |  |  |
| `agent` | AgentOut \| null | ha |  |  |
| `money` | MoneyOut | ha |  |  |
| `referral` | ReferralOut | ha |  |  |
| `sales` | CardSalesOut | ha |  |  |
| `problems` | TroubleOut[] | ha |  |  |
| `traces` | TraceOut[] | ha |  | The office's last 6 actions here. |

### CustomerPersonOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `email` | string | ha |  |  |
| `phone` | string | ha |  |  |

### CustomerRowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `customer` | CustomerPersonOut | ha |  |  |
| `is_blocked` | boolean | ha |  |  |
| `joined_at` | datetime | ha |  |  |
| `last_login_at` | datetime \| null | ha |  |  |
| `business` | BusinessLineOut \| null | ha |  |  |
| `term` | TermOut | ha |  |  |
| `trouble` | TroubleOut \| null | ha |  | The worst thing wrong. |
| `pages` | PagesOut \| null | ha |  |  |
| `running` | integer | ha |  | Campaigns this product launched, running now. |
| `spend` | AmountOut[] | ha |  | This month, per currency. |
| `leads` | integer | ha |  | This month's applications. |
| `paid_total` | AmountOut[] | ha |  | Every paid bill, per currency. |
| `paid_before` | boolean | ha |  | A deleted account on this address left paid receipts behind. |
| `sales_manager` | PersonOut \| null | ha |  |  |

### CustomersOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `rows` | CustomerRowOut[] | ha |  |  |
| `total` | integer | ha |  |  |
| `offset` | integer | ha |  |  |
| `next_offset` | integer | ha |  |  |
| `has_more` | boolean | ha |  |  |
| `as_of` | datetime | ha |  | Send back as `as_of` with the next offset. |
| `states` | ChoiceOut[] | ha |  |  |
| `sorts` | ChoiceOut[] | ha |  |  |
| `plans` | ChoiceOut[] | ha |  |  |
| `managers` | ChoiceOut[] | ha |  | Sales staff, for the `manager` filter; `none` is nobody's. |

### DashActivityOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `running` | integer | ha |  |  |
| `launched` | integer | ha |  |  |
| `failed` | integer | ha |  |  |
| `spend` | AmountOut[] | ha |  | Customers' ad spend, per currency. |
| `leads` | integer | ha |  |  |
| `leads_before` | integer | ha |  |  |
| `leads_change_pct` | integer \| null | ha |  |  |
| `ai_cost` | AmountOut \| null | ha |  | Money roles only. |

### DashboardOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `window` | WindowOut | ha |  |  |
| `sees_money` | boolean | ha |  |  |
| `takings` | TakingsOut \| null | ha |  | Money roles only. |
| `customers` | DashCustomersOut | ha |  |  |
| `activity` | DashActivityOut | ha |  |  |
| `waiting` | DashWaitingOut | ha |  |  |
| `problems` | DashProblemsOut | ha |  |  |
| `payments` | DashPaymentOut[] \| null | ha |  | Money roles only. |
| `sales` | DashSalesOut[] | ha |  |  |

### DashCustomersOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `total` | integer | ha |  |  |
| `joined` | integer | ha |  |  |
| `joined_before` | integer | ha |  |  |
| `joined_change_pct` | integer \| null | ha |  |  |
| `trial` | integer | ha |  | On a trial now. |
| `paying` | integer | ha |  | On a paid plan now. |
| `expiring` | integer | ha |  | Ending within 7 days. |
| `churned` | integer | ha |  | Stopped in the window and not back. |
| `joined_paid` | integer | ha |  | Of those who joined, how many paid. |
| `conversion_pct` | integer \| null | ha |  |  |
| `setup_unfinished` | integer | ha |  |  |
| `meta_missing` | integer | ha |  | Subscribed, no live Facebook link. |

### DashPaymentOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `paid_at` | datetime | ha |  |  |
| `customer` | PersonOut \| null | ha |  | Gone when the account was deleted. |
| `email` | string | ha |  |  |
| `plan` | string | ha |  |  |
| `amount_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `manual` | boolean | ha |  |  |

### DashProblemOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `kind` | string | ha |  |  |
| `label` | string | ha |  |  |
| `urgent` | boolean | ha |  |  |
| `customer_id` | string \| null | ha |  |  |
| `who` | string | ha |  |  |
| `what` | string | ha |  |  |
| `since` | datetime \| null | ha |  |  |
| `action` | string | ha |  |  |

### DashProblemsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `total` | integer | ha |  |  |
| `urgent` | integer | ha |  |  |
| `rows` | DashProblemOut[] | ha |  |  |

### DashSalesOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `manager` | PersonOut | ha |  |  |
| `sold` | integer | ha |  | Sold in the window. |
| `open` | integer | ha |  | Cards open now. |

### DashWaitingOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `promos` | integer | ha |  |  |
| `support` | integer | ha |  |  |
| `support_oldest` | datetime \| null | ha |  | The longest-waiting chat. |
| `asks` | integer | ha |  |  |
| `feedback` | integer | ha |  |  |
| `arizas` | integer | ha |  |  |
| `holds` | integer | ha |  | Payments held longer than 12 hours. |

### DaysIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `paid` | boolean | yo'q | `false` |  |
| `amount` | number \| string \| null | yo'q |  | Whole units. |
| `method` | ManualMethod \| null | yo'q |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |
| `days` | integer | ha |  | min 1.0, max 120.0 |

### DeletedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  | What happened, to show in the message strip. |
| `rows` | integer | ha |  |  |
| `receipts_kept` | integer | ha |  |  |

### DeleteIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `email` | string | ha |  | The customer's address, typed back. |

### DialogOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `mode` | string | ha |  | `own` (yours), `watch` (a lead looking), `queue` (in the pool) or `gone` (someone else's). |
| `refusal` | string | ha |  | Why the last press was refused; empty if not. |
| `card` | ClientCardOut | ha |  |  |
| `hold` | HoldOut \| null | ha |  | Only in `watch` mode. |
| `reasons` | SalesReasonOut[] | ha |  |  |
| `outcomes` | object | ha |  |  |
| `hold_terms` | object | ha |  |  |
| `held` | integer | ha |  |  |
| `placement` | PlacementOut \| null | yo'q |  | Only after a press. |

### DropIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `outcome` | string | yo'q | `""` |  |
| `callback_at` | datetime \| null | yo'q |  |  |
| `reason` | uuid \| null | yo'q |  |  |
| `term` | HoldTerm | yo'q | `"90"` |  |
| `note` | string | yo'q | `""` | ko'pi 2000 |
| `to` | string | ha |  |  |
| `from` | string | yo'q | `""` |  |

### EditIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `body` | string | yo'q | `""` | The new words. |

### FileOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `kind` | string | ha |  | `image`, `video`, `file` or `voice`. |
| `name` | string | ha |  |  |
| `size` | integer | ha |  | Bytes. |
| `seconds` | integer | ha |  | A voice message's length; 0 otherwise. |
| `length` | string | ha |  | `seconds` as m:ss. |
| `url` | string | ha |  | Download. Send the bearer header or `?token=`. |
| `view_url` | string | ha |  | Shown in the page (`?view=1`): pictures, video and voice answer with their type and a byte range; anything else downloads. |

### HistoryLineOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `kind` | string | ha |  |  |
| `kind_label` | string | ha |  |  |
| `from_plan` | PlanLineOut \| null | ha |  |  |
| `to_plan` | PlanLineOut \| null | ha |  |  |
| `days` | integer | ha |  |  |
| `expires_before` | datetime \| null | ha |  |  |
| `expires_after` | datetime \| null | ha |  |  |
| `invoice` | string | ha |  |  |
| `paid_minor` | integer | ha |  |  |
| `actor` | PersonOut \| null | ha |  |  |
| `reason` | string | ha |  |  |
| `occurred_at` | datetime | ha |  |  |

### HoldOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `client_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `until` | datetime \| null | ha |  |  |
| `forever` | boolean | ha |  |  |
| `set_by` | PersonOut \| null | ha |  |  |
| `reason` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |

### HoldsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `page` | integer | ha |  |  |
| `pages` | integer | ha |  |  |
| `total` | integer | ha |  |  |
| `rows` | HoldOut[] | ha |  |  |

### HoldTerm

Qiymatlar: `30`, `90`, `never`


### InstagramOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `name` | string | ha |  |  |
| `is_own` | boolean | ha |  | The page's own account, on the page's slot. |
| `in_subscription` | boolean | ha |  |  |
| `is_linked` | boolean | ha |  | False: Meta unlinked it from the page. |

### JournalOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `kind` | string | ha |  |  |
| `kinds` | ChoiceOut[] | ha |  | Filter chips; `""` is every write, readings come last. |
| `rows` | JournalRowOut[] | ha |  |  |
| `offset` | integer | ha |  |  |
| `next_offset` | integer | ha |  |  |
| `has_more` | boolean | ha |  |  |

### JournalRowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `kind` | string | ha |  |  |
| `kind_label` | string | ha |  |  |
| `reason` | string | ha |  |  |
| `detail` | object | ha |  |  |
| `actor` | PersonOut \| null | ha |  | Gone when that member was removed. |
| `customer` | PersonOut | ha |  |  |

### LaunchAdOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `position` | integer | ha |  |  |
| `name` | string | ha |  |  |
| `headline` | string | ha |  |  |
| `text` | string | ha |  |  |
| `description` | string | ha |  |  |
| `words_by` | string | ha |  | `ai`, `owner`, or empty: no words of its own. |
| `words_by_label` | string | ha |  |  |
| `picture` | string | ha |  |  |
| `is_video` | boolean | ha |  |  |
| `video_url` | string | ha |  |  |
| `media_kind_label` | string | ha |  |  |
| `post_url` | string | ha |  | The post it was built from; empty for none. |

### LimitsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `pages` | UsedOut | ha |  |  |
| `extra_instagrams` | integer | ha |  | Of `pages.used`, Instagram slots. |
| `crm_seats` | UsedOut | ha |  |  |
| `running` | RunningOut[] | ha |  | Ad groups delivering, per page. |
| `ai` | AiOut | ha |  | This month's assistant budget. |
| `chat` | UsedOut | ha |  | Today's assistant questions. |
| `trial_left` | integer \| null | ha |  | Trial launches left; None when paid. |
| `has_plan` | boolean | ha |  |  |

### LiveAdOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `delivery` | string | ha |  |  |
| `delivery_label` | string | ha |  |  |
| `problem` | string | ha |  |  |
| `picture` | string | ha |  |  |
| `is_video` | boolean | ha |  |  |
| `video_url` | string | ha |  |  |
| `text` | string | ha |  |  |
| `headline` | string | ha |  |  |
| `description` | string | ha |  |  |
| `link` | string | ha |  |  |
| `button` | string | ha |  |  |
| `post` | AdPostOut \| null | ha |  |  |

### LiveFormOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `is_synced` | boolean | ha |  | False: only the id is known so far. |
| `name` | string | ha |  |  |
| `questions` | string[] | ha |  |  |
| `custom_questions` | object[] | ha |  |  |
| `leads_count` | integer \| null | ha |  |  |
| `collecting` | boolean | ha |  |  |
| `privacy_url` | string | ha |  |  |
| `locale` | string | ha |  |  |

### ManualMethod

Qiymatlar: `cash`, `transfer`, `card`


### MeOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `user` | PersonOut | ha |  |  |
| `roles` | ChoiceOut[] | ha |  | The roles this reader holds. |
| `can` | CanOut | ha |  |  |
| `waiting` | WaitingOut | ha |  |  |

### MessageOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  | What happened, to show in the message strip. |

### MetaOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `status` | string | ha |  |  |
| `status_label` | string | ha |  |  |
| `name` | string | ha |  | The Facebook profile's name. |
| `expires_at` | datetime \| null | ha |  |  |
| `last_verified_at` | datetime \| null | ha |  |  |
| `last_error_code` | string | ha |  |  |
| `action_required` | boolean | ha |  | Meta asks the customer to confirm. |
| `connected_at` | datetime | ha |  |  |

### MineOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `span` | SpanOut | ha |  |  |
| `me` | MonthOut | ha |  |  |
| `place` | integer | ha |  |  |
| `ranked` | integer | ha |  |  |
| `to_next` | integer \| null | ha |  |  |
| `next_place` | integer \| null | ha |  |  |
| `currency` | string | ha |  |  |
| `percent` | integer | ha |  |  |
| `wallet_minor` | integer | ha |  |  |
| `held` | integer | ha |  |  |
| `sales` | ShareOut[] | ha |  |  |
| `months` | PastMonth[] | ha |  |  |

### MoneyOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `paid` | AmountOut[] | ha |  |  |
| `invoices` | CardInvoiceOut[] | ha |  | The latest 6. |
| `history` | HistoryLineOut[] | ha |  | The latest 10. |
| `old_receipts` | CardInvoiceOut[] | ha |  | A deleted account on this address paid these; attach, do not write the money down twice. |

### MonthOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `manager_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `claimed` | integer | ha |  |  |
| `contacted` | integer | ha |  |  |
| `sold` | integer | ha |  |  |
| `base_minor` | integer | ha |  |  |
| `commission_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `open_now` | integer | ha |  |  |
| `conversion` | any | ha |  |  |

### MovedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `client_id` | string | ha |  |  |
| `placed` | SalesCardOut \| null | ha |  |  |
| `column` | string | ha |  | Where the card sits now; `pool`, or empty. |
| `pooled` | PooledOut \| null | ha |  |  |
| `totals` | object | ha |  | Column -> card count. |
| `pool_total` | integer | ha |  |  |
| `held` | integer | ha |  |  |
| `message` | string | ha |  |  |

### MovePageIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `target` | uuid | ha |  | The page that takes this one's slot. |

### NewCodeIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  | kamida 1, ko'pi 32 |
| `description` | string | yo'q | `""` | ko'pi 255 |
| `is_active` | boolean | yo'q | `true` |  |
| `starts_at` | datetime \| null | yo'q |  | Empty: works at once. |
| `expires_at` | datetime \| null | yo'q |  |  |
| `max_uses` | integer | yo'q | `0` | 0 = no ceiling. min 0.0, max 2147483647.0 |
| `max_uses_per_user` | integer | yo'q | `1` | 0 = no ceiling. min 0.0, max 32767.0 |
| `note` | string | yo'q | `""` | ko'pi 5000 |
| `grant_days` | integer | yo'q | `0` | Kind `plan`. min 0.0, max 32767.0 |
| `plan` | string | yo'q | `""` | Kind `plan`: a plan code, or empty. |
| `grant_pages` | integer | yo'q | `0` | Kind `slots`. min 0.0, max 32767.0 |
| `needs_approval` | boolean | yo'q | `false` | Kinds `plan` and `slots`. |
| `discount_kind` | PromoDiscountKind \| null | yo'q |  | Kind `discount`: `percent` or `amount`. |
| `discount_value` | integer | yo'q | `0` | A percent 1-99, or whole units. min 0.0, max 1000000000000.0 |
| `scope` | PromoScope | yo'q | `"both"` |  |
| `min_amount` | integer | yo'q | `0` | Whole units; 0 = any. min 0.0, max 1000000000000.0 |
| `kind` | PromoKind | ha |  |  |

### NoteIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `body` | string | yo'q | `""` | ko'pi 2000 |

### OutcomeIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `outcome` | string | ha |  |  |
| `callback_at` | datetime \| null | yo'q |  |  |
| `reason` | uuid \| null | yo'q |  |  |
| `term` | HoldTerm | yo'q | `"90"` |  |
| `note` | string | yo'q | `""` | ko'pi 2000 |

### PageAccountIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `current` | string | yo'q | `""` | The pair's ad account id; empty if none. |
| `target` | string | ha |  | kamida 1, ko'pi 64 |

### PageOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `is_active` | boolean | ha |  | In the subscription. |
| `leadgen_subscribed` | boolean | ha |  |  |
| `may_advertise` | boolean \| null | ha |  |  |
| `live_groups` | integer | ha |  |  |
| `pairs` | PairOut[] | ha |  |  |
| `instagrams` | InstagramOut[] | ha |  |  |

### PagesOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `used` | integer | ha |  |  |
| `allowed` | integer \| null | ha |  | None without a live plan. |

### PaidIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `paid` | boolean | yo'q | `false` |  |
| `amount` | number \| string \| null | yo'q |  | Whole units. |
| `method` | ManualMethod \| null | yo'q |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |

### PairOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `ad_account_id` | string | ha |  |  |
| `ad_account_name` | string | ha |  |  |
| `stored` | boolean | ha |  | False: drawn by default, nobody chose it yet. |

### PasswordIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `new_password1` | string | ha |  | kamida 1, ko'pi 128 |
| `new_password2` | string | ha |  | kamida 1, ko'pi 128 |

### PastMonth

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `month` | string | ha |  |  |
| `claimed` | integer | ha |  |  |
| `contacted` | integer | ha |  |  |
| `sold` | integer | ha |  |  |
| `base_minor` | integer | ha |  |  |
| `commission_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |

### PaymentIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `amount` | number \| string | ha |  |  |
| `method` | ManualMethod | ha |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |

### PayoutIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `amount` | number \| string | ha |  | min 1.0 |
| `currency` | string | ha |  | kamida 3, ko'pi 3 |
| `method` | PayoutMethod | ha |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |

### PayoutMethod

Qiymatlar: `card`, `bank`, `cash`


### PayoutOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `status` | string | ha |  |  |
| `status_label` | string | ha |  |  |
| `amount_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `method` | string | ha |  |  |
| `card_last4` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `decided_at` | datetime \| null | ha |  |  |

### PersonOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `email` | string | ha |  |  |

### PixelOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `external_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `is_active` | boolean | ha |  |  |

### PlacementOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `client_id` | string | ha |  |  |
| `placed` | SalesCardOut \| null | ha |  |  |
| `column` | string | ha |  | Where the card sits now; `pool`, or empty. |
| `pooled` | PooledOut \| null | ha |  |  |
| `totals` | object | ha |  | Column -> card count. |
| `pool_total` | integer | ha |  |  |
| `held` | integer | ha |  |  |

### PlanChoiceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  |  |
| `name` | string | ha |  |  |
| `is_active` | boolean | ha |  | False: withdrawn from sale. |
| `currency` | string | ha |  |  |
| `due_minor` | integer | ha |  | What the customer would owe: the amount box. |
| `waits` | boolean | ha |  | Cheaper than the running plan: not until it ends. |

### PlanIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `paid` | boolean | yo'q | `false` |  |
| `amount` | number \| string \| null | yo'q |  | Whole units. |
| `method` | ManualMethod \| null | yo'q |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |
| `plan` | string | ha |  | A plan code; withdrawn plans may be given too. |

### PlanLine

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `plan` | string | ha |  |  |
| `status` | string | ha |  |  |
| `expires_at` | datetime | ha |  |  |

### PlanLineOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  |  |
| `name` | string | ha |  |  |

### PlanPickerOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `choices` | PlanChoiceOut[] | ha |  |  |
| `credit_minor` | integer | ha |  | The unused paid days a change takes off. |
| `credit_days` | integer | ha |  |  |
| `currency` | string | ha |  |  |

### PlanRef

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `code` | string | ha |  |  |
| `name` | string | ha |  |  |

### PlanShareOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `name` | string | ha |  |  |
| `payments` | integer | ha |  |  |
| `amount_minor` | integer | ha |  |  |
| `share_pct` | integer | ha |  | Of the amount. |

### PooledOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `client_id` | string | ha |  |  |
| `is_request` | boolean | ha |  |  |
| `name` | string | ha |  |  |
| `phone` | string | ha |  |  |
| `group` | string \| null | ha |  |  |
| `group_label` | string | ha |  |  |
| `asked_at` | datetime \| null | yo'q |  |  |
| `last_closed` | datetime \| null | yo'q |  |  |
| `last_reason` | string \| null | yo'q |  |  |
| `email` | string \| null | yo'q |  |  |
| `date_joined` | datetime \| null | yo'q |  |  |
| `live_expires` | datetime \| null | yo'q |  |  |
| `live_plan_name` | string \| null | yo'q |  |  |
| `live_status` | string \| null | yo'q |  |  |
| `live_started` | datetime \| null | yo'q |  |  |
| `last_plan_name` | string \| null | yo'q |  |  |
| `last_ended` | datetime \| null | yo'q |  |  |
| `has_paid` | boolean \| null | yo'q |  |  |
| `is_referred` | boolean \| null | yo'q |  |  |
| `last_outcome` | string \| null | yo'q |  |  |
| `is_problem` | boolean \| null | yo'q |  |  |
| `is_asked` | boolean \| null | yo'q |  |  |
| `live_plan_id` | string \| null | yo'q |  |  |

### PoolOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `who` | WhoOut | ha |  |  |
| `chips` | ChipOut[] | ha |  |  |
| `pool_cards` | PooledOut[] | ha |  |  |
| `pool_total` | integer | ha |  |  |
| `pool_next` | integer \| null | ha |  | Pass as `offset` for more; null at the end. |

### ProfileOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `email` | string | ha |  |  |
| `phone` | string | ha |  |  |
| `language` | string | ha |  |  |
| `is_blocked` | boolean | ha |  |  |
| `joined_at` | datetime | ha |  |  |
| `last_login_at` | datetime \| null | ha |  |  |
| `prepared_at` | datetime \| null | ha |  | When preparation finished. |

### PromoCodeOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `code` | string | ha |  |  |
| `kind` | string | ha |  | `plan`, `slots` or `discount`; never edited. |
| `kind_label` | string | ha |  |  |
| `description` | string | ha |  |  |
| `is_active` | boolean | ha |  |  |
| `status` | string | ha |  | `live`, `scheduled`, `spent`, `expired`, `off`. |
| `status_label` | string | ha |  |  |
| `used` | integer | ha |  | Uses spent; a waiting request counts. |
| `percent` | integer | ha |  | How full against `max_uses`; 0 = no ceiling. |
| `starts_at` | datetime \| null | ha |  |  |
| `expires_at` | datetime \| null | ha |  |  |
| `max_uses` | integer | ha |  |  |
| `max_uses_per_user` | integer | ha |  |  |
| `note` | string | ha |  |  |
| `grant_days` | integer | ha |  |  |
| `plan` | PromoPlanOut \| null | ha |  |  |
| `grant_pages` | integer | ha |  |  |
| `needs_approval` | boolean | ha |  |  |
| `discount_kind` | string | ha |  |  |
| `discount_value` | integer | ha |  | A percent, or whole units for `amount`. |
| `scope` | string | ha |  |  |
| `min_amount` | integer | ha |  | Whole units of `currency`. |
| `created_at` | datetime | ha |  |  |

### PromoDiscountKind

Qiymatlar: `none`, `percent`, `amount`


### PromoKind

Qiymatlar: `plan`, `slots`, `discount`


### PromoOffersOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `days` | integer | ha |  |  |
| `pages` | integer | ha |  |  |
| `plan` | string | ha |  |  |

### PromoOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `tab` | string | ha |  |  |
| `requests` | PromoRequestOut[] | ha |  |  |
| `total` | integer | ha |  |  |
| `offset` | integer | ha |  |  |
| `next_offset` | integer | ha |  |  |
| `has_more` | boolean | ha |  |  |
| `current` | PromoCodeOut[] | ha |  | Live, or written in advance. |
| `finished` | PromoCodeOut[] | ha |  | Off, expired, or used up. |
| `currency` | string | ha |  | What fixed discounts and `min_amount` are in. |
| `kinds` | ChoiceOut[] | ha |  |  |
| `discount_kinds` | ChoiceOut[] | ha |  |  |
| `scopes` | ChoiceOut[] | ha |  |  |
| `plans` | ChoiceOut[] | ha |  |  |

### PromoPlanOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  |  |
| `name` | string | ha |  |  |

### PromoRequestOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `customer` | PersonOut | ha |  |  |
| `code` | string | ha |  |  |
| `kind` | string | ha |  |  |
| `kind_label` | string | ha |  |  |
| `description` | string | ha |  |  |
| `offers` | PromoOffersOut | ha |  | What the code gives as it reads now. |
| `redeemed_at` | datetime | ha |  |  |
| `refused_before` | integer | ha |  | This person's earlier refusals; queue only. |
| `status` | string | ha |  |  |
| `status_label` | string | ha |  |  |
| `decided_at` | datetime \| null | ha |  |  |
| `decided_by` | PersonOut \| null | ha |  |  |
| `decision_note` | string | ha |  |  |

### PromoScope

Qiymatlar: `subscription`, `addon`, `both`


### QuoteOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `who` | string | ha |  |  |
| `text` | string | ha |  |  |
| `gone` | boolean | ha |  | The quoted message was taken back. |

### RankedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `manager_id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `claimed` | integer | ha |  |  |
| `contacted` | integer | ha |  |  |
| `sold` | integer | ha |  |  |
| `base_minor` | integer | ha |  |  |
| `commission_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `open_now` | integer | ha |  |  |
| `conversion` | any | ha |  |  |
| `place` | integer | ha |  |  |

### ReasonChangeIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `action` | string | yo'q | `""` |  |
| `label` | string | yo'q | `""` | ko'pi 120 |

### ReasonIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |

### ReasonSavedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  |  |
| `reason` | SalesReasonOut | ha |  |  |

### ReferralIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `mode` | ReferralMode | ha |  |  |

### ReferralMode

Qiymatlar: `auto`, `open`, `closed`


### ReferralOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `mode` | string | ha |  | `auto`, `open` or `closed`. |
| `mode_label` | string | ha |  |  |
| `mode_reason` | string | ha |  |  |
| `mode_set_by` | PersonOut \| null | ha |  |  |
| `open` | boolean | ha |  | Whether the link works and earns. |
| `wallet_payable` | boolean | ha |  |  |
| `inviter` | PersonOut \| null | ha |  |  |
| `invited` | integer | ha |  |  |
| `wallet` | WalletOut[] | ha |  |  |
| `payouts` | PayoutOut[] | ha |  | The latest 6. |

### RefuseIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | kamida 1, ko'pi 500 |

### RemovePairIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `account` | string | ha |  | kamida 1, ko'pi 64 |

### ReorderIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `stage` | string | ha |  |  |
| `c` | string[] | yo'q |  |  |

### RuleHistoryLine

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `percent` | integer | ha |  |  |
| `ending_days` | integer | ha |  |  |
| `valid_from` | datetime | ha |  |  |
| `set_by` | PersonOut \| null | ha |  |  |

### RuleIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `percent` | integer \| null | yo'q |  | min 0.0, max 100.0 |
| `ending_days` | integer | ha |  | min 1.0, max 60.0 |

### RuleOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `percent` | integer | ha |  |  |
| `ending_days` | integer | ha |  | Days before expiry a client counts as ending. |
| `set` | boolean | ha |  |  |

### RuleSavedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  |  |
| `changed` | boolean | ha |  |  |

### RunningOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `about` | string | ha |  | The page, when there are several. |
| `used` | integer | ha |  |  |

### SalesBoardOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `who` | WhoOut | ha |  |  |
| `chips` | ChipOut[] | ha |  |  |
| `pool_cards` | PooledOut[] | ha |  |  |
| `pool_total` | integer | ha |  |  |
| `pool_next` | integer \| null | ha |  | Pass as `offset` for more; null at the end. |
| `columns` | SalesColumnOut[] | ha |  |  |
| `held` | integer | ha |  | Clients this manager holds now. |
| `managers` | PersonOut[] | ha |  | For the `m` filter; leads only. |
| `cursor` | string | ha |  | Send to `GET /office/sales/pulse`. |
| `nothing_found` | boolean | ha |  |  |
| `stages` | object | ha |  |  |
| `outcomes` | object | ha |  | Values for `outcome`. |
| `hold_terms` | object | ha |  | Values for `term`. |

### SalesCardOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `client_id` | string | ha |  | A user id, or a request (ariza) id. |
| `name` | string | ha |  |  |
| `phone` | string | ha |  |  |
| `is_request` | boolean | ha |  | A website request, not a signed-up user. |
| `group` | string | ha |  | `ariza`, `problem`, `new`, `back`, `ending`, ... |
| `group_label` | string | ha |  |  |
| `stage` | string | ha |  |  |
| `outcome` | string | ha |  |  |
| `column` | string | ha |  | `taken`, `no_answer`, `callback`, `thinking`, `using`, `awaiting`, `lost`; empty once closed. |
| `attempts` | integer | ha |  |  |
| `callback_at` | datetime \| null | ha |  |  |
| `claimed_at` | datetime \| null | ha |  |  |
| `expires_at` | datetime \| null | ha |  | When the claim lapses. |
| `extended_at` | datetime \| null | ha |  |  |
| `contacted_at` | datetime \| null | ha |  |  |
| `closed_at` | datetime \| null | ha |  |  |
| `manager` | PersonOut \| null | ha |  |  |
| `reason` | string | ha |  |  |
| `invoice` | string | ha |  |  |
| `live` | PlanLine \| null | ha |  | The client's running plan. |

### SalesColumnOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `key` | string | ha |  |  |
| `label` | string | ha |  |  |
| `total` | integer | ha |  |  |
| `hidden` | integer | ha |  |  |
| `cards` | SalesCardOut[] | ha |  |  |

### SalesConsultOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `name` | string | ha |  |  |
| `phone` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |

### SalesHistoryLine

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `kind` | string | ha |  |  |
| `label` | string | ha |  |  |
| `actor` | PersonOut \| null | ha |  |  |
| `reason` | string | ha |  |  |
| `body` | string | ha |  |  |
| `callback_at` | datetime \| null | ha |  |  |
| `created_at` | datetime | ha |  |  |

### SalesMessageOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  |  |

### SalesPulseOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `columns` | SalesColumnOut[] | ha |  |  |
| `cursor` | string | ha |  |  |
| `held` | integer | ha |  |  |

### SalesReasonIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `label` | string | ha |  | kamida 1, ko'pi 120 |

### SalesReasonOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `label` | string | ha |  |  |
| `position` | integer | ha |  |  |
| `archived_at` | datetime \| null | ha |  |  |

### SalesReportOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `span` | SpanOut | ha |  |  |
| `live` | boolean | ha |  |  |
| `closed` | boolean | ha |  |  |
| `months` | string[] | ha |  | `YYYY-MM` values for `oy`. |
| `rows` | MonthOut[] | ha |  |  |
| `currency` | string | ha |  |  |
| `totals` | MonthOut | ha |  |  |
| `picked` | string \| null | ha |  |  |
| `picked_sales` | ShareOut[] | ha |  |  |
| `reasons` | ShareBar[] | ha |  |  |
| `sources` | ShareBar[] | ha |  |  |

### SalesSettingsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `who` | WhoOut | ha |  |  |
| `rule` | object | ha |  |  |
| `may_set_percent` | boolean | ha |  |  |
| `history` | RuleHistoryLine[] | ha |  |  |
| `reasons` | SalesReasonOut[] | ha |  |  |
| `segments` | SegmentOut[] | ha |  |  |

### SegmentIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `plan` | uuid | ha |  |  |
| `days` | integer | ha |  | min 1.0, max 365.0 |

### SegmentOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `key` | string | ha |  | Use as the `g` chip. |
| `plan` | PlanRef | ha |  |  |
| `days` | integer | ha |  |  |

### SegmentSavedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `message` | string | ha |  |  |
| `segment` | SegmentOut | ha |  |  |

### SentOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `already_sent` | boolean | ha |  | A repeat of a press already stored. |
| `message` | SupportMessageOut \| null | ha |  |  |

### ShareBar

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `label` | string | ha |  |  |
| `count` | integer | ha |  |  |
| `width` | integer | ha |  | Bar width, percent of the largest. |

### ShareOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `client` | PersonOut \| null | ha |  |  |
| `invoice` | string | ha |  |  |
| `plan` | string | ha |  |  |
| `base_minor` | integer | ha |  |  |
| `percent` | integer | ha |  |  |
| `amount_minor` | integer | ha |  |  |
| `currency` | string | ha |  |  |
| `earned_at` | datetime | ha |  |  |

### SliceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `amount_minor` | integer | ha |  |  |
| `payments` | integer | ha |  |  |
| `signups` | integer | ha |  |  |
| `average_minor` | integer | ha |  |  |
| `online_minor` | integer | ha |  |  |
| `manual_minor` | integer | ha |  |  |
| `plans` | PlanShareOut[] | ha |  |  |

### SlotsIn

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `reason` | string | ha |  | Why - it goes to the journal. kamida 1, ko'pi 500 |
| `paid` | boolean | yo'q | `false` |  |
| `amount` | number \| string \| null | yo'q |  | Whole units. |
| `method` | ManualMethod \| null | yo'q |  |  |
| `pay_reference` | string | yo'q | `""` | ko'pi 128 |
| `pages` | integer | ha |  | min 1.0, max 20.0 |
| `take` | boolean | yo'q | `false` | Take room back instead of giving it. |

### SpanOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `month` | string | ha |  | `YYYY-MM`. |
| `start` | datetime | ha |  |  |
| `end` | datetime | ha |  |  |

### StickerOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `code` | string | ha |  |  |
| `emoji` | string | ha |  |  |
| `name` | string | ha |  |  |

### SubscriptionOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `plan` | PlanLineOut \| null | ha |  |  |
| `status` | string | ha |  |  |
| `status_label` | string | ha |  |  |
| `started_at` | datetime | ha |  |  |
| `expires_at` | datetime | ha |  |  |
| `ended_at` | datetime \| null | ha |  |  |
| `days_left` | integer \| null | ha |  | Live only; 0 is today. |
| `extra_pages` | integer | ha |  |  |
| `setup_completed_at` | datetime \| null | ha |  |  |
| `activated_by` | PersonOut \| null | ha |  |  |
| `note` | string | ha |  |  |

### SupportMessageOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `side` | string | ha |  | `client` or `office`: who wrote it. |
| `own` | boolean | ha |  | The reader wrote it: drawn on the right. |
| `who` | string | ha |  | `Siz` or `Qo'llab-quvvatlash` for the client. |
| `kind` | string | ha |  | `text`, `image`, `video`, `file`, `voice` or `sticker`. |
| `body` | string | ha |  |  |
| `sticker` | string | ha |  | Sticker code; draw `stickers/<code>.svg`. |
| `sticker_name` | string | ha |  |  |
| `sticker_emoji` | string | ha |  |  |
| `files` | FileOut[] | ha |  |  |
| `quote` | QuoteOut \| null | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `at` | integer | ha |  | `created_at` in milliseconds. |
| `edited_at` | datetime \| null | ha |  |  |
| `deleted_at` | datetime \| null | ha |  | Set: draw `Xabar o'chirildi`. |
| `editable` | boolean | ha |  |  |
| `deletable` | boolean | ha |  |  |
| `repliable` | boolean | ha |  |  |
| `read` | boolean | ha |  | Own message the other side has read: two ticks. |
| `preview` | string | ha |  | The message in one line. |

### SupportQueueOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `state` | string | ha |  |  |
| `states` | ChoiceOut[] | ha |  |  |
| `rows` | SupportRowOut[] | ha |  |  |
| `total` | integer | ha |  |  |
| `offset` | integer | ha |  |  |
| `next_offset` | integer | ha |  |  |
| `has_more` | boolean | ha |  |  |

### SupportRowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  | The chat's id: `GET /office/support/{id}`. |
| `customer` | PersonOut | ha |  |  |
| `waiting` | boolean | ha |  | The client spoke last and nobody settled it. |
| `last_message_at` | datetime \| null | ha |  |  |
| `last_client_at` | datetime \| null | ha |  |  |
| `preview` | string | ha |  | The last message in one line. |
| `last_side` | string | ha |  | `client` or `office`: who wrote it. |

### SupportSendForm

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `body` | string | yo'q | `""` | The words. |
| `attachments` | string[] \| null | yo'q |  | Up to 10 pictures, videos, documents. |
| `voice` | string \| null | yo'q |  | webm, ogg, m4a or mp3. |
| `voice_seconds` | integer \| null | yo'q |  | The recording's length. |
| `sticker` | string | yo'q | `""` | A sticker code. ko'pi 32 |
| `reply_to` | string | yo'q | `""` | The message answered. ko'pi 64 |
| `send_key` | string | yo'q | `""` | The screen's `send_key`. ko'pi 64 |
| `nonce` | string | yo'q | `""` | Echoed on the socket. ko'pi 64 |

### SupportStartForm

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `body` | string | yo'q | `""` | The words. |
| `attachments` | string[] \| null | yo'q |  | Up to 10 pictures, videos, documents. |
| `voice` | string \| null | yo'q |  | webm, ogg, m4a or mp3. |
| `voice_seconds` | integer \| null | yo'q |  | The recording's length. |
| `sticker` | string | yo'q | `""` | A sticker code. ko'pi 32 |
| `reply_to` | string | yo'q | `""` | The message answered. ko'pi 64 |

### SupportThreadOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `customer` | PersonOut | ha |  |  |
| `conversation_id` | string \| null | ha |  | Empty: no chat yet; the first message writes it. |
| `waiting` | boolean | ha |  |  |
| `messages` | SupportMessageOut[] | ha |  |  |
| `page` | integer | ha |  |  |
| `pages` | integer | ha |  |  |
| `has_previous` | boolean | ha |  |  |
| `has_next` | boolean | ha |  |  |
| `client_read_at` | datetime \| null | ha |  | The client's second tick. |
| `send_key` | string | ha |  |  |
| `ws_path` | string | ha |  | Add `?token=`; empty without a chat. |
| `composer` | ComposerOut | ha |  |  |

### TakingsOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `window` | WindowOut | ha |  |  |
| `currency` | string | ha |  |  |
| `bars` | BarOut[] | ha |  |  |
| `picked` | string | ha |  |  |
| `shown` | SliceOut | ha |  | The picked bar, or the whole window. |
| `before_minor` | integer | ha |  | The same number of days just before. |
| `change_pct` | integer \| null | ha |  |  |
| `unpaid` | integer | ha |  | Bills waiting to be paid, now. |
| `unpaid_minor` | integer | ha |  |  |
| `given_free` | integer | ha |  | Plans, days, pages the office gave free. |

### TeamOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `span` | SpanOut | ha |  |  |
| `podium` | RankedOut[] | ha |  |  |
| `table` | RankedOut[] | ha |  |  |
| `mine` | RankedOut | ha |  |  |
| `to_next` | integer \| null | ha |  |  |
| `next_place` | integer \| null | ha |  |  |
| `currency` | string | ha |  |  |
| `previous` | SpanOut | ha |  |  |
| `last_winner` | MonthOut \| null | ha |  |  |

### TelegramOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `username` | string | ha |  |  |
| `is_active` | boolean | ha |  |  |
| `linked_at` | datetime \| null | ha |  |  |
| `last_error_at` | datetime \| null | ha |  |  |

### TermOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `state` | string | ha |  | `trial`, `active` (live), `lapsed` (paid once, ended) or `never` (no subscription ever). |
| `label` | string | ha |  |  |
| `plan` | PlanLineOut \| null | ha |  | Live plan, else the last one. |
| `days_left` | integer \| null | ha |  | Live only; 0 is today. |
| `expires_at` | datetime \| null | ha |  | Live only. |
| `ended_on` | datetime \| null | ha |  | Lapsed only. |

### TraceOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `id` | string | ha |  |  |
| `created_at` | datetime | ha |  |  |
| `kind` | string | ha |  |  |
| `kind_label` | string | ha |  |  |
| `reason` | string | ha |  |  |
| `detail` | object | ha |  |  |
| `actor` | PersonOut \| null | ha |  | Gone when that member was removed. |

### TroubleOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `kind` | string | ha |  | `connection`, `account_blocked`, `payment_due`, `lead_gap`, `sweep`, `launch`, `hold`, `expiring`, `setup`. |
| `label` | string | ha |  |  |
| `what` | string | ha |  |  |
| `urgent` | boolean | ha |  |  |
| `since` | datetime \| null | ha |  |  |

### UsedOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `used` | integer | ha |  |  |
| `allowed` | integer | ha |  | 0 is no limit. |

### WaitingOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `promos` | integer | ha |  |  |
| `asks` | integer | ha |  | Withdrawal requests waiting to be paid. |
| `feedback` | integer | ha |  |  |
| `support` | integer | ha |  | Chats whose customer spoke last. |
| `arizas` | integer | ha |  | Home page call-back requests in the sales queue. |

### WalletOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `currency` | string | ha |  |  |
| `earned_minor` | integer | ha |  |  |
| `paid_minor` | integer | ha |  |  |
| `spent_minor` | integer | ha |  |  |
| `held_minor` | integer | ha |  |  |
| `available_minor` | integer | ha |  |  |

### WhoOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `user` | PersonOut | ha |  |  |
| `is_lead` | boolean | ha |  | Sees every manager's cards. |
| `is_owner` | boolean | ha |  |  |
| `chip` | string | ha |  | The `g` applied. |
| `manager` | string | ha |  | The `m` applied. |
| `term` | string | ha |  | The `q` applied, after cleaning. |
| `rule` | RuleOut | ha |  |  |
| `segments` | SegmentOut[] | ha |  |  |

### WindowOut

| Maydon | Tur | Majburiy | Standart | Izoh |
|---|---|---|---|---|
| `period` | string | ha |  |  |
| `unit` | string | ha |  | One bar: `day`, `week` or `month`. |
| `since` | date | ha |  |  |
| `until` | date | ha |  |  |
| `days` | integer | ha |  |  |
| `refused` | string | ha |  | Why a typed range was not used; else empty. |
| `periods` | ChoiceOut[] | ha |  |  |
