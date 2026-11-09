# Reklama boshqaruvi — frontend uchun (7–8-noyabr o'zgarishlari)

Bu hujjatda 2026-11-07/08 kunlari backend'da qo'shilgan yoki o'zgargan
API'lar va har birining vazifasi yozilgan. Dizayn shu ma'lumotga
tayanib qayta chiziladi.

**Umumiy qoidalar**
- Barcha manzillar `/api/v1` bilan boshlanadi va `Authorization: Bearer <token>` talab qiladi.
- Maydon nomlari quyidagi misollarda qanday yozilgan bo'lsa, javobda ham aynan shunday keladi:
  - `/campaigns/...` javoblari **camelCase**da;
  - `/agent` va xabarlar javoblari **snake_case**da.
- So'rov tanasida `/campaigns/...` uchun camelCase ham, snake_case ham qabul qilinadi.
- Xatolar:
  - `422` → `problems: {maydon: "matn"}` keladi. Matnni o'sha maydonning ostida ko'rsating.
  - `422` / `404` / `409` → `detail` yoki `message` keladi. Toast yoki maydon ostida ko'rsating.
- **Meta'ga ketadigan har bir o'zgarish darhol bajarilmaydi.** Bunday so'rovlar ikki xil javob qaytaradi:
  - `actionId` → holatini `GET /campaigns/actions/{actionId}` bilan kuzating. `polling: true` bo'lsa, qayta so'rang.
  - `ControlState` → `pending: true` bo'lsa, `pollSeconds` soniyadan keyin qayta so'rang.

  Kutish paytida tugma "yuborilmoqda" holatida turishi kerak. Natija kelganda yashil yoki qizil xabar chiqadi.
  Rad etilsa, `failure` / `refused` / `explanationHtml` ichidagi matnni ko'rsating.

---

## 1. Kampaniya nomini o'zgartirish (TZ 4) — YANGI

`POST /campaigns/{campaign_id}/name`

```json
{ "name": "Yangi nom" }
```

