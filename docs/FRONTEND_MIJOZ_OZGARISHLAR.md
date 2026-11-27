# Mijoz kabineti: ishlab turgan API lardagi o'zgarishlar

Backend: `feat/business-knowledge` branchi. Bu hujjat faqat **mavjud, ishlab turgan**
API larda nima o'zgarganini aytadi. Yangi API lar alohida hujjatlarda:

- Reklama yaratish chati — `docs/FRONTEND_REKLAMA_CHATI.md`
- Biznes bilimi (yangi `/api/v3/businesses/{id}/knowledge…`) — `docs/FRONTEND_BIZNES_BILIMI.md`

## 1. Qisqacha

| # | Qayerda | Nima o'zgardi | Eski front buziladimi |
|---|---|---|---|
| 1 | `GET /api/v1/start` (tayyorgarlik) | «Biznes ma'lumotlari» (`profile`) qadami yo'q, qadamlar soni 4 → 3 | Buzilmaydi, lekin o'lik qadam va forma qoladi — olib tashlang |
| 2 | `/api/v2/assistant` (AI chat) javobidagi `buttons` | Ikki yangi tugma turi: `knowledge`, `business_kind` | Buzilmaydi: oddiy tugma bo'lib chiziladi, lekin `lines` va «Kerak emas» ko'rinmaydi |

Boshqa hech bir mavjud yo'lning so'rovi yoki javobi o'zgarmagan (3-bo'lim).

## 2. O'zgarishlar

### 2.1 Tayyorgarlik: «Biznes ma'lumotlari» qadami olib tashlandi

Foydalanuvchidan to'lovdan keyin biznes ma'lumoti so'ralmaydi. Sahifa va reklama
akkaunti ulanganda biznes profili backendda o'zi yoziladi (nomi va shahri sahifadan),
bir-ikki daqiqadan keyin AI biznes turini taxmin qiladi.

`GET /api/v1/start` javobida:

| Maydon | Oldin | Hozir |
|---|---|---|
| `setup.steps`, `setup.state` | `connect`, `profile`, `page`, `ad_account`, `leads` (+ `telegram`, `pixel`) | `profile` yo'q |
| `setup.total` | 4 | 3 |
| `setup.blocked_on`, `next_action` | `"profile"` bo'lishi mumkin edi | hech qachon `"profile"` emas |
| `setup.facts.has_profile`, `has_category` | bor | bor, lekin hech narsani to'smaydi |

**Frontda:**

1. Tayyorgarlik sahifasidan «Biznes ma'lumotlari» qadami va formasini olib tashlang.
2. `blocked_on === "profile"` / `next_action === "profile"` ga bog'langan yo'naltirish
   va shartlarni o'chiring.
3. Qadamlar sonini qattiq yozmang — `setup.total` dan oling.

### 2.2 AI chat: ikki yangi tugma turi

`/api/v2/assistant` yo'llari o'zgarmagan. Faqat javob ostidagi `buttons` ro'yxatida
ikki yangi `kind` kelishi mumkin. Ikkalasi ham bir xil chiziladi va bir xil ishlaydi.

**`knowledge`** — foydalanuvchi biznesi haqida aytgan narsani eslab qolish taklifi:

```json
{"kind": "knowledge", "key": "K1", "label": "Eslab qolish", "state": "open",
 "state_text": "", "target": "Texno",
 "lines": ["Yangi taklif: Dazmol — 390 000 so'm", "Kafolat: 1 yil kafolat"],
 "business_id": "…", "proposal_id": "…"}
```

**`business_kind`** — biznes turini tasdiqlash (tur taxmin yoki noma'lum bo'lsa):

```json
{"kind": "business_kind", "key": "B1", "label": "Tasdiqlash", "state": "open",
 "state_text": "", "target": "Zukko Academy",
 "lines": ["Biznes turi: Ta'lim → ingliz tili kurslari", "Nomi: Zukko"],
 "business_id": "…", "direction_id": "…", "subtype": "ingliz tili kurslari",
 "name": "Zukko"}
```

**Chizish:** `target` — sarlavha (biznes nomi), `lines` — nima saqlanishi ro'yxati,
ostida ikkita tugma: `label` va «Kerak emas». Mavjud `change` tugmasining kartasi mos
keladi. Bitta javobda ikkalasi birga kelishi mumkin.

**Bosish va rad etish — mavjud yo'llar:**

| Amal | Yo'l | Natija |
|---|---|---|
| Tasdiqlash | `POST /api/v2/assistant/buttons/{message_id}/{key}` | `state: "done"`, `text` — tayyor matn («Saqlandi. …») |
| Kerak emas | `POST /api/v2/assistant/buttons/{message_id}/{key}/dismiss` | `state: "dismissed"` |

Boshqa holatlar: `gone` (taklifga boshqa joyda javob berilgan), `refused` (`text` da
sababi). `working` holati yo'q — natija darhol keladi, so'rab turish kerak emas.
Suhbat qayta ochilganda tugma `state` va `state_text` bilan keladi — shundan chizing.

## 3. O'zgarmagan narsalar

- Profil API lari (`GET/PUT /api/v1/business…`): «Biznes» sahifasidagi forma avvalgidek.
- Eski «Reklama berish» ning hamma yo'llari (`/api/v1/launch/…`): reja, media, lid
  formasi, ko'rib chiqish, yaratish.
- Reklama boshqaruvi, Lidlar, CRM, to'lovlar, Support — tegilmagan.
- AI chatning savol berish, oqim (stream), tarix va boshqa tugmalari — tegilmagan.

## 4. Tekshiruv ro'yxati

- [ ] Yangi ro'yxatdan o'tgan foydalanuvchi tayyorgarlikda 3 qadam ko'radi, biznes
      formasi chiqmaydi.
- [ ] Sahifa va akkaunt ulangach «Biznes» sahifasida profil bor (nomi sahifa nomidan).
- [ ] AI chatda «Bizda … bor, narxi …» deb yozilsa, javob ostida «Eslab qolish»
      kartasi `lines` bilan chiqadi; bosilsa «Saqlandi…», «Kerak emas» bosilsa yopiladi.
- [ ] Turi noma'lum biznesda «Biz … bilan shug'ullanamiz» deb yozilsa, «Tasdiqlash»
      kartasi chiqadi.
- [ ] Sahifa yangilanganda bosilgan tugmalar bosilgan holatda ko'rinadi.
