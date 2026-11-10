# Reklama akkauntiga ruxsat yo'q: frontendda ko'rsatish

Backend o'zgardi (2026-11-10, branch `fix/account-access`, migratsiya 0039).
Bu hujjat frontend uchun: nima keladi va qayerda nimani o'zgartirish kerak.

## Muammo nima edi

Mijoz Meta'ni **boshqa Facebook profil** bilan qayta ulasa, eski profil orqali
kelgan reklama akkaunti kabinetda "faol, tanlangan" bo'lib qolardi. Yangi
profilda esa bu akkauntga ruxsat yo'q edi. Natijada reklama yaratilganda Meta
rad etardi va mijoz inglizcha matnni ko'rardi:

> Unsupported post request. Object with ID 'act_…' does not exist, cannot be
> loaded due to missing permissions… | code 100/33

Haqiqiy holat: 2026-11-09, "Baraka" kabineti. Bir xil sabab Business
Manager'da profildan akkaunt roli olib qo'yilganda ham chiqadi.

## Backend endi nima qiladi

1. **Qayta ulanganda** (va akkauntlar har safar sinxronlanganda) tanlangan
   akkauntlar tekshiriladi. Profil kira olmaydigan akkaunt **"ruxsat yo'q"**
   deb belgilanadi. Profil akkauntni yana o'qiy olsa (qayta ulash, «Yangilash»
   yoki keyingi sinxronlash), belgi o'zi olib tashlanadi.
2. **Reklama yaratishdan oldin** akkaunt tekshiriladi. Ruxsat bo'lmasa, Meta'ga
   hech narsa yuborilmaydi va ishga tushirish yangi kod bilan yiqiladi:
   **`account_access`**. Uning o'zbekcha matni backend'dan keladi.
3. Kampaniyani yoqish/o'chirish paytida xuddi shu sabab chiqsa, xato so'zi
   `account_access` bo'ladi.

## 1. Yangi maydonlar: reklama akkaunti (`AdAccountOut`)

`AdAccountOut` ishlatiladigan hamma joyda ikkita yangi maydon bor:

| Maydon | Tur | Ma'nosi |
|---|---|---|
| `is_reachable` | `boolean` | `false` bo'lsa, ulangan Facebook profil bu akkauntga kira olmaydi |
| `reach_lost_at` | `string \| null` (ISO vaqt) | Ruxsat qachon yo'qolgani aniqlangan. `is_reachable: true` bo'lsa, `null` |

Endpointlar:
- `GET /api/v1/connections`
- `GET /api/v1/connections/cabinet`
- `GET /api/v1/connections/pages`: `payer`, `options[].account`, `paired[]`,
  juftlik `account` ichida
- `GET /api/v1/connections/google`: maydon bor, lekin Google akkauntlari uchun
  hozircha har doim `true`

**Akkaunt tanlash oynasi.** `PayerOptionOut.unusable` endi ruxsati yo'q akkaunt
uchun ham `true` keladi. Shuning uchun bunday akkaunt ro'yxat oxiriga tushadi va
avvalgi "ishlatib bo'lmaydi" mantig'i bilan o'chirilgan ko'rinadi.

Javob namunasi:
```json
{
  "external_id": "act_1001166539663370",
  "name": "baraka",
  "is_active": true,
  "is_current": true,
  "may_advertise": true,
  "is_reachable": false,
  "reach_lost_at": "2026-11-09T16:44:28Z"
}
```

`may_advertise: true` va `is_reachable: false` birga kelishi mumkin. Akkauntning
o'zi Meta'da faol, faqat hozirgi profil unga kira olmaydi. **`is_reachable`
birinchi tekshiriladi.**

## 2. Yangi xato kodi: ishga tushirish (`account_access`)

Ishga tushirish yiqilganda `failure.code` endi `"account_access"` bo'lishi
mumkin. Ekran matnlari (`title`, `hint`, `explain`, `guide.cause`,
`guide.steps`, `fix`) **backend'dan tayyor keladi**. Frontend ularni boshqa
kodlar kabi chizadi, yangi matn yozish shart emas.

Backend yuboradigan matn:
- **title:** Ulangan Facebook profili bu reklama akkauntiga kira olmaydi
- **hint:** Akkauntga ruxsati bor profil bilan qayta ulang
- **fix:** `{ "label": "Ulanishlarni ochish", "to": "connections" }`

