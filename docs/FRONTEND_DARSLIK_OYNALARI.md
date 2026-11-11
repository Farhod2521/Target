# Darsliklar boshqa oynalarda — frontend uchun qo'llanma

Sana: 2026-11-11. Backend: `feat/tutorial-places` branch, migratsiya `0041`.

## Nima o'zgardi

Har bir darslikda endi **`places`** maydoni bor: darslik kabinetning qaysi oynalarida
chiqishi. Bitta darslik bir nechta oynada chiqishi mumkin (masalan, «Lidlar» va «CRM»).

- Eski `type` maydoni (`meta` / `google` / `gpt`) o'zgarmadi — u tarmoq turi.
- `places` — oyna turi. Ofis darslikni yozganda tanlaydi.
- `places` bo'sh bo'lsa, darslik faqat «Darsliklar» bo'limida chiqadi (hozirgi darsliklarning
  hammasi shunday — migratsiya ularga bo'sh ro'yxat qo'yadi).
- «Darsliklar» bo'limi (`/app/tutorials/`) avvalgidek **hamma** yoqilgan darsliklarni ko'rsatadi.
- Yashirilgan (`status=false`) darslik hech qaysi oynada chiqmaydi.

## Oynalar ro'yxati

Ro'yxatni frontendda qattiq yozmang — backend uni har javobda `places` kalitida beradi
(pastga qarang). Hozirgi qiymatlar va ular qaysi sahifaga mos kelishi:

| `value`        | `label`              | Kabinet sahifasi (taklif)                                   |
|----------------|----------------------|-------------------------------------------------------------|
| `dashboard`    | Bosh sahifa          | `/app/`                                                     |
| `launch`       | Reklama yaratish     | `/app/campaigns/launch/...`, `/app/networks/:id/launch/`   |
| `campaigns`    | Reklamalar           | `/app/campaigns/`, `/app/campaigns/:id/`                    |
| `leads`        | Lidlar               | `/app/leads/...`                                            |
| `crm`          | CRM                  | `/app/crm/...`                                              |
| `chat`         | AI chat              | `/app/chat/...`                                             |
| `agent`        | AI agent             | `/app/agent/...`                                            |
| `google`       | Google reklama       | `/app/google/...`                                           |
| `chatgpt`      | ChatGPT reklama      | `/app/networks/chatgpt/...`                                 |
| `audiences`    | Auditoriyalar        | `/app/connections/audiences/`                               |
| `montage`      | Montaj               | `/app/montaj/...`                                           |
| `surveys`      | So'rovnoma           | `/app/sorovnoma/`                                           |
| `destinations` | Lidlarni yuborish    | `/app/destinations/sheet/`, `/app/destinations/telegram/`   |
| `connections`  | Ulanishlar           | `/app/connections/`, `/app/networks/:id/`                   |
| `billing`      | To'lov va tariflar   | `/app/billing/...`                                          |
| `referrals`    | Referal              | `/app/referrals/...`                                        |

Sahifa ↔ `place` moslashuvi frontendning ishi: har bir sahifa o'zining `place` qiymatini biladi.
Yangi oyna kerak bo'lsa, backendga qiymat qo'shish so'raladi.

---

## 1. Kabinet

### 1.1. Oynaning darsliklari

```
GET /api/v1/tutorials?place=crm
Authorization: Bearer <token>
```

Query:

| nom      | majburiy | izoh                                                          |
|----------|----------|---------------------------------------------------------------|
| `place`  | yo'q     | yuqoridagi `value`lardan biri; berilsa, faqat shu oynaniki    |
| `type`   | yo'q     | `meta` / `google` / `gpt` — avvalgidek                        |
| `q`      | yo'q     | sarlavha yoki izohdan qidiruv — avvalgidek                    |
| `offset` | yo'q     | sahifalash — avvalgidek (sahifa 50 ta)                        |

Javob `200` (avvalgi shakl + `// YANGI` deb belgilangan kalitlar):

```json
{
  "rows": [
    {
      "id": "6c1f…",
      "title": "Lidni CRM ga qo'shish",
      "type": "meta",
      "type_label": "Meta",
      "places": [                                   // YANGI
        { "value": "leads", "label": "Lidlar" },
        { "value": "crm",   "label": "CRM" }
      ],
      "description": "…",
      "image_url": "/api/v1/tutorials/6c1f…/image?t=…",
      "video": { "kind": "youtube", "url": "…", "embed_url": "…" },
      "created_at": "2026-11-11T08:00:00+00:00",
      "updated_at": "2026-11-11T08:00:00+00:00"
    }
  ],
  "total": 1,
  "offset": 0,
  "next_offset": null,
  "has_more": false,
  "types":  [ { "value": "meta", "label": "Meta" }, … ],
  "places": [ { "value": "dashboard", "label": "Bosh sahifa" }, … ]   // YANGI
}
```

- `rows[].places` — darslik chiqadigan oynalar, doim backend katalogi tartibida, takrorsiz.
  Bo'sh bo'lsa `[]`.
- Yuqori darajadagi `places` — butun katalog (filtr va ofis formasi uchun).

Xatolar:

| kod   | qachon                                         |
|-------|------------------------------------------------|
| `401` | token yo'q yoki eskirgan                       |
| `422` | `place` katalogda yo'q qiymat (masalan `kino`) |

Bitta darslik (`GET /api/v1/tutorials/{id}`) ham endi `places` bilan keladi.

### 1.2. Oynada qanday ko'rsatish (taklif)

1. Sahifa ochilganda `GET /tutorials?place=<shu oyna>` so'raladi. React Query kaliti:
   `["tutorials", "place", place]`. Mavjud `useTutorials(type, q)` ga `place` qo'shish yoki
   alohida `useTutorialsFor(place)` qilish mumkin.
