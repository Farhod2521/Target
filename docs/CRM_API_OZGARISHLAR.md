# CRM API o'zgarishlari — 2026-10-31

Frontend uchun. Asosiy hujjat: [CRM_API.md](CRM_API.md).

**Qisqasi:** 2 ta o'zgarish frontendda ish talab qiladi (1-bo'lim). Qolganlari
avtomatik ishlaydi, frontend hozirgi holatida buzilmaydi.

---

## 1. Frontendda qilinadigan ishlar

### 1.1 Menejer o'rni haqidagi haqiqiy holatni ko'rsatish (muhim)

**Muammo:** ega menejer qo'shadi, "qo'shildi" xabarini ko'radi, menejer esa
yopiq ekranga tushadi (`409 seat`). Sabab: `packages/api/src/live/bridges/crm.ts`
da `seated: true` qat'iy yozilgan va `seats.paid: members.length + 1` doim bitta
bo'sh o'rin ko'rsatadi.

**Backendda yangi maydon:** `GET /crm/settings` va `POST /crm/setup/{step}`
javobida:

```json
{ "seat_open": true }
```

`true` — hozir qo'shiladigan menejer shu juftlikda o'ringa sig'adi. `false` —
menejer baribir qo'shiladi, lekin `seated: false` bo'ladi va kira olmaydi.

**Kerakli o'zgarishlar:**

1. API tiplarini qayta generatsiya qilish (`SettingsOut.seat_open` qo'shildi).
2. `toMember`da `seated: true` o'rniga `seated: m.seated`.
3. `toSetup`da `seat_open`ni olib, `Members` blokida `team < paid` tekshiruvi
   o'rniga ishlatish.
4. `seat_open: false` bo'lganda qo'shishdan oldin ogohlantirish chiqarish.
5. Ro'yxatda `seated: false` menejerni belgilash ("O'rin yo'q — kira olmaydi").

O'rinni mijozning o'zi sotib olish endpointi hali yo'q, shuning uchun `seats`
feature o'chiq qoladi. Matnda sotib olish tugmasini va'da qilmang.

### 1.2 Karta oynasida o'rinsiz menejerni tanlatmaslik

`GET /crm/cards/{id}` → `members[].seated` endi to'g'ri keladi (oldin doim
`true` edi). "Menejer" ro'yxatida `seated: false` menejerni o'chirib qo'ying.
Tanlansa, backend `400 member_not_seated` qaytaradi.

---

## 2. Tuzatilgan: frontend o'zgarishi shart emas

| So'rov | Oldin | Endi |
|---|---|---|
| `POST /crm/setup/skip-members` | Doim `422` — "Men o'zim ishlayman" ishlamasdi | `200`, 3-qadamga o'tadi. Ustunlar yaratilmagan bo'lsa `409 {"detail": {"step": 1}}` |
| `GET /crm/nav` (menejer) | `{"url": "/app/leads/", "attention": 0}` | `{"url": "/app/crm/", "attention": N}` — o'z kartalari sanaladi |
| `PUT /crm/settings/members/{id}`, `POST .../password` | `seated` doim `true` | Haqiqiy qiymat |
| `GET /crm?q=` (NUL belgili) | `500` | `200`, NUL tashlab yuboriladi |

---

## 3. Yangi rad etishlar

Javob shakli o'zgarmagan: `400 {"detail": "<matn>", "code": "<kod>"}`, matn
foydalanuvchiga ko'rsatishga tayyor. `useRefusal` ularni o'zi chiqaradi.

| `code` | Qachon | Matn |
|---|---|---|
| `card_is_closed` | Yopilgan kartada `take`, `note`, `no-answer`, `due`, `due/done`. Sotilganga yana `win`, rad etilganga yana `lose` | Bu karta yopilgan. Avval uni boshqa ustunga o'tkazing. |
| `member_not_seated` | `assign` — o'rinsiz menejerga | Bu menejerda o'rin yo'q: u kartani ocha olmaydi. |
| `bad_email` | `POST /crm/settings/members` — noto'g'ri yoki bo'sh email | Email manzilini to'g'ri kiriting. |
| `amount_too_big` | `win` — summa 10^15 dan katta (oldin `500`) | Summa juda katta. Tekshirib qayta kiriting. |
| `bad_kpi` (eski kod) | `kpi_fix` 10^15 dan katta (oldin `500`) | Fix maosh va foizni raqam bilan yozing (foiz 0 dan 100 gacha). |

**Yopilgan kartada ishlashda davom etadi:** doskada sudrash (`move` — qayta
ochadi), rad etilganni `win`, sotilganni `lose` (natijani almashtiradi), egasi
uchun `assign`. Hozirgi doska va oyna oqimlari o'zgarmaydi.

Bir vaqtda ochiq eski oynada (boshqa odam kartani yopgan bo'lsa) tugma bosilsa
endi xato chiqadi. Oynani yangilash kifoya.

---

## 4. Qattiqroq validatsiya (`422`)

Frontend hozir to'g'ri yuboradi, faqat ma'lumot uchun.

| So'rov | Qoida |
|---|---|
| `POST /crm/cards/{id}/due` | `due` vaqt zonasi bilan bo'lishi shart: `toISOString()` to'g'ri. `2030-01-01T10:00:00` — `422` (oldin `500`) |
| `POST /crm/settings/state` | `state` faqat `"on"` yoki `"off"`. Boshqa qiymat oldin CRM'ni o'chirib yuborardi |
