# Ofis → Mijoz → Reklamalar: holatni to'g'ri ko'rsatish

Backend o'zgardi (2026-11-10). Bu hujjat ofis frontendidagi
`apps/office/src/pages/clients/ClientAds.tsx` va
`packages/api/src/live/bridges/officeClients.ts` uchun.

## Muammo nima edi

Ofis ro'yxati kampaniya holatini bazadagi Meta nusxasidan (mirror) o'qiydi.
Nusxa faqat sinxronlash ishlagan paytdagicha to'g'ri. Uch holatda u yolg'on
gapirardi:

1. **Nusxa eskirgan.** Sinxron faqat to'lovi bor egalar va yoqilgan reklama
   hisoblari uchun yuradi. Tarif tugasa, hisob o'chirilsa yoki ulanish uzilsa,
   nusxa to'xtaydi va "Ishlayapti" abadiy qoladi. Mijoz Ads Manager'da
   o'chirgan bo'lsa ham, ofis "Ishlayapti" deydi.
2. **Reklamalari qolmagan kampaniya.** Mijoz Ads Manager'da guruh yoki
   reklamalarni o'chirsa, kampaniya o'zi ACTIVE qoladi va "Ishlayapti"
   ko'rinardi.
3. **Noma'lum / to'lov kutilmoqda.** Bunday holatlar ham "ishlayapti" deb
   sanalardi (`is_running: true`), front esa ularni yashil ko'rsatardi.

O'chirilgan kampaniya ro'yxatda "Noma'lum" bo'lib turardi.

## Backend endi nima qiladi

`GET /api/v1/office/customers/{customer_id}/ads` (bridge: `/office/clients/:id/ads`)

- **O'chirilgan kampaniya ro'yxatda yo'q.** Uning soni `deleted` da, shu
  davrda sarflagan puli `deleted_totals` da. `totals` va `summary` faqat
  ko'rsatilgan qatorlarni qo'shadi.
- **`is_running`** faqat quyidagi hammasi to'g'ri bo'lsa `true`: kampaniya
  yoqilgan, kamida bitta reklamasi yoqilgan va nusxa 3 soatdan yangi.
  `running` ham shu qoida bilan sanaydi. Mijozlar ro'yxati va dashboard'dagi
  "ishlayotgan" son ham shu qoidaga o'tdi.
- **Eskirgan nusxa qayta o'qiladi.** Sahifa ochilganda nusxasi eskirgan hisob
  uchun Meta'dan o'qish navbatga qo'yiladi (15 daqiqada ko'pi bilan bir
  marta) va javobda `refreshing: true` keladi.

### Yangi maydonlar

Har bir qatorda (`AdRowOut`):

| Maydon | Turi | Ma'nosi |
|---|---|---|
| `delivery` | string | Holat kaliti, quyidagi jadvalga qarang. Regex o'rniga shuni ishlating |
| `is_stale` | bool | Nusxa 3 soatdan eski |
| `synced_at` | datetime \| null | Meta oxirgi marta qachon o'qilgan |

Javobning o'zida (`CustomerAdsOut`):

| Maydon | Turi | Ma'nosi |
|---|---|---|
| `deleted` | int | Meta'da o'chirilgan, ro'yxatga kirmagan kampaniyalar soni |
| `deleted_totals` | `AmountOut[]` | Ular shu davrda sarflagan pul, valyuta bo'yicha |
| `stale` | int | Ro'yxatdagi eskirgan qatorlar soni |
| `refreshing` | bool | Hozir Meta'dan qayta o'qish navbatga qo'yildi |

### `delivery` qiymatlari

| `delivery` | `delivery_label` | `is_running` | Badge |
|---|---|---|---|
| `active` | Ishlayapti | true | `active` (yashil) |
| `paused` | To'xtatilgan | false | `paused` |
| `pending` | Tekshiruvda | false | `pending` |
| `billing` | To'lov kutilmoqda | false | **yangi**: `billing` (warn) |
| `rejected` | Muammo bor | false | `rejected` |
| `finished` | Tugagan | false | `finished` |
| `unknown` | Noma'lum | false | **yangi**: `unknown` (neutral) |
| `stale` | Holati eskirgan | false | **yangi**: `stale` (warn) |
| `no_ads` | Reklamasi qolmagan | false | **yangi**: `no_ads` (neutral) |
| `not_read` | Hali o'qilmagan | false | **yangi**: `not_read` (neutral) |

`deleted` qatorda kelmaydi.

## Frontendda nima qilish kerak

### 1. API turlarini yangilash

`docs/api/openapi.json` va `packages/api/src/gen/openapi.ts` ni backenddan
qayta yarating. Hozirgi nusxa backenddan ancha orqada, shuning uchun qo'lda
qo'shsangiz ham bo'ladi: `AdRowOut` ga `delivery`, `is_stale`, `synced_at`;
`CustomerAdsOut` ga `deleted`, `deleted_totals`, `stale`, `refreshing`.

### 2. `statusOf` — regex o'rniga `delivery`

`packages/api/src/live/bridges/officeClients.ts`:

