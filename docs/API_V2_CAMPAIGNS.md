# Reklama bo'limi: API v2 ga ulanish

Reklama ro'yxati, Targetolog jadvali va kampaniya sahifasini v1 dan v2 ga
o'tkazish bo'yicha yo'riqnoma. Hozirgi frontend kodi bo'yicha yozilgan.

**Prod:** `https://api.targetolog.ai`. v1 ishlashda davom etadi, shuning uchun
ulanish bosqichma-bosqich qilinadi.

---

## 1. Nima tuzatiladi

| Ekranda | v1 da | v2 da |
|---|---|---|
| `Kliklar`, `CTR` | Doim 0 | Havolaga bosishlar |
| Tanlangan davrdagi `Qamrov` | Noma'lum bo'lsa ham 0 | Noma'lum bo'lsa `null` |
| `Comp Reg` va boshqa sayt hodisalari | `Saytga o'tishlar 0` | Haqiqiy natija va to'g'ri nom |
| Instagram profilga o'tish | Sanalmaydi | Sanaladi |
| Natija turi | Meta'da yaratilganlarda ko'pincha `click` | Guruh maqsadidan olinadi |
| Ichki reklamalar | Doim 7 kun | Tanlangan davr |

`Sarflandi` va `Ko'rsatildi` o'zgarmaydi.

---

## 2. Endpoint'lar

Hammasi `GET`, avtorizatsiya v1 dagidek: `Authorization: Bearer <access_token>`.

| v1 | v2 | Hook |
|---|---|---|
| `/api/v1/campaigns` | `/api/v2/campaigns` | `useCampaigns` |
| `/api/v1/campaigns/manager` | `/api/v2/campaigns/manager` | `useManager` |
| `/api/v1/campaigns/{id}/tree` | `/api/v2/campaigns/{id}/tree` | `useCampaignTree` |
| `/api/v1/campaigns/{id}` | `/api/v2/campaigns/{id}` | `useCampaign` |

**v1 da qoladi:** `POST /campaigns/sync`, pause, resume, budget, delete,
`/edit`, `/history`, `/campaigns/ads/...` va `/campaigns/manage/...`.

### Query parametrlar

| Parametr | Qiymat | Qaysi endpoint |
|---|---|---|
| `period` | `today`, `7d`, `30d`, `90d`, `custom` (standart: `7d`) | Hammasi |
| `since`, `until` | `YYYY-MM-DD`, faqat `period=custom` bilan | Hammasi |
| `status` | `all`, `running`, `paused` | Ro'yxat, manager |
| `source` | `all`, `here`, `network`, `other_account` | Ro'yxat, manager |
| `network` | `all` yoki tarmoq id | Ro'yxat, manager |
| `started` | `1` yoki `first` | Faqat ro'yxat |

Xatolar: `401` token yaroqsiz, `404` kampaniya topilmadi yoki hozirgi sahifaga
tegishli emas, `422` id yoki sana formati noto'g'ri.

---

## 3. Javobdagi o'zgarishlar

Quyida faqat v1 dan farqi yozilgan. Qolgan maydonlar v1 bilan bir xil.

### Yangi `kind` qiymatlari

v1 dagilar qoladi: `lead`, `chat`, `call`, `view`, `click`, `site`, `profile`,
`sub`. Yangilari:

| `kind` | Ma'nosi | Ko'rsatish |
|---|---|---|
| `conversion` | Saytdagi hodisa: ro'yxatdan o'tish, xarid va boshqalar | Nom `resultLabel` dan olinadi |
| `recall` | Reklamani eslab qolganlar | `Eslab qolganlar` |
| `other` | Bu yerda sanalmaydigan maqsad | Natija va narx o'rniga `—` |

### Yangi maydon: `resultLabel`

`string | null`. Faqat `kind: "conversion"` da to'ladi, masalan
`Ro'yxatdan o'tishlar`, `Xaridlar`, `Konversiyalar`. Hozircha faqat o'zbekcha
keladi.

Bu maydon ro'yxat qatorida, manager qatorida va kampaniya sahifasida bor.

### `GET /api/v2/campaigns/manager`

```json
{
  "level": "campaign",
  "kind": "conversion",
  "resultLabel": "Ro'yxatdan o'tishlar",
  "results": 10,
  "unitCost": { "minor": 90, "currency": "USD", "exponent": 2 },
  "spent": { "minor": 896, "currency": "USD", "exponent": 2 },
  "impressions": 3945,
  "reach": 2810,
  "clicks": 218
}
```

| Maydon | Farqi |
|---|---|
| `clicks` | Havolaga bosishlar. `CTR = clicks / impressions` |
| `reach` | `number \| null`. `null` bo'lsa `—` ko'rsating, `0` emas |

