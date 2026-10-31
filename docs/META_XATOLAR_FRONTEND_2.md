# Meta xatolari, 2-qism: frontendga ulash

`docs/META_XATOLAR_FRONTEND.md` dagi dialog allaqachon ulangan. Bu hujjat faqat
yangi o'zgarishlarni aytadi. `Refusal` shakli, `RefusalDialog` va
`GET /refusals/answer` o'zgarmagan.

Muammo: worker'da bajariladigan amal (update, budget, o'chirish) rad etilsa, user
sababni ko'rmaydi yoki "Bajarilmadi. Qayta urinib ko'ring." degan matnni ko'radi.
Meta reklamani rad etganda esa dialog umuman ochilmaydi.

Barcha API o'zgarishlari qo'shimcha: eski front ishlashda davom etadi. Avval
backend, keyin front chiqadi. OpenAPI'dan `gen/openapi.ts`ni qayta yarating.

---

## 1. API o'zgarishlari

### Yangi maydonlar

| Endpoint | Obyekt | Yangi maydonlar |
|---|---|---|
| `GET /campaigns` | `ListedCampaign` | `refusal`, `rejection` |
| `GET /campaigns/{id}` | `CampaignDetail` | `refusal`, `rejection` |
| `GET /campaigns/{id}/tree` | `AdGroup` | `refusal`, `rejection` |
| `GET /campaigns/{id}/tree` | `CampaignAd` | `lastAction`, `refusal`, `rejection` |
| `GET /campaigns/manager` | `ManagerRow` | `refusal`, `rejection` |
| `GET /campaigns/manage/{level}/{externalId}/state` | `ControlState` | `gone` |

```ts
// Oxirgi amal Meta tomonidan rad etilgan bo'lsa to'ladi, keyingi muvaffaqiyatli amalda tozalanadi.
refusal: Refusal | null;

// Meta reklamani ishga tushirmaydi. Kampaniya va guruhda: ichidagi birinchi shunday reklama.
rejection: Refusal | null;

// true: obyekt o'chib bo'lgan, /state so'rashni to'xtating.
gone?: boolean | null;
```

Ikkala maydon ham `html: null` bilan keladi. `key` bo'lsa, `explaining: true`
bo'ladi va dialog javobni `/refusals/answer` dan odatdagidek oladi.

`CampaignDetail.problem` endi kampaniyaning o'z xatosi bo'lmasa ham, rad etilgan
reklamadan to'ladi. `problem.fix` doim bo'sh: uni ko'rsatmang.

### O'zgargan javoblar

| Endpoint | Eski | Yangi |
|---|---|---|
| `POST /campaigns/ads/{externalId}/edit` | `204` | `200 ControlState` |
| `DELETE /campaigns/{id}` | `204` | `200 ControlState` |
| `DELETE /campaigns/adsets/{externalId}` | `204` | `200 ControlState` |
| `DELETE /campaigns/ads/{externalId}` | `204` | `200 ControlState` |
| `POST /agent/proposals/{id}/new-ad` | Oldingi javob | Oldingi javob va `control: ControlState` |

`POST .../new-ad` javobi OpenAPI'da sxemasiz qoladi, `control` tipini qo'lda yozing.