```ts
const statusOf = (a: AdRow): DeliveryStatus => {
  if (a.is_running) return /learn|o.?rgan/i.test(a.delivery_label) ? "learning" : "active";
  switch (a.delivery) {
    case "paused": case "pending": case "rejected": case "finished":
    case "billing": case "unknown": case "stale": case "no_ads": case "not_read":
      return a.delivery;
    default:
      return STATUS.find(([, re]) => re.test(a.delivery_label))?.[0] ?? "unknown";
  }
};
```

Default `"paused"` emas, `"unknown"` bo'lsin: bilmagan holatni
"To'xtatilgan" deyish ham yolg'on.

### 3. `DeliveryStatus` va `StatusBadge`

`packages/ui/src/components/basic.tsx` va `packages/api/src/types.ts`:

```ts
export type DeliveryStatus =
  | "active" | "learning" | "pending" | "rejected" | "paused" | "finished" | "paused_above"
  | "billing" | "unknown" | "stale" | "no_ads" | "not_read";
```

`StatusBadge` map'iga:

```ts
billing:  ["warn", true,  t`To'lov kutilmoqda`],
unknown:  ["neutral", false, t`Noma'lum`],
stale:    ["warn", false, t`Holati eskirgan`],
no_ads:   ["neutral", true, t`Reklamasi qolmagan`],
not_read: ["neutral", false, t`Hali o'qilmagan`],
```

`StatusBadge` mijoz kabinetida ham ishlatiladi. Yangi kalitlarni qo'shish
u yerni buzmaydi, chunki u yerda ular kelmaydi.

### 4. `ClientAd` / `ClientAds` ga maydon qo'shish

`packages/api/src/officeClients.ts`:

```ts
export interface ClientAd { /* ... */ stale: boolean; syncedAt: string | null; }
export interface ClientAds { /* ... */ deleted: number; deletedSpend: Money[]; stale: number; refreshing: boolean; }
```

`toAd`: `stale: a.is_stale, syncedAt: a.synced_at ?? null`.
`toAds`: `deleted: d.deleted ?? 0, deletedSpend: (d.deleted_totals ?? []).map(money), stale: d.stale ?? 0, refreshing: d.refreshing ?? false`.

### 5. Sahifada ko'rsatish (`ClientAds.tsx`)

- **Pastki izoh (`of-cap`)** — `hidden` yonida:
  `d.deleted > 0` → ``t`Meta'da o'chirilgan ${d.deleted} ta reklama ko'rsatilmadi (${spend} sarflagan).` ``
  `spend` = `deletedSpend` (bir nechta valyuta bo'lsa vergul bilan). Pul 0 bo'lsa qavsni chiqarmang.
- **Eskirgan nusxa banneri** — `d.stale > 0` bo'lsa
  `<Banner tone="warn">` va matn:
  ``t`${d.stale} ta reklamaning holati Meta'dan uzoq vaqt o'qilmagan.` ``
  `d.refreshing` bo'lsa davomi: ``t`Hozir yangilanmoqda…` ``.
  Aks holda: ``t`Mijozning ulanishi yoki tarifini tekshiring.` ``
- **Qatorda** — `a.stale && a.syncedAt` bo'lsa, badge ostida kichik kulrang
  matn: ``t`Oxirgi o'qilgan: ${formatDateTime(a.syncedAt)}` ``.
- **Qayta so'rash** — `d.refreshing === true` bo'lsa, 20 soniyadan keyin
  so'rovni **bir marta** qayta yuboring (`useClientAds` uchun
  `refetchInterval: d => d?.refreshing ? 20_000 : false`, eng ko'pi 3 urinish).
  Backend 15 daqiqada bir martadan ko'p navbatga qo'ymaydi, shuning uchun
  keyingi javobda `refreshing: false` keladi va so'rash to'xtaydi.
- **"Reklama N ta · M ishlayapti"** — o'zgarmaydi; `running` endi to'g'ri.

### 6. Reklama detali (`/ads/:adId/launch`)

`row` ham shu maydonlarni olib keladi (`delivery`, `is_stale`, `synced_at`).
Detal sahifasidagi holat badge'i ham `statusOf` dan o'tadi; 2-qadamdan
keyin o'zi to'g'rilanadi. O'chirilgan kampaniyaning detali ochilsa,
`row.delivery === "deleted"` va label "O'chirilgan" keladi. Unga
`neutral` badge kerak (yoki `"deleted"` ni ham `DeliveryStatus` ga qo'shing).

## Tekshirish

1. Mijoz Ads Manager'da kampaniyani o'chirsin → keyingi sinxrondan keyin
   (har 30 daqiqada; nusxa 3 soatdan eski bo'lsa, ofis sahifasi ochilganda)
   qator yo'qoladi, izohda "o'chirilgan 1 ta" chiqadi. Hisob bizda o'chirilgan
   (`is_active=false`) bo'lsa, o'chirilganini aniqlab bo'lmaydi: qator
   "Hali o'qilmagan" bo'lib qoladi.
2. Ads Manager'da to'xtatsin → "To'xtatilgan", `running` 1 ga kamayadi.
3. Ads Manager'da kampaniya ichidagi hamma reklamani o'chirsin →
   "Reklamasi qolmagan".
4. Tarifi tugagan mijoz → eski "Ishlayapti" o'rniga "Holati eskirgan" va
   sariq banner; sahifa ochilgach 20 soniyada yangi holat keladi.