`reach: 0` faqat ko'rsatish bo'lmaganda keladi. Qamrov quyidagi davrlarda
keladi: bugun, kecha, 7, 14, 28, 30, 90 kun, shu hafta, o'tgan hafta, shu oy,
o'tgan oy. Kalendardan qo'lda tanlangan boshqa sanalarda `null` keladi.

### `GET /api/v2/campaigns`

Javob v1 bilan bir xil. Har bir qatorda `kind` yangilangan va `resultLabel`
qo'shilgan. `metrics.results` va `metrics.unitCost` to'g'ri natijani beradi.

### `GET /api/v2/campaigns/{id}/tree`

Javob shakli v1 bilan bir xil, reklama raqamlari tanlangan davrga mos keladi.
`period`, `since`, `until` ni yuboring. Yubormasangiz 7 kun qaytadi.

### `GET /api/v2/campaigns/{id}`

Sahifa javobi v1 bilan bir xil, quyidagilardan tashqari:

| Maydon | Farqi |
|---|---|
| `kind`, `resultLabel` | Yuqoridagidek |
| `ads` | `period`, `since`, `until` bo'yicha. Standart: 7 kun |
| `stats` | Sayt hodisasi va Instagram uchun natija, narx va oldingi 7 kunga farqi. Natija yo'q bo'lsa `null` |
| `panel.note` | Natija sanalganda `null` |
| `panel.periods[].cards` | Sanaladigan bo'lsa, boshida `leads` va `cpl` kartalari turadi. Yorlig'i `label` dan olinadi |

`stats` va `panel` faqat 7, 30, 90 kun bilan ishlaydi. Tanlangan davrga faqat
`ads` ergashadi.

---

## 4. Frontendni ulash

### 4.1. So'rov yo'lini ochish

Ehtiyot bo'ling: `/v2/...` yo'lini oddiy `api.get` ga yozsangiz, so'rov
`/api/v1/v2/...` bo'lib ketadi va `pending.ts` uni `not_ready` bilan to'xtatadi.
To'g'ri yo'l uch joyda o'zgartirishni talab qiladi.

**`packages/api/src/client.ts`**: `apiFetch` ga `base` qo'shing va v2 uchun
yordamchi yarating.

```ts
export const API_V2_BASE = "/api/v2";

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { json?: unknown; base?: string } = {},
): Promise<T> {
  const { json, headers, base = API_BASE, ...rest } = init;
  // ...
  const url = new URL(base + path, typeof location !== "undefined" ? location.origin : "http://localhost");
  // ...
}

export const apiV2 = {
  get: <T>(path: string) => apiFetch<T>(path, { base: API_V2_BASE }),
};
```

**`packages/api/src/live/backend.ts`**: to'liq yo'lga `/api/v1` qo'shilmasin.

```ts
export const backendUrl = (path: string) =>
  path.startsWith("/api/") ? `${base}${path}` : `${base}/api/v1${path}`;
```

**`packages/api/src/live/direct.ts`**: v2 ham `campaigns` domeni deb tanilsin.

```ts
const path = new URL(url, "http://local").pathname.replace(/^\/api\/v[12]\//, "");
```

`transport.ts` ni o'zgartirish shart emas: u faqat `/api/v1` ni olib tashlaydi,
`/api/v2/...` yo'lini o'zgartirmaydi.

### 4.2. Tiplar

`packages/api/src/campaigns.ts`. `ResultKind` ning o'zini kengaytirmang: u
Dashboard'da ham ishlatiladi va `Record<ResultKind, ...>` ro'yxatlarini buzadi.

```ts
export type CampaignKind = ResultKind | "conversion" | "recall" | "other";

export interface CampaignRow {
  kind: CampaignKind;
  resultLabel?: string | null;
  // qolgani o'zgarmaydi
}

export interface ManagerRow {
  kind: CampaignKind;
  resultLabel?: string | null;
  reach: number | null;
  // qolgani o'zgarmaydi
}

export interface CampaignDetail {
  kind: CampaignKind;
  resultLabel?: string | null;
  // qolgani o'zgarmaydi
}
```

### 4.3. Hook'lar