- **Javob:** `ControlState` (yuqoridagi umumiy qoida bo'yicha kuzatiladi).
- **Cheklovlar:** nom bo'sh bo'lmasligi va 100 belgidan oshmasligi kerak. Aks holda `422 problems.name` qaytadi.
- **Faqat Meta kampaniyasi uchun.** Boshqa platformadagi kampaniya rad etiladi.
- Bu o'zgarishni orqaga qaytarish (undo) mumkin. Undo boshqa o'zgarishlarniki kabi Harakatlar tarixidan qilinadi va eski nom aynan qaytadi.
- Yangi guruh yoki yangi reklama qo'shishda **nom endi so'ralmaydi.** `POST /campaigns/{id}/adsets/new` va `POST /campaigns/adsets/{id}/ads/new` tanasida `name` maydoni yo'q. Tizim nomni o'zi qo'yadi.

**UX:**
- Nom joyida tahrirlanadi: bosiladi → maydonga aylanadi → Enter yoki ✓.
- Yonida belgilar soni chiqadi (`x/100`).
- Saqlanayotganda nom xira ko'rinadi va yonida spinner aylanadi.

---

## 2. Duplikat — nusxa olish (TZ 2.1–2.3) — YANGI

Uchala daraja ham `202` va `{ "actionId": "..." }` qaytaradi. Shundan keyin `GET /campaigns/actions/{actionId}` bilan kuzatiladi.

### 2.1 Kampaniya

`POST /campaigns/{campaign_id}/copy`, tanasi yo'q.

- Nusxa **to'xtatilgan** holatda yaratiladi, nomi `«… — nusxa»` bo'ladi.
- Katta kampaniya fonda nusxalanadi. Tayyor bo'lganda xabarlar ro'yxatida `kind: "copy"` keladi (5-bo'limga qarang).

### 2.2 Guruh

1. `GET /campaigns/adsets/{external_id}/copy` — guruhni qaysi kampaniyalarga ko'chirish mumkin:
   ```json
   { "places": [ { "id": "...", "name": "...", "running": true, "own": true } ] }
   ```
   Birinchi element — guruhning o'z kampaniyasi (`own: true`).
2. `POST /campaigns/adsets/{external_id}/copy`
   ```json
   { "into": "<kampaniya external id>" }
   ```
   `into: ""` bo'lsa, nusxa o'sha kampaniyaning o'ziga tushadi. Guruh reklamalari bilan, to'xtatilgan holatda ko'chadi.

### 2.3 Reklama

1. `GET /campaigns/ads/{external_id}/copy` — reklamani qaysi guruhlarga ko'chirish mumkin. Javob tuzilishi 2.2 dagi bilan bir xil.
2. `GET /campaigns/ads/{external_id}/copy/creative` — "yangi kreativ bilan" variant uchun forma. Asl reklama matnlari, kutubxona, formalar, `welcome`, shuningdek:
   ```json
   { "button": "LEARN_MORE", "buttons": [ { "key": "LEARN_MORE", "label": "Batafsil" } ] }
   ```
   Tugma so'zini o'zgartirib bo'lmaydigan reklamada `buttons` ro'yxatida faqat joriy tugma keladi.
3. `POST /campaigns/ads/{external_id}/copy`
   ```json
   {
     "into": "",                // "" — o'z guruhi, "<guruh id>" — boshqa guruh, "new" — yangi guruh
     "creative": {               // berilmasa — asl reklama aynan nusxalanadi
       "message": "...", "headline": "...", "description": "...",
       "picture": "<library qatori id>",
       "leadForm": "<forms.options dan id>",
       "button": "<buttons[].key>",
       "welcome": { "text": "...", "questions": [ { "title": "...", "response": "..." } ] }
     }
   }
   ```
   - Ishlab turgan guruhga tushgan nusxa **faol** bo'ladi. `"new"` (yangi guruh) bo'lsa, nusxa **to'xtatilgan** bo'ladi.
   - Kutubxonada yo'q rasm yuborilsa, `422 "Bu rasm kutubxonada yo'q."` qaytadi.

**UX (Duplikat oynasi):**
- 1-qadam: **qayerga** — ro'yxatdan tanlanadi, `own` yonida "joriy" belgisi bo'ladi.
  Ishlab turgan joylar (`running`) yashil nuqta bilan ajratiladi.
- 2-qadam (faqat reklama uchun): **"Aynan nusxa"** yoki **"Yangi kreativ bilan"**.
- Natija qanday holatda yaratilishi tugma ustida oldindan yozilsin: "faol bo'ladi" yoki "to'xtatilgan holatda yaratiladi".

---

## 3. Mavjud reklamani o'zgartirish (TZ 2.4–2.6) — O'ZGARDI

### 3.1 Tahrirlash formasi

`GET /campaigns/ads/{external_id}/edit` javobiga yangi maydon qo'shildi:

```json
"welcome": { "text": "...", "questions": [ { "title": "...", "response": "..." } ],
             "maxQuestions": 4, "maxChars": 80 }   // chat ochmaydigan reklamada: null
```

### 3.2 Saqlash

`POST /campaigns/ads/{external_id}/edit` tanasiga yangi maydonlar qo'shildi:

| Maydon | Ma'nosi |
|---|---|
| `welcome` | Chat salomlashuvi va tez savollar (savol + javob). Berilmasa, o'zgarmaydi. |
| `inPlace` | `true` — **shu reklamaning o'zi** o'zgaradi. Meta reklamani qayta ko'rib chiqadi, layk va izohlar noldan boshlanadi. `false` — yangi reklama yaratiladi va eskisi to'xtatiladi. |

UX: `inPlace` tanlovini ikki variantli tanlov sifatida bering va **oqibatini ochiq yozing**. Foydalanuvchi layklar yo'qolishini bilishi shart.

### 3.3 Yangi lid formasi

`POST /campaigns/ads/{external_id}/forms`

```json
{ "name": "Forma nomi", "questions": ["Qaysi xizmat kerak?", "..."] }
```

- Ism va telefon har doim birinchi so'raladi. `questions` — ulardan keyingi qisqa savollar, 15 tagacha.
- Javob: `{ "id": "...", "name": "..." }`. Yangi formani shu zahoti tanlangan holatga qo'ying.
- Meta formani rad etsa, `422 detail` qaytadi.
- Obunasi tugagan foydalanuvchiga ham rad javobi qaytadi.
- **Tugmani ikki marta bosishdan himoya backend'da yo'q.** So'rov ketayotganda tugmani o'chirib qo'ying.

### 3.4 Kampaniya daraxtidagi reklama qatorlari

Har bir reklama qatoriga yangi maydonlar qo'shildi:

- `opens: "form" | "chat" | null` — reklama tugmasi nimani ochadi:
  - `form` bo'lsa, menyuda **«Lid formani almashtirish»** chiqadi;
  - `chat` bo'lsa, **«Xabar shablonini o'zgartirish»** chiqadi.
- `canSwap: false` — reklama matni post ichida turibdi, uni almashtirib bo'lmaydi. Tugmani yashiring yoki sababini yozib o'chiring.

---

## 4. Natija hodisasi va pixel (TZ 3) — O'ZGARDI

Bu bo'lim reklama yaratish qoralamasiga tegishli: `GET /launch/drafts/{id}` → `edit.adv[]` qatorlari.

- `key: "conversion_event"` qatorida endi **`hints`** bor. U har bir variantga mos, xuddi shu tartibda keladi:
  ```json
  { "meta": "7 kunda 312 ta", "warn": "", "group": "event" }   // group: event | custom | ""
  ```
- `key: "pixel_id"` qatorida ham `hints[].meta` keladi (har bir pixelning 7 kunlik soni).
- `warn` matnlari:
  - «Bu event saytingizdan kelmayapti…» — 7 kunda 0 ta;
  - «Event kam, reklama sekin o'rganadi.» — 10 tadan kam.

  **Bu faqat ogohlantirish, tanlov baribir ruxsat etiladi.**
- `group: "custom"` — bu custom conversion. Uning kaliti `cc:<id>` ko'rinishida. Ro'yxatda alohida sarlavha ostida ko'rsating.
- Saqlash: `PATCH /launch/drafts/{id}` → `advanced.pixel_id` va `advanced.conversion_event`.
  Pixel va hodisa **bitta so'rovda** yuborilishi mumkin. Hodisa yuborilgan pixel bo'yicha tekshiriladi.
- Kampaniya maqsadini endi hodisa belgilaydi: so'rov turidagi hodisa → Leads, xarid turidagi hodisa → Sales.
- Kampaniya ro'yxatida, v2 sahifada va bot hisobotida natija endi tanlangan hodisa nomi bilan chiqadi (masalan «Arizalar», «Sahifa ko'rishlar»).

**UX:**
- Har bir variant ikki qatorda chiqadi: tepada nomi, ostida kulrang `meta`.
- `warn` bo'lsa, sariq belgi chiqadi va matn variant ostida ko'rinadi.

---

## 5. Instagram joylashuvi (TZ 5) — MATN O'ZGARDI

API o'zgarmadi, faqat matnlar yangilandi:
- Instagram rejimi endi Explore'ni ham o'z ichiga oladi. Joylashuvlar ro'yxatida yangi qator bor: `explore_home: "Instagram Explore"`.
- Instagram'siz sahifa uchun `no_instagram` ogohlantirishi:
  «Instagram ulanmagan - reklama Facebook'da ko'rsatiladi. Instagram'da yoqmoqchi bo'lsangiz, Instagram'ni ulang yoki supportga yozing.»
  Uning yonida ikki tugma bo'lsin: **Instagram'ni ulash** va **Supportga yozish**.

---

## 6. Meta maslahatlari olib tashlandi (TZ 7) — O'CHIRILDI

- Kampaniya sahifasidagi `notes` (Meta tavsiyalari) maydoni **olib tashlandi**. Shu blokni dizayndan ham olib tashlang.
- Xabarlar ro'yxatiga Meta maslahatlari endi kelmaydi.
- Jadvallarda `recommendations` maydoni hali qaytadi, lekin **uni ko'rsatmang**.

---

## 7. Chastota darajalari (TZ 6) — YANGI / O'ZGARDI

Darajalar: **2.00 / 2.50 / 3.00**.

### 7.1 Dashboard tepasi — YANGI

`GET /agent/frequency/pressing`

```json
{ "alerts": [ { "id": "...", "level": "warning", "title": "...", "body": "..." } ] }
```

- `level: "warning"` (2.50) — sariq banner.
- `level: "required"` (3.00) — qizil banner.
- Ro'yxat bo'sh bo'lsa, hech narsa chizilmaydi.

### 7.2 Amallar ro'yxati

`GET /agent` → `frequency[]`:

```json
{ "id", "adset_external_id", "level", "frequency", "title", "body", "answer", "created_at",
  "buttons": { "fine": "Reklama yaxshi ishlayapti", "creative": "Qo'shimcha kreativ qo'shamiz" } }
```

Tugmalar:
- **fine** → `POST /agent/frequency/{id}/fine`
- **creative** → `GET /agent/frequency/{id}/creative`. Javob `{ "externalId", "campaignId" }`.
  Shundan keyin kampaniya sahifasini (`campaignId`) oching va shu reklama (`externalId`) uchun **Duplikat → Yangi kreativ bilan** oynasini darhol ochiq holda ko'rsating.
  - **O'ZGARDI:** oldin bu so'rov `edit_url` qaytarardi, endi qaytarmaydi.

---

## 8. Lid narxi 3 barobar oshdi (TZ 1) — YANGI

### 8.1 Amallar ro'yxati

`GET /agent` → yangi **`price[]`** ro'yxati:

```json
{ "id", "adset_external_id", "ad_external_id", "times": 3.4, "title", "body", "created_at",
  "buttons": { "creative": "Yangi kreativ qo'shish", "pause": "Reklamani to'xtatish", "watch": "Kuzataman" } }
```

`body` ichida sabablar (ko'pi bilan ikkita) va ularni tuzatish yo'li yozilgan. Agar shu guruhda chastota ogohlantirishi ham bo'lsa, u ham shu matnga qo'shilgan. U holda bu ogohlantirish `frequency[]` ro'yxatida alohida kelmaydi.

Tugmalar:
- **creative** → `GET /agent/price/{id}/creative`. Javob va ochiladigan oyna 7.2 dagi bilan bir xil.
- **pause** → `POST /agent/price/{id}/pause`. Bosishdan oldin **tasdiqlash oynasi** chiqsin.
- **watch** → `POST /agent/price/{id}/watch`. Shundan keyin 72 soat davomida bu guruh haqida xabar kelmaydi.

Eski 2 barobarlik «Qimmatlashdi» qatori olib tashlandi.

UX: bu kartochka **shoshilinch** turdagi. Rangi qizil bo'lsin, `times` yirik raqam bilan ko'rsatilsin («×3.4»), uchta tugma bir qatorda tursin, asosiy tugma — «Yangi kreativ qo'shish».

---

## 9. Xabarlar ro'yxati (inbox) — YANGI turlar

`InboxItem.kind` ga yangi qiymatlar qo'shildi:

| `kind` | Darajasi | Ma'nosi |
|---|---|---|
| `price` | `urgent` | 8-bo'limdagi narx oshishi. Tugmalari `actions[]` ichida keladi, `confirm` bo'lsa tasdiqlash oynasi chiqsin. |
| `copy` | `news` | «Kampaniya nusxasi tayyor: «… — nusxa»». `href` kampaniyalar ro'yxatiga olib boradi. |

---

## 10. Lidlarni tekshirish — MATN O'ZGARDI

`POST /connections/meta/leads/recheck` endi «tekshirilmoqda… bir necha daqiqada «Mijozlar»ga tushadi» degan matn qaytaradi.

Bu so'rov joriy sahifaning o'tkazib yuborilgan lidlarini ham tortib oladi.

`POST /connections/meta/pages/{page_id}/leads` endi sahifalarni qayta o'qiydi, shuning uchun lead terms holati yangilanadi. «Qabul qildim» bosilgandan keyin sahifa holatini shu yo'l bilan yangilang.

«Lid topilmadi» kabi o'zingizdan yozilgan natija ko'rsatmang. Backend qaytargan matnni chiqaring, so'ng kartochkani biroz keyin qayta o'qing.

---

## Dizayn uchun umumiy talablar

1. **Har bir Meta amalida uch holat bor:** yuborilmoqda → bajarildi / rad etildi. Tugma bosilgandan keyin javob kelguncha ikkinchi marta bosib bo'lmasin.
2. **Oqibati og'ir amallar tasdiq so'rasin:** to'xtatish, `inPlace: true`, butun kampaniya nusxasi.
3. **Natija holati oldindan yozilsin:** nusxa faol bo'ladimi yoki to'xtatilgan holatda yaratiladimi.
4. **Ogohlantirish bilan xato farqlansin:** `warn` (sariq) tanlovni to'xtatmaydi, `422` (qizil) esa to'xtatadi.
5. **Matnlar backend'dan keladi** (`title`, `body`, `buttons`, `label`). Ularni frontend'da qayta yozmang, faqat ko'rsating.
6. Telefonda ham tekshiring: Duplikat oynasi va narx kartochkasi ekranga sig'ishi kerak.
