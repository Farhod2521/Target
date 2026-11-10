# AI chat → Support: javob topilmasa mutaxassisga o'tkazish

AI yordamchi (`/chat`) savolga aniq javob topa olmasa (to'lov, bloklangan akkaunt,
xato, mahsulot haqida javobi yo'q savol yoki mijoz "operator kerak" desa), savol
**avtomatik** Support'ga o'tadi. Frontend faqat natijani ko'rsatadi.

## 1. Stream'dagi yangi maydon: `handoff`

`GET /api/v1/chat/stream/{turn_id}` dagi har bir freymda endi `handoff` bor.
Oxirgi freymda (`"done": true`) qiymati quyidagilardan biri bo'ladi:

| `handoff` | Kim | Frontend nima qiladi |
|---|---|---|
| `""` | — | Hech narsa, oddiy javob |
| `"sent"` | Login qilgan mijoz | Javob ostida: "✅ Savolingiz mutaxassisga yuborildi. Javob **Yordam** bo'limida keladi." + "Yordam chatini ochish" tugmasi (`/support`) |
| `"ask_phone"` | Mehmon (login qilmagan) | Javob ostida forma: **Ism**, **Telefon**, Email (ixtiyoriy) + "Yuborish" tugmasi → 2-bo'lim |
| `"not_sent"` | Login qilgan mijoz | Bir soatda 3 tadan ko'p bo'ldi yoki xato: "Yordam bo'limiga yozing" tugmasi (`/support`) |

Mijoz uchun savol uning support chatiga **o'z nomidan** yoziladi (manba: `ai_chat`),
Support xodimlariga Telegram staff botda "· AI chatdan" belgisi bilan boradi.

Suhbat qayta ochilganda (`GET /api/v1/chat/threads/{id}`) `messages[].handoff`
xuddi shu qiymatni qaytaradi, shuning uchun yozuv sahifa yangilanganda ham qoladi.

## 2. Mehmon formasi: `POST /api/v1/chat/handoff`

Token kerak emas.

```json
{
  "turn_id": "<savol berilganda qaytgan turn_id>",
  "name": "Ali Valiyev",
  "phone": "+998 90 123 45 67",
  "email": ""
}
```

**201** — mehmon support chati ochildi, birinchi xabari savol va AI javobi:

```json
{ "token": "…", "chat": { "name": "…", "phone": "+998901234567", "messages": [ … ] } }
```

`token` ni saqlang. Keyin bu oddiy mehmon chati bo'ladi (kirish sahifasidagi "Yordam"
bilan bir xil): `GET /api/v1/support/guest` va `POST /api/v1/support/guest/messages`,
header `X-Guest-Token: <token>`.

**Xatolar:**
- `422` — `problems` ichida maydon bo'yicha xato (`name`, `phone`, `email`), formada
  maydon ostida ko'rsating.
- `404` — savol topilmadi yoki allaqachon yuborilgan (24 soatdan keyin ham shunday).
- `429` — bir manzildan juda ko'p chat ochildi.

## Postman

1. `POST /api/v1/chat/ask` — `{"question": "Kartamdan ikki marta pul yechildi"}`
2. `GET /api/v1/chat/stream/{turn_id}` — oxirgi freymda `"handoff": "sent"`
3. `GET /api/v1/support` — savol mijozning support chatida turibdi.

Mehmon uchun 1-qadamni tokensiz, `{"question": "...", "guest_id": "g1"}` bilan
yuboring, stream'da `"ask_phone"` keladi, keyin `POST /api/v1/chat/handoff`.