```ts
export const useCampaigns = (f: CampaignFilters, started?: string) =>
  useQuery({
    queryKey: [KEY, "list", f, started ?? ""],
    queryFn: () => apiV2.get<CampaignList>(`/campaigns?${listQuery(f, started)}`),
    placeholderData: keepPreviousData,
    refetchInterval: pollUntil<CampaignList>(d => d?.state !== "reading"),
  });

export const useManager = (f: CampaignFilters, enabled: boolean) =>
  useQuery({
    queryKey: [KEY, "manager", listQuery(f)],
    queryFn: () => apiV2.get<ManagerData>(`/campaigns/manager?${listQuery(f)}`),
    placeholderData: keepPreviousData,
    enabled,
  });

const rangeQuery = (f?: Pick<CampaignFilters, "period" | "since" | "until">) => {
  if (!f) return "";
  const q = new URLSearchParams({ period: f.period });
  if (f.period === "custom" && f.since && f.until) {
    q.set("since", f.since);
    q.set("until", f.until);
  }
  return `?${q}`;
};

export const useCampaign = (id: string, f?: Pick<CampaignFilters, "period" | "since" | "until">) =>
  useQuery({
    queryKey: [KEY, "detail", id, rangeQuery(f)],
    queryFn: () => apiV2.get<CampaignDetail>(`/campaigns/${id}${rangeQuery(f)}`),
  });

export const useCampaignTree = (id: string, enabled: boolean, f?: Pick<CampaignFilters, "period" | "since" | "until">) =>
  useQuery({
    queryKey: [KEY, "tree", id, rangeQuery(f)],
    queryFn: () => apiV2.get<CampaignTree>(`/campaigns/${id}/tree${rangeQuery(f)}`),
    enabled,
    refetchInterval: pollUntil<CampaignTree>(d => !d?.groups.some(g => g.deleting || g.ads.some(a => a.deleting))),
  });
```

`Tree` komponentiga ro'yxatdagi `filters` ni uzating. Kampaniya sahifasiga ham
davrni uzatish kerak: `filters` hozir faqat ro'yxat holatida turadi, shuning
uchun uni havola query'si orqali yuborish mumkin. Davr yuborilmasa, sahifa 7
kunni ko'rsatadi.

Kesh `campaigns` kaliti bilan tozalanadi, mutatsiyalarga tegmang.

### 4.4. Yorliqlar

`apps/cabinet/src/pages/campaigns/labels.ts`, `useAdWords`:

```ts
const results: Record<CampaignKind, string> = {
  // mavjudlari...
  conversion: t`Konversiyalar`, recall: t`Eslab qolganlar`, other: t`Natija`,
};
const unitCost: Record<CampaignKind, string> = {
  // mavjudlari...
  conversion: t`Bitta natija narxi`, recall: t`Bitta eslab qolgan narxi`, other: t`Natija narxi`,
};
const total: Record<CampaignKind, string> = {
  // mavjudlari...
  conversion: t`Jami natija`, recall: t`Jami eslab qolgan`, other: t`Jami natija`,
};
const noun: Record<CampaignKind, string> = {
  // mavjudlari...
  conversion: t`natija`, recall: t`eslab qolgan`, other: t`natija`,
};
```

Nom hamma joyda shu tartibda olinadi:

```ts
const resultName = (r: { kind: CampaignKind; resultLabel?: string | null }) =>
  r.resultLabel ?? w.results[r.kind];
```

`apps/cabinet/src/lib/labels.ts` dagi `useKindText` ham yangi turlarni bilishi
kerak. Hozir `count` da ularning `case` i yo'q va `undefined` qaytadi.

`KindMark` va `kindIcon` yangi turlarni tanimaydi, shuning uchun moslab bering:

```ts
export const markKind = (k: CampaignKind): Kind =>
  k === "conversion" ? "site" : k === "recall" ? "view" : k === "other" ? "neutral" : k;
```

### 4.5. O'zgartiriladigan ekranlar

| Fayl | O'zgarish |
|---|---|
| `campaigns/Row.tsx:151` | `w.results[r.kind]` o'rniga `resultName(r)`. `kind: "other"` da raqam o'rniga `—` |
| `campaigns/Row.tsx:156`, `campaigns/Campaign.tsx:165`, `campaigns/dialogs.tsx:38` | `w.unitCost[...]` yangi turlarni oladi |
| `campaigns/Sections.tsx:104` | `w.noun[c.kind]` yangi turlarni oladi |
| `campaigns/Tree.tsx:167` | `kt.count(ctx.kind, ...)`: `conversion` uchun `resultLabel` bilan, `other` uchun `—` |
| `campaigns/Manager.tsx:221` | `<KindMark kind={markKind(r.kind)} />` |
| `campaigns/Manager.tsx:245` | `r.reach == null ? "—" : formatNumber(r.reach)` |
| `campaigns/Manager.tsx:182`, `:266` | Jami `Qamrov` qo'shilmaydi, `—` ko'rsatiladi. Bir odam bir necha qatorda bo'lishi mumkin |
| `campaigns/Manager.tsx:241`, `:260` | Natija matnida `resultLabel` hisobga olinadi |
| `networks/Network.tsx:116` | `useCampaigns` orqali avtomatik v2 ga o'tadi, yorliqlarni tekshiring |

`campaigns/EditSheet.tsx:288` ga tegmang: `/edit` v1 da qoladi va eski turlarni
qaytaradi.

