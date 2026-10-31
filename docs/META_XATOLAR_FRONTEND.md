# Meta xatolari: frontendga ulash yo'riqnomasi

Meta biror amalni rad etganda user endi "keyinroq urinib ko'ring" o'rniga aniq
sabab va tartiblangan qadamlarni ko'rishi kerak. Backend tayyor, frontendda bitta
dialog va ofisda bitta sahifa qo'shiladi.

Tavsiya etilgan tartib: 1, 2, 3 — dialog; 4 — har bir manba; 5 — ofis; 6 — tekshiruv.

---

## 1. API tiplarini yangilang

Backend deploy bo'lgach, OpenAPI tiplarini qayta generatsiya qiling. Yangi narsalar:

```ts
interface Refusal {
  key: string | null;            // /refusals/answer ga so'rov uchun
  retryable: boolean;            // true: vaqtincha, kutib qayta bosiladi
  title: string;                 // dialog sarlavhasi
  cause: string;                 // sabab
  steps: string[];               // tartiblangan qadamlar
  providerWords: string | null;  // Meta'ning o'z so'zlari
  html: string | null;           // tayyor javob; bo'lsa cause va steps o'rniga chiqadi
  explaining: boolean;           // javob yozilmoqda
  fix: RefusalFix | null;        // asosiy tugma
  retryAfterSeconds: number | null;
}

interface RefusalFix {
  label: string;
  url: string | null;  // to'liq manzil yoki /app/... ichki yo'l
  to: string | null;   // reklama ustasi ichidagi joy: geo, media, plan, ads, form...
}

interface RefusalAnswer {
  key: string;
  html: string | null;
  explaining: boolean;
}
```

## 2. `ApiError`ga `refusal` qo'shing

Yangi xato kodi `provider_refused`, status `422`:

```json
{
  "detail": "Meta aniq sababini aytmadi.",
  "code": "provider_refused",
  "refusal": {
    "key": "audience:meta:100/2654",
    "retryable": false,
    "title": "Meta auditoriyani qabul qilmadi",
    "cause": "Auditoriya yaratilmadi — Shartlarni qabul qiling.",
    "steps": ["«Ulanishlar» sahifasida Meta ulanishi «Faol» ekanini tekshiring."],
    "providerWords": "Auditoriya yaratilmadi — Shartlarni qabul qiling.",
    "html": null,
    "explaining": true,
    "fix": null,
    "retryAfterSeconds": null
  }
}
```

`client.ts`dagi `ApiError` body'dan `refusal`ni olib, tashqariga bersin. Transport
qatlami javobni o'zgartirsa, bu maydon yo'qolmasligini tekshiring.

## 3. Bitta `<RefusalDialog>` yarating

Ilova ildiziga bitta dialog qo'ying va uni ochadigan `openRefusal(refusal, { onRetry })`
funksiyasini bering. `MutationCache.onError`da shunday qiling:

```ts
if (error instanceof ApiError && error.refusal) {
  openRefusal(error.refusal);
  return; // toast chiqmasin
}
```

Dialog tartibi:

1. `title`
2. `html` bo'lsa, shuni chiqaring. Bu `<p>`, `<ol>`, `<li>`, `<a>` teglaridan iborat.
3. `html` yo'q bo'lsa: `cause`, keyin `steps` raqamlangan ro'yxat bo'lib. `explaining`
   bo'lsa, tepasida "Yechim tayyorlanmoqda..." ko'rsating.