2. `total === 0` bo'lsa — **hech narsa chizilmaydi** (bo'sh joy, "darslik yo'q" yozuvi kerak emas).
3. `total > 0` bo'lsa — sarlavha yonida kichik «Darslik (N)» tugmasi yoki sahifa tepasida
   yig'iladigan qator. Shell'da `help` prop bor (`CabinetTop`) — tugma o'sha joyga mos keladi.
4. Bosilganda: bitta darslik bo'lsa — darhol `/app/tutorials/:id/` (yoki shu sahifaning o'zida
   modal pleer); bir nechta bo'lsa — kartochkalar ro'yxati, har biri `/app/tutorials/:id/` ga.
   Pleer mantiqi «Darsliklar» bo'limidagi bilan bir xil (`video.kind`, `stream_url`, `image_url`).
5. `image_url` va `video.stream_url` ichidagi token 6 soat yashaydi — sahifa uzoq ochiq
   qolsa, ro'yxatni qayta so'rang (bo'limdagi bilan bir xil qoida).
6. Darsliklar bo'limidagi filtrga `place` qo'shish shart emas; xohlasangiz, `places`
   katalogidan tanlov qilish mumkin.

---

## 2. Ofis (`/office/tutorials`)

### 2.1. Ro'yxat

```
GET /api/v1/office/tutorials?place=crm&type=&q=&status=&offset=0
```

- Yangi `place` filtri (ixtiyoriy). Noto'g'ri qiymat → `422`.
- Javobda `rows[].places` va yuqori darajada `places` katalogi (kabinetdagi bilan bir xil).

### 2.2. Yaratish va tahrirlash

`POST /api/v1/office/tutorials` va `PUT /api/v1/office/tutorials/{id}` — multipart forma,
avvalgi maydonlarga **`places`** qo'shildi.

`places` har bir tanlangan oyna uchun bir marta yuboriladi:

```ts
const form = new FormData();
form.append("title", title);
form.append("type", type);
// …avvalgi maydonlar…
if (places.length) places.forEach(p => form.append("places", p));
else form.append("places", "");   // hammasini olib tashlash
```

Qoidalar:

| yuborilgani                       | natija                                              |
|-----------------------------------|-----------------------------------------------------|
| `places=crm`, `places=leads`      | darslik shu ikki oynada chiqadi                     |
| bitta bo'sh `places=""`           | hech qaysi oynada chiqmaydi (faqat bo'limda)        |
| `places` umuman yuborilmagan, PUT | **avvalgi oynalar saqlanadi**                       |
| `places` umuman yuborilmagan, POST| bo'sh ro'yxat                                       |
| takror yoki boshqa tartib         | backend tartiblaydi va takrorni olib tashlaydi      |

Shuning uchun formada multi-select bo'lsa, **doim** yuboring: tanlangan bo'lsa qiymatlarni,
tanlanmagan bo'lsa bitta bo'sh `places`. Aks holda «hammasini olib tashlash» ishlamaydi.

Xato `422`, avvalgi shaklda:

```json
{ "problems": { "places": "Bunday oyna yo'q." } }
```

Formada maydon: «Qaysi oynalarda chiqsin» — chiplar yoki checkbox ro'yxati, variantlar
`GET /office/tutorials` javobidagi `places` katalogidan. Tahrirlashda boshlang'ich qiymat:
`row.places.map(p => p.value)`.

### 2.3. O'zgarmaganlar

`PATCH /{id}/status`, `DELETE /{id}`, video bo'laklab yuklash (`/uploads/chunk`), stream,
rasm — hammasi avvalgidek.

---

## 3. TypeScript turlari (`packages/api/src/tutorials.ts` uchun)

```ts
export type TutorialPlace =
  | "dashboard" | "launch" | "campaigns" | "leads" | "crm" | "chat" | "agent"
  | "google" | "chatgpt" | "audiences" | "montage" | "surveys"
  | "destinations" | "connections" | "billing" | "referrals";

export interface Choice<T extends string = string> { value: T; label: string }

export interface Tutorial {
  // …avvalgi maydonlar…
  places: Choice<TutorialPlace>[];
}

export interface TutorialsPage {
  // …avvalgi maydonlar…
  types: Choice<TutorialType>[];
  places: Choice<TutorialPlace>[];
}

export const useTutorialsFor = (place: TutorialPlace) =>
  useQuery({
    queryKey: ["tutorials", "place", place],
    queryFn: () => api.get<TutorialsPage>(`/tutorials?place=${place}`),
    staleTime: 5 * 60_000,
  });
```

Ofisda darslik yaratilgan / tahrirlangan / yashirilgan / o'chirilgandan keyin `["tutorials"]`
kalitini invalidate qilish kifoya — oynalar kaliti ham shu prefiks ostida.

## 4. Tekshirish ro'yxati

- [ ] Ofis formasida «Qaysi oynalarda chiqsin» tanlovi; tahrirlashda avvalgi tanlov ko'rinadi.
- [ ] Hammasini olib tashlab saqlansa, darslik oynalardan yo'qoladi (bo'sh `places` yuborilgan).
- [ ] Ofis ro'yxatida `place` filtri (ixtiyoriy).
- [ ] Har bir mos kabinet sahifasida `?place=` so'rovi; darslik yo'q bo'lsa hech narsa chiqmaydi.
- [ ] Yashirilgan darslik oynada chiqmaydi.
- [ ] Mock handler (`packages/api/src/mock/handlers/tutorials.ts`) `place` filtrini va `places`
      maydonini qaytaradi.
