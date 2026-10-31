# Frontend repo'dagi Claude Code uchun prompt

Quyidagi matnni `targetolog-ai-frontend` repo'sida ishlaydigan Claude Code'ga bering.

---

Backend Meta xatolarini tushuntiradigan yagona `Refusal` obyektini qaytaradigan
bo'ldi. Shuni frontendga ulab ber: user "qayta urinib ko'ring" o'rniga aniq sabab
va tartiblangan qadamlarni ko'rishi kerak.

Avval kodni o'qi, reja tuz, keyin bosqichma-bosqich ishla. Har bosqichdan keyin
`typecheck` va testlarni ishga tushir. Mavjud komponentlar, tillar (`lingui`) va
uslubni ishlat, keraksiz abstraksiya qo'shma. Mock handler'larni ham yangila.

## API tiplari

Avval OpenAPI tiplarini qayta generatsiya qil. Backend deploy bo'lmagan bo'lsa,
tiplarni shu bilan qo'lda qo'sh.

```ts
interface Refusal {
  key: string | null;
  retryable: boolean;
  title: string;
  cause: string;
  steps: string[];
  providerWords: string | null;
  html: string | null;
  explaining: boolean;
  fix: { label: string; url: string | null; to: string | null } | null;
  retryAfterSeconds: number | null;
}
interface RefusalAnswer { key: string; html: string | null; explaining: boolean }
```

## 1. `ApiError`

`packages/api/src/client.ts`. Xato javob: status `422`,
`{ detail, code: "provider_refused", refusal: Refusal }`. `ApiError`da
`refusal` getter bo'lsin, transport bu maydonni yo'qotmasin.

## 2. `<RefusalDialog>`

Cabinet ildiziga bitta dialog va `openRefusal(refusal, { onRetry? })`.
`packages/api/src/query.ts`dagi `MutationCache.onError`da `error.refusal` bo'lsa
dialog ochilsin, toast chiqmasin. `packages/api` ichidan cabinet'ga to'g'ridan-to'g'ri
bog'lanma: mavjud usuldagi callback yoki store orqali ula.

Tartib: `title`; `html` bo'lsa uni chiqar (`dangerouslySetInnerHTML`, backend escape
qilgan; faqat `p ol ul li a b code table` teglari); aks holda `cause` va raqamlangan
`steps`; `explaining` bo'lsa "Yechim tayyorlanmoqda..."; `providerWords` yig'iladigan
"Meta javobi" blokida; tugmalar: `fix`, "Qayta urinish" (`onRetry` bo'lsa), "Supportga yozish".
`retryAfterSeconds` bo'lsa, "Qayta urinish"ni shuncha soniya o'chirib tur.

`fix`: `url` `http` bilan boshlansa yangi oyna; `/` bilan boshlansa ichki router
(`/app/connections/` mavjudligini tekshir); `url` yo'q, `to` bo'lsa `launch/Review.tsx`dagi
`useTarget` kabi reklama ustasi bo'limi.

Polling: `refusal.explaining && refusal.key` bo'lsa
`GET /api/v1/refusals/answer?key=` 3 soniyada bir marta, ko'pi bilan 20 marta.
`html` kelsa almashtir va to'xta. `explaining: false` kelsa yoki urinish tugasa to'xta.
Dialog yopilsa bekor qil.

Dialog telefonda ham ishlasin.

## 3. Manbalar

Avtomatik (2-band orqali): `/connections/audiences*`,
`GET /launch/drafts/{id}/locations`.

Qo'lda ulanadigan to'rttasi:

- **`apps/cabinet/src/pages/launch/Review.tsx`, `Failed`:** `draft.failure.refusal`.
  Sahifa qoladi. Bir xato uchun bir marta avtomatik dialog och, `onRetry` = mavjud retry.
  "AI dan so'rash" tugmasi o'rniga dialogni qayta ochadigan "Yechimni ko'rish".
- **`apps/cabinet/src/pages/campaigns/ControlLine.tsx`:** `s.failure.refusal` bo'lsa
  xato matni yoniga "Batafsil" tugmasi. Mavjud `fix` tugmasi qoladi.
- **`apps/cabinet/src/pages/launch/MediaTile.tsx`:** `state` `upload_failed` yoki
  `delete_failed` va `tile.refusal` bo'lsa, tile bosilganda dialog.
- **Ulanishlar sahifasi:** URL'da `?refusal_key=<key>&error=<matn>` bo'lsa, dialog och
  (`title`: "Meta ulanishni rad etdi", `cause`: error, `explaining: true`,
  qolganlari bo'sh), keyin parametrni URL'dan olib tashla.

## 4. Ofis sahifasi

`apps/office` ichida "Meta xatolari" sahifasi. Mavjud ofis sahifalari uslubida.

- `GET /api/v1/office/refusals?tab=&q=&offset=` →
  `{ tab, tabs: {value,label}[], links: {value,label}[], rows, held, total, offset, next_offset, has_more }`.
- `rows[]`: `id, key, operation, operation_label, provider_title, provider_message,
  answer_uz, answer_ru, answer_en, written_by ("ai"|"office"), held, retired, hits,
  created_at, edited_at`.
- `PATCH /api/v1/office/refusals/{id}`, body: o'zgargan `answer_uz|ru|en`. Javob: yangi qator.
- Uchala til bo'sh bo'lsa `400`, `detail`ni ko'rsat.
- Tablar `tabs[]`dan, menyu nishoni `held`dan. Tahrirlash oynasida Meta so'zlari va
  `links[]` ko'rinsin: `[[nom]]` matnda havolaga aylanadi. Barcha ofis rollariga ko'rinadi.

## 5. Eski kod

- `LaunchErrorCode` 31 ta qiymatga ko'paydi. `Record<LaunchErrorCode, ...>` bo'lsa to'ldir.
- `Failure.raw` endi ichki kod emas, Meta'ning so'zlari yoki `null`.
- Auditoriya xatosi `502` emas, `422`.
- `explanationHtml`, `explaining`, `guide` maydonlari hozircha qoladi, ularni olib tashlama.

## Yakunda

Mock'lar bilan quyidagilarni tekshir: dialog ochilishi, polling'da javob almashishi,
`retryable`, `fix`ning uch holati, ikki marta ochilmasligi, telefon kengligi. Nima
qilganingni va tekshirolmaganingni ochiq yoz. Commit va push'ni so'ralmaguncha qilma.