4. `providerWords` bo'lsa, "Meta javobi" deb yig'iladigan blokda.
5. Tugmalar: `fix`, "Qayta urinish" (faqat `onRetry` berilgan bo'lsa), "Supportga yozish".

`retryAfterSeconds` bo'lsa, "Qayta urinish"ni shu vaqtgacha o'chirib turing.

**Tugma qoidasi:**

| `fix` | Harakat |
|---|---|
| `url` `http` bilan boshlanadi | Yangi oynada ochiladi |
| `url` `/` bilan boshlanadi | Ichki router orqali ochiladi |
| `url` yo'q, `to` bor | Mavjud `useTarget`dagi kabi reklama ustasi bo'limi ochiladi |

`/app/connections/` kabi ichki yo'l cabinet router'ida borligini tekshiring.

**`html` xavfsiz:** backend matnni avval escape qiladi, `<script>` o'tmaydi.
`dangerouslySetInnerHTML` ishlatsa bo'ladi. Havolalar yangi oynada ochiladi.

**Javobni kutish.** `refusal.explaining && refusal.key` bo'lsa:

```
GET /api/v1/refusals/answer?key=<refusal.key>
```

- 3 soniyada bir marta, 20 martagacha so'rang.
- `html` kelsa, dialogda almashtiring va to'xtang.
- `explaining: false` kelsa yoki 20 ta tugasa, to'xtang. `cause` va `steps` qoladi.
- Dialog yopilsa, to'xtating.

Bu endpoint barcha manbalar uchun bir xil.

## 4. Manbalarni ulang

| Manba | Qayerdan | Nima qilinadi |
|---|---|---|
| Auditoriya: `POST /connections/audiences`, `/rule`, `/lookalike`, `POST /audiences/{pk}/fill`, `DELETE /audiences/{pk}` | `422 provider_refused` | Avtomatik, 3-band |
| Joy qidirish: `GET /launch/drafts/{id}/locations` | `422 provider_refused` | Avtomatik. Vaqtincha xato eskicha `503 place_search_failed` |
| Reklama yaratish: `GET /launch/drafts/{id}` | `failure.refusal` | Pastda |
| Ishlayotgan reklama: `GET /campaigns/manage/{level}/{id}/state` | `failure.refusal` | Pastda |
| O'zgarish holati: `GET /campaigns/actions/{id}` | `refusal` | Pastda |
| Media: `.../media` tile'lari | `tile.refusal` | Pastda |
| Meta ulash | Redirect: `?error=<matn>&refusal_key=<kalit>` | Pastda |

**Reklama yaratish (`Review.tsx`, `Failed`).** Sahifa qoladi. Unga
`failure.refusal.key || failure.code` bo'yicha bir marta avtomatik dialog oching,
`onRetry` = mavjud retry. "AI dan so'rash" tugmasini "Yechimni ko'rish" bilan
almashtiring: u dialogni qayta ochadi.

**Ishlayotgan reklama (`ControlLine.tsx`).** Qatordagi xato matni qoladi, yoniga
`failure.refusal` bo'lsa "Batafsil" tugmasi qo'shiladi. `failure.fix` o'z joyida qoladi.

**Media tile (`MediaTile.tsx`).** `state` `upload_failed` yoki `delete_failed` bo'lib,
`tile.refusal` bor bo'lsa, tile bosilganda dialog ochiladi. `refusal` bo'lmasa, eskicha.
Tile'dagi `refusal.html` doim bo'sh: javob `/refusals/answer`dan olinadi.

**Meta ulash.** `/app/connections` sahifasi `?refusal_key=` bo'lsa, shu obyektni
tuzib dialog ochadi, keyin parametrni URL'dan olib tashlaydi:

```ts
openRefusal({
  key: params.refusal_key, title: t`Meta ulanishni rad etdi`, cause: params.error,
  explaining: true, retryable: false, steps: [], html: null,
  providerWords: null, fix: null, retryAfterSeconds: null,
});
```

## 5. Ofis sahifasi

Yangi sahifa "Meta xatolari". To'liq ma'lumot: [OFIS_API.md](OFIS_API.md), 7b-bo'lim.

- Ro'yxat: `GET /office/refusals?tab=&q=&offset=`. Tablar javobdagi `tabs[]`dan,
  menyu nishoni `held`dan. Qatorda: `operation_label`, `key`, `provider_title`,
  `hits`, `written_by`, holat belgisi.
- Tahrirlash: uz, ru, en uchun uchta matn maydoni. Yonida `provider_title`,
  `provider_message` va `links[]` ro'yxati (`[[tolov]]` kabi nomlar).
- Saqlash: `PATCH /office/refusals/{id}`, faqat o'zgargan tillar.

## 6. O'zgargan narsalar

Eski frontend yangi backend bilan ishlaydi, lekin mana bularni hisobga oling:

| Nima | Oldin | Hozir |
|---|---|---|
| `Failure.code` | 7 ta qiymat | 30 ta qiymat. `Record<LaunchErrorCode, ...>` bo'lsa to'ldiring |
| `Failure.raw` | Ichki kod (`refused`) | Meta'ning so'zlari yoki `null` |
| Auditoriya xatosi | `502`, faqat `detail` | `422`, `provider_refused` va `refusal` |
| Meta'ni ulash xatosi | `?error=` | `?error=` va ba'zan `?refusal_key=` |

Eski maydonlar `explanationHtml`, `explaining`, `guide`, `fix` qoladi. Hamma joy
`refusal`ga o'tgach, keyin olib tashlaymiz.

## 7. Tekshirish ro'yxati

- [ ] To'lov usuli yo'q xatoda to'lov tugmasi chiqadi, "kuting" chiqmaydi
- [ ] Yangi xatoda "tayyorlanmoqda" ko'rinadi, keyin qadamlar o'zi chiqadi
- [ ] Xuddi shu xato qaytsa, javob darhol chiqadi
- [ ] Vaqtincha xatoda `retryable` matni chiqadi
- [ ] Polling dialog yopilganda to'xtaydi
- [ ] `fix` uch holatda ham to'g'ri ishlaydi
- [ ] Ofisda matnni tuzatgach, user yangi matnni ko'radi
- [ ] Dialog telefon kengligida sig'adi
- [ ] Bir xato uchun dialog ikki marta ochilmaydi