`needs_fix_first` bu kod uchun `true`. "Qayta urinish"dan oldin mijoz Meta
tomonida biror narsani tuzatishi kerak (boshqa `account_*` kodlari kabi).

Yoqish/o'chirish dialoglarida (`Refusal`) ham xuddi shu: so'z `account_access`,
sabab va qadamlar backend'dan keladi, tugma esa `reconnect`.

## Frontendda nima o'zgartirish kerak

### A. Turlar
1. `packages/api/src/gen/openapi.ts`ni qayta generatsiya qiling: `AdAccountOut`ga
   `is_reachable` va `reach_lost_at` qo'shiladi. Frontend nusxasi backenddan
   ortda qolgan bo'lsa, shu ikki maydonni qo'lda qo'shing.
2. `packages/api/src/launch.ts`dagi `LaunchErrorCode`ga `"account_access"`
   qo'shing.
3. `packages/api/src/connections.ts`dagi `PayAccount.state`ga `"unreachable"`
   qo'shing:
   ```ts
   state: "ok" | "limit" | "debt" | "inactive" | "unreachable";
   ```

### B. Bridge
`packages/api/src/live/bridges/connections.ts`dagi `toPayAccount`da
`unreachable` **birinchi** tekshirilsin:
```ts
const state: PayAccount["state"] =
  a.is_reachable === false ? "unreachable"
  : a.payment_due ? "debt"
  : a.cap_reached ? "limit"
  : (ACCOUNT_STATE[a.account_status.toLowerCase()] ?? "ok");
```

`packages/api/src/live/bridges/onboarding.ts`dagi `disabledOf` ham
`unreachable` akkauntni o'chirilgan deb hisoblasin:
```ts
const disabledOf = (a: Account) =>
  a.may_advertise === false || ["inactive", "unreachable"].includes(toPayAccount(a).state);
```

### C. Ulanishlar sahifasi
`apps/cabinet/src/pages/settings/Pairs.tsx` → `AccountWarn`ga yangi qator
(qizil, `alert` belgisi, `debt`dan oldin):

> Hozir ulangan Facebook profilingiz bu reklama akkauntiga kira olmaydi —
> reklama yaratilmaydi. Akkauntga ruxsati bor profil bilan Meta'ni qayta ulang
> yoki Business Manager'da shu profilga rol bering.

Yoniga **«Qayta ulash»** tugmasini qo'ying: u mavjud Meta qayta ulash oqimini
ochadi (`POST /api/v1/connections/meta/start`).

Akkaunt tanlash ro'yxatlarida (`AddPages.tsx`, juftlik akkauntini almashtirish)
`unreachable` akkaunt o'chirilgan ko'rinsin va yonida "Ruxsat yo'q" degan kichik
belgi tursin.

### D. Reklama yaratish ekrani
Agar kabinetning joriy akkaunti `is_reachable: false` bo'lsa, ishga tushirish
tugmasi ustida C bo'limdagi ogohlantirishni oldindan ko'rsatish mumkin.
Majburiy emas: backend baribir ishga tushirishni boshlamaydi va
`account_access` qaytaradi.

### E. Mock va testlar
- `packages/api/src/mock/handlers/launch.ts`: `FAILURES`ga `account_access`
  namunasi (matn yuqorida).
- Hisob fixture'lariga (`live-connections.test.ts`, `live-onboarding.test.ts`
  va boshqalar) `is_reachable: true, reach_lost_at: null` qo'shing va
  `is_reachable: false` → `state: "unreachable"` testini yozing.

## Tekshirish (staging)
1. Meta'ni A profil bilan ulang va akkaunt tanlang.
2. Shu akkauntga roli yo'q B profil bilan qayta ulang.
3. Bir necha daqiqadan keyin `/connections` javobida o'sha akkauntning
   `is_reachable: false` bo'lishi kerak. Sahifada ogohlantirish chiqadi.
4. Shu akkauntda reklama ishga tushiring. Ekranda "Ulangan Facebook profili bu
   reklama akkauntiga kira olmaydi" chiqadi va Meta'da hech narsa yaratilmaydi.
5. A profil bilan qayta ulang: belgi o'chadi, `is_reachable: true` bo'ladi.