### 4.6. Arzon narxni ko'rsatish

API `unitCost` ni butun sentda beradi: 1,6 sent `2` bo'lib keladi. `formatMoney`
esa bitta kasr qoldiradi va `0 USD` chiqaradi. Aniq narx uchun `spent` va
`results` dan hisoblang:

```ts
const preciseCost = (spent: Money, results: number, per: 1 | 1000 = 1) => {
  const value = (spent.minor / 10 ** spent.exponent / results) * per;
  return formatNumber(value, { maximumFractionDigits: value < 0.1 ? 3 : 2 }) + ` ${spent.currency}`;
};
```

### 4.7. Mock

Demo rejim uchun `packages/api/src/mock/handlers/campaigns.ts` ga v2 yo'llarini
qo'shing. `manager` ni `:id` dan oldin yozing.

```ts
http.get("*/api/v2/campaigns/manager", /* v1 handler bilan bir xil */),
http.get("*/api/v2/campaigns", /* ... */),
http.get("*/api/v2/campaigns/:id/tree", /* ... */),
http.get("*/api/v2/campaigns/:id", /* ... */),
```

Mock `manager()` javobiga `reach: null` va `kind: "conversion"` bo'lgan qator
qo'shing, shunda bu holatlar demo'da ham ko'rinadi.

---

## 5. Lokal ishga tushirish

```bash
VITE_MOCKS=0 VITE_API_URL=https://api.targetolog.ai pnpm --filter @tg/cabinet dev --port 5374
```

Prod API bilan ishlaganda quyidagilarga amal qiling:

- Faqat `Targetolog AI` yoki test akkaunt bilan kiring, mijoz akkauntiga kirmang.
- `To'xtatish`, `O'chirish`, byudjet va `Reklama berish` tugmalarini bosmang:
  ular haqiqiy reklamaga ta'sir qiladi.
- `Yangilash` tugmasini ketma-ket bosmang: Meta limiti barcha mijozlar uchun
  umumiy.
- Lokaldan Facebook'ni qayta ulamang: javob `targetolog.ai` ga qaytadi.

---

## 6. Tekshirish ro'yxati

Ads Manager bilan **bir xil sanalarni** tanlab solishtiring.

- [ ] `TOF - CBO - Comp Reg - Osiyo - 28.10`: `Ro'yxatdan o'tishlar` 10 ta, narxi 0,90 USD
- [ ] `TOF - CBO - Comp Reg - UZ - 28.10`: 121 ta, narxi taxminan 0,21 USD
- [ ] `Targetolog AI · Saytga tashrif #2`: 6 080, narxi `0 USD` emas
- [ ] `Targetolog` jadvali: `Kliklar` va `CTR` 0 emas
- [ ] `Oxirgi 14 kun`: `Qamrov` raqam, qo'lda tanlangan sanada `—`
- [ ] Ro'yxatda 14 kun tanlanganda ichki reklamalar raqami ham 14 kunlik
- [ ] Jami qatorda `Qamrov` qo'shilmagan
- [ ] `kind: "other"` kampaniyada `0` emas, `—`
- [ ] Kampaniya sahifasi: yuqori blok, `Raqamlar` va `Reklamalar` bir xil natija nomini ko'rsatadi
- [ ] `Yangilash`, `To'xtatish` va `Yoqish` v1 orqali ishlashda davom etadi
- [ ] Demo rejim buzilmagan
- [ ] `pnpm typecheck`, `pnpm test`, `pnpm i18n:extract` o'tgan

Meta natijasi bilan 1–2 ta farq bo'lishi mumkin, chunki Meta ba'zi natijalarni
kechroq kunga yozadi. Kattaroq farqni backend'ga xabar qiling.

---

## 7. Hali qamrab olinmagan

- **`Qaysi reklama ishlayapti` bloki:** `Comp Reg` kampaniyalarida reklamalar hali
  natijasiz deb baholanishi mumkin.
- **`Raqamlar` grafigi:** kunlik grafikda sayt hodisalari seriyasi yo'q.
- **`resultLabel` tarjimasi:** hozircha faqat o'zbekcha.
- **Dashboard:** bu hujjatga kirmaydi, u `/api/v1/metrics/numbers` dan o'qiydi.

Dashboard'dagi `Bittasi —` xatosi esa frontendning o'zida:
`packages/api/src/live/bridges/dashboard.ts:182`. Backend `result_cost` uchun
`"—"` matnini yuboradi, `||` uni qiymat deb oladi va `cpl` ga o'tmaydi. Tuzatish:

```ts
const resultCost = r.result_cost && r.result_cost !== "—" ? r.result_cost : "";
cost: costOf(resultCost || (kind === "lead" ? r.cpl : ""), c),
```
