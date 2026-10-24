# llmkit — o'zgarishlar tarixi

Semantik versiyalash.

## 0.5.0 — 2026-10-12

### Qo'shildi
- `ClaudeSpendLimit`: tashkilot yoki workspace xarajat chegarasiga yetgan,
  yoki kredit tugagan (402 `billing_error`, yoki «usage limit», «spend
  limit», «credit balance» deb aytgan 4xx). Qayta urinilmaydi.
- Kesh siyosati `"instructions"`: `system` yolg'iz bo'lsa ham keshga
  belgilanadi — o'zgaruvchan qism xabarning o'zida bo'lgan chaqiruvlar uchun.

## 0.4.0 — 2026-10-09

### Qo'shildi
- `Image` (bayt, `media_type`, `label`) va `ClaudeClient.structured(images=...)`.
  Rasmlar promptdan oldin, har biri o'z yorlig'i bilan yuboriladi. Rasmsiz
  chaqiruv avvalgidek bitta satr bo'lib ketadi.

## 0.3.0 — 2026-09-15

### Qo'shildi
- `ClaudeClient.converse()` va `ToolStream` — javob yozilishidan oldin
  model tool chaqira oladi. Chaqiruv chaqiruvchining `run_tool` funksiyasi
  orqali bajariladi, natija modelga qaytadi va keyingi raund boshlanadi.
  Har raund matni oqim bo'lib keladi, raundlar orasiga bo'sh qator qo'yiladi.
- Raundlar soni cheklangan (`max_rounds`, standart 4). Oxirgi raund
  `tool_choice: none` bilan yuboriladi — model bor ma'lumot bilan javob
  berishi shart.
- `Tool` (nom, tavsif, argumentlar pydantic modeli), `ToolCall`,
  `ToolOutput`, `ToolRunner`. Argumentlar paket ichida tekshiriladi:
  mos kelmagan yoki noma'lum chaqiruv bajarilmaydi, xato matni modelga
  qaytadi.
- `LLMResult.rounds` va `LLMResult.tool_calls`. Token va narx barcha
  raundlar yig'indisi.

## 0.2.0 — 2026-09-11

### O'zgardi
- `structured()` sxemani majburiy tool orqali emas, `output_config.format`
  (JSON outputs) orqali yuboradi. Sxema SDK'ning `transform_schema` idan
  o'tadi: har obyekt yopiq (`additionalProperties: false`), API qabul
  qilmaydigan cheklovlar (uzunlik, son oralig'i, ro'yxat hajmi) maydon
  tavsifiga ko'chadi va pydantic ularni javob kelgach tekshiradi.
- Sxemaga tushmagan javob logi `llm_answer_refused` o'rniga
  `llm_answer_invalid` deb yoziladi. Satrda endi `stop_reason`, content
  bloklarining turlari, yuqori darajadagi kalitlar va `output_tokens` bor.
- `anthropic>=0.122` — `output_config` shu versiyada tekshirilgan.

### Qo'shildi
- `ClaudeRefused` — `stop_reason == "refusal"`. Log: `llm_answer_refusal`.
  Qayta so'ralmaydi.
- `Spend` va `LLMError.spent` — yiqilgan chaqiruv qancha token va pul
  sarflagani.

### Olib tashlandi
- `TOOL_NAME` konstantasi.

## 0.1.0 — 2026-08-16

Birinchi versiya — skelet. Ishlaydigan kod hali yo'q.

### Qo'shildi
- Paket tuzilmasi va bog'liqlik chegarasi: anthropic SDK + pydantic
- `errors` — xato ierarxiyasi