`GET .../state` o'chirish amali bajarilgan obyekt uchun endi `404` emas, shunday javob
beradi (hech qachon bo'lmagan id uchun esa `404` qoladi):

```json
{ "level": "ad", "externalId": "123", "pending": false, "stalled": false,
  "failure": null, "action": null, "tries": 3, "pollSeconds": 2, "gone": true }
```

Launch ko'rib chiqishida `postRoute` yangi `"carousel"` qiymatini oladi.
`postRouteNote` tayyor matn bilan keladi, uni o'zgarishsiz ko'rsating.

---

## 2. Frontendda qilinadigan ishlar

### 2.1. Bitta global kuzatuvchi

Hozir xato faqat tugma bosilgan sahifadagi `ControlLine` chizilgan bo'lsa
kuzatiladi. Kuzatuvchini `RefusalLayer` darajasiga ko'taring, u sahifa
almashganda ham ishlashi kerak.

1. `ControlState` kelsa va `pending: true` bo'lsa, obyektni kuzatuvga qo'shing.
2. `pollSeconds` oralig'ida `/state`ni so'rang, `tries`ni uzating.
3. `failure.refusal` chiqsa: `openRefusalOnce(action.id, failure.refusal)`.
4. `pending: false`, `stalled: true` yoki `gone: true` bo'lsa, kuzatuvni to'xtating.
5. Tugaganda `campaignsKey`ni yangilang.

Shu bitta ish budget, kampaniya edit, reklama update va o'chirish muammosini yopadi.

### 2.2. Hook'lar

Quyidagilar javobdagi `ControlState`ni kuzatuvchiga bersin:

- `useSaveAdEdit`, `useDeleteAd`, `useDeleteGroup`, `useDeleteCampaign`
- `useSaveNewAd`: `control` maydonidan
- `useManage`, `useSetBudget`, `useSaveCampaign`, `useRevertControl`,
  `usePauseCampaign`, `useResumeCampaign`: `useControlMutation` orqali

`AdEdit` va `NewAd`dagi "Yangi reklama yuborildi" toast'i qoladi.

### 2.3. Umumiy matnni olib tashlang

`Row.tsx:133` va `Tree.tsx:211`dagi "Bajarilmadi. Qayta urinib ko'ring." o'rniga:

```tsx
{r.refusal && !ctl && (
  <span className="errmsg" role="alert">
    {r.refusal.cause}
    <button className="btn link sm" onClick={() => openRefusal(r.refusal!)}>{t`Batafsil`}</button>
  </span>
)}
```

Shuni guruh qatori, reklama qatori (`Tree.tsx:165` atrofida) va Manager'ga ham qo'shing.

### 2.4. Rad etilgan reklama

- `Sections.tsx`dagi `Problem` blokidan bo'sh "AI tuzatish taklifi" kartasini olib tashlang.
- "Matn va rasmni almashtirish" tugmasi o'rniga `c.rejection` bo'lsa `openRefusal(c.rejection)`
  ochadigan tugma qo'ying.
- "Rad etildi" belgisi yonida, `Row` va Manager'dagi `problem` matnida `rejection`ni oching.
- `rejection.fix` bo'lmasa, reklama post'dan qurilgan: uni almashtirib bo'lmaydi, buni
  qadamlar aytadi. "Almashtirish" havolasini ko'rsatmang.

### 2.5. Dialog qachon o'zi ochiladi

| Holat | Xulq |
|---|---|
| User shu sessiyada amal bosdi va xato chiqdi | Dialog o'zi ochiladi |
| Sahifaga qayta kirdi, `refusal` yoki `rejection` bor | Faqat matn va "Batafsil" |
| Launch sahifasi | O'zgarmaydi |

---

## 3. Tekshirish

- [ ] Reklama update: Meta rad etsa, boshqa sahifada ham dialog ochiladi
- [ ] Kampaniya sahifasida budget va edit xatosi dialogda chiqadi
- [ ] O'chirish rad etilsa, qator tiklanadi va dialog ochiladi
- [ ] O'chirish muvaffaqiyatli tugasa (`gone: true`), xato chiqmaydi
- [ ] Sahifa yangilangach, qatorda aniq sabab va "Batafsil" turadi
- [ ] Rad etilgan reklamada dialog sabab, qadamlar va Meta so'zlarini ko'rsatadi
- [ ] Post reklamasida "almashtirish" havolasi chiqmaydi
- [ ] Bir xato uchun dialog ikki marta ochilmaydi
- [ ] `grep "Bajarilmadi. Qayta urinib"` faqat tarmoq xatolarida qoladi
