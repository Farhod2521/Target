# telegramkit — o'zgarishlar tarixi

Semantik versiyalash. Telegram Bot API'ning versiyasi yo'q — u
o'zgarganda eski metodlar ishlashda davom etadi, shuning uchun
`client.py` da qadab qo'yiladigan versiya konstantasi ham yo'q.

## 0.9.0 — 2026-10-21

### O'zgardi
- Umumiy qatordagi tugmalar 8 tadan oshsa (`ROW_MAX_BUTTONS`), keyingi
  qatorga o'tkaziladi. Telegram bir qatorda 8 tadan ko'pini chizmaydi —
  ilgari bunday klaviatura rad etilardi, endi 0–10 shkalasi 8+3 bo'lib
  chiqadi. 8 tagacha bo'lgan klaviaturalar o'zgarmaydi.

## 0.8.0 — 2026-10-12

### Qo'shildi
- `Button.style` — tugma rangi: `"success"` (yashil), `"danger"` (qizil),
  `"primary"` (ko'k). Telegram 2026-yil fevraldan keyingi ilovalarda
  chizadi, eskilari maydonni e'tiborsiz qoldiradi. Berilmasa payload
  o'zgarmaydi.

## 0.7.0 — 2026-09-30

### Qo'shildi
- `OtherMessage` — so'zsiz xabar: rasm, ovoz, stiker, joylashuv.
  `read_update()` uni buyruq va matndan keyin qaytaradi. Ichidagi narsa
  olib yurilmaydi — paket rasmni ham, ovozni ham o'qiy olmaydi. Faqat
  kim, qayerda (`chat_type`) va qaysi xabar: chaqiruvchi javob bera
  olishi uchun. Rasm ostidagi izoh savol sifatida o'qilmaydi — so'zlar
  odatda rasm haqida bo'ladi.

## 0.6.0 — 2026-09-12

Bot endi suhbatlasha oladi. Paket buni bilmaydi — u faqat matnli
xabarni o'qiy oladigan bo'ldi va javob yozilayotganini ko'rsatadigan
usul qo'shildi. Nima deb javob berish mahsulotning ishi.

### Qo'shildi
- `TextMessage` — buyruq bo'lmagan matnli xabar. `read_update()` uni
  buyruqdan keyin qaytaradi, chunki buyruq ham matnli xabar.
  `message_id` olib yuriladi: javob model yozib bo'lgach keladi va
  oradan bir necha xabar o'tgan bo'lishi mumkin. `chat_type` ham
  olib yuriladi («private», «group», …) — lekin unga qarab qaror
  qabul qilinmaydi: har xabarga javob beradigan bot shaxsiy suhbatda
  to'g'ri, guruhda esa o'chirib tashlanadigan bot. Maydon yo'q bo'lsa
  bo'sh satr, ya'ni chaqiruvchi uni rad etadi.
- `BotClient.send_chat_action()` — «yozmoqda…». Xatosi yutiladi:
  bu kelayotgan xabar haqidagi ishora, va ishorani yo'qotish xabarni
  yo'qotishga aylanmasligi kerak.
- `send_message(reply_to=...)` — javob qaysi savolga ekanini ko'rsatadi.
  `allow_sending_without_reply` bilan: o'chirilgan savol javobni emas,
  faqat iqtibosni yo'qotadi.

Matnsiz xabar (rasm, ovoz, joylashuv, stiker) hamon `None`. Ularning
har biri alohida mahsulot qarori — paket taxmin qilmaydi.

## 0.5.1 — 2026-09-09

Uzunlik chegarasi HTML'ni bilmasdi. `_fits()` matnni 4096-belgida
shunchaki kesardi, `send_message` esa har doim `parse_mode="HTML"`
yuboradi — kesim `<a href="...">` ning o'rtasiga yoki ochiq `<b>` dan
keyin tushsa, Telegram butun xabarni rad etadi. Ya'ni qisqartirish
aynan o'zi oldini olish uchun yozilgan natijani berardi.

### Tuzatildi
- Kesim endi teg tashqarisidagi chegarada olinadi, ochiq qolgan teglar
  esa yopiladi. Teg nomlari kuzatiladi, qavslar sanalmaydi — chaqiruvchi
  yangi teg qo'shsa ham shu qoida amal qiladi.
- Chegara endi Telegram sanaydigan birlikda — UTF-16 code unit —
  o'lchanadi. Emoji Python uchun bitta belgi, API uchun ikkita: 3000 ta
  emoji `len` bo'yicha chegara ichida, Telegram bo'yicha tashqarisida
  edi.

### O'zgarmadi
- Chegaraga yetmagan xabar avvalgidek daxlsiz qaytadi, va bu holat
  mahsulotdagi deyarli hamma xabar uchun to'g'ri.

## 0.5.0 — 2026-09-07

«/start bosdim, hech narsa kelmadi» — bu nosozlikning bizda **hech
qanday izi qolmaydi**. Update umuman yetib kelmagan bo'lsa, log qatori
ham, jadvalda satr ham yo'q. Javobni faqat Telegram biladi, va uni
so'raydigan metod yo'q edi.

### Qo'shildi
- `BotClient.get_webhook_info()` — yettinchi va oxirgi metod. Hech bir
  mahsulot funksiyasi uni chaqirmaydi; u faqat odam o'qishi uchun.
- `WebhookInfo` DTO, besh maydon. «Hech narsa kelmayapti» ning to'rtta
  sababi — webhook yo'q, boshqa manzilda, bizniki rad etyapti, bizniki
  qabul qilyapti-yu worker turibdi — shu beshtada ajraladi.

### Eslatma
- Telegram ro'yxatdan o'tgan `secret_token` ni **hech qachon
  qaytarmaydi**. `setWebhook` dan keyin o'zgargan secret faqat
  `last_error_message` dagi 403 sifatida ko'rinadi — shuning uchun bu
  maydon boolean'ga siqilmay, o'zi qanday kelgan bo'lsa shunday
  olib yuriladi.
- `last_error_date` Unix sekundida qoladi. Paket soat o'qimaydi va
  zonaga egalik qilmaydi — buni chop etadigan chaqiruvchi biladi.

## 0.4.0 — 2026-08-27

Prod javob berdi. `miniapp_proof_accepted` qatoridagi `signed_keys`:
`auth_date,query_id,signature,user` — ya'ni haqiqiy klientning HMAC'i
`signature` ni **qamraydi**. 0.3.0 dagi ikkinchi o'qish savol edi,
savolning javobi bor.

### O'chirildi
- `LEGACY_UNSIGNED`, `SIGNATURE_FIELD`, `UNSIGNED` va ikkinchi urinishni
  bajaradigan ichki `_matching()`. Bitta o'qish qoldi: digest `hash` dan
  boshqa hamma kelgan maydonni qamraydi.
- `build_init_data(..., unsigned=...)` — u faqat ikkinchi o'qishni
  qurish uchun bor edi.

### Buzuvchi o'zgarish
- Eski usulda (`signature` digestdan tashqarida) imzolangan payload endi
  `InitDataError("bad-signature")` bilan rad etiladi.
- Yuqoridagi uchta konstanta `webapp` modulining API'sidan ketdi.
  `telegramkit` paketining o'zidan hech qachon eksport qilinmagan edi.

### O'zgarmadi
- `signed_keys` qoladi. Endi «qaysi o'qish» emas, «digest nimani
  qamradi» degan savolga javob beradi: Telegram yangi maydon qo'shsa, u
  avval shu log qatorida ko'rinadi.
- Muzlatilgan test vektori va `aiogram` algoritmining mustaqil
  ko'chirmasi qoladi — ular `build_init_data` dan mustaqil qulf, va
  aynan ularsizlik 0.3.0 dagi xatoni testdan o'tkazib yuborgan edi.

## 0.3.0 — 2026-08-27

`initData` tekshiruvi prodda **har urinishda** yiqilardi. Ikkita
chetlanish, ikkalasi ham hujjatdan mustaqil o'ylab topilgan va
ikkalasi ham noto'g'ri chiqqan.

### Tuzatildi
- **`signature` maydoni endi digest ostida.** Hujjatning «except hash
  and signature» iborasi Ed25519 protsedurasiga tegishli — u boshqa
  check-string, `bot_id:WebAppData` prefiksi bilan. HMAC bo'limi esa
  «all received fields» deydi va faqat `hash` ni chiqaradi
  (`aiogram.utils.web_app.check_webapp_signature` ham shunday). Zamonaviy
  klientlar `signature` yuboradi, ya'ni eski o'qish **har bir haqiqiy
  payload'ni** rad etardi.
- **`+` endi probel deb o'qiladi.** `parse_qsl` (va JS'dagi
  `URLSearchParams`) shunday qiladi; qo'lda yozilgan `unquote` esa
  `+` ni saqlardi va ichida `+` bo'lgan har qanday payload uchun
  Telegram bilan boshqa check-string qurardi.
- `keep_blank_values=True`: `start_param=` tushib qolmaydi. Bu yerda
  `URLSearchParams` semantikasi olinadi — payload'ni qurgan narsa
  brauzer, `aiogram` esa bu bitta nuqtada boshqacha.

### Qo'shildi
- `VerifiedInitData` — `parse_init_data()` endi `Sender` emas, shuni
  qaytaradi. `signed_keys` digest nimani qamraganini aytadi.
- `InitDataError.reason` (barqaror slug) va `.keys` (kelgan maydon
  **nomlari**, qiymatlari emas). `InitDataExpired.age_seconds`.
  Foydalanuvchi baribir bitta jumla ko'radi; bular log uchun.
- `LEGACY_UNSIGNED` — hujjat ikki xil o'qilgani uchun eski variant
  ikkinchi urinish sifatida qoldirildi va qaysi biri mos kelgani
  `signed_keys` da qaytariladi. **Prod javob bergach o'chiriladi**
  (0.4.0 da o'chirildi).
- `build_init_data(..., unsigned=...)` — test ikkinchi o'qishni
  ataylab qura olsin.

### Buzuvchi o'zgarish
- `parse_init_data()` qaytaradigan tur o'zgardi (`Sender` →
  `VerifiedInitData`). Yagona chaqiruvchi — `apps/miniapp`.

## 0.2.0 — 2026-08-26

Mini App (B6.2).

### Qo'shildi
- `webapp` — `parse_init_data()`: Telegram Mini App'ning `initData`
  imzosini tekshiradi (`secret = HMAC("WebAppData", bot_token)`),
  `Sender` qaytaradi. Sof funksiya: soat ham, konfiguratsiya ham
  argument. `build_init_data()` testlar uchun.
- `webapp` — `InitDataError` (imzogacha bo'lgan hamma tekshiruv) va
  `InitDataExpired` (imzo to'g'ri, `auth_date` eski). Chegara —
  imzoning o'zi: undan oldingi xato nomlanmaydi, keyingisi
  nomlanadi.
- `Button` — `web_app` maydoni. Tugma yo javob qaytaradi
  (`callback_data`), yo sahifa ochadi (`web_app`); ikkalasi ham yoki
  hech qaysisi bo'lmasa payload qurilganda rad etiladi.

### O'zgardi
- `_keyboard()` endi bir qator emas: javob tugmalari bitta qatorda,
  sahifa ochadigan har tugma o'z qatorida. Sabab — yonma-yon turgan
  ikki tugma tanlov bo'lib o'qiladi, havola esa tanlov emas.

## 0.1.0 — 2026-08-26

Birinchi reliz (B6.1).

### Qo'shildi
- `BotClient` — `send_message`, `edit_message_text`,
  `answer_callback_query`, `set_webhook`, `get_me`.
- `errors` — `BotBlocked` (403), `ChatUnreachable` (400, chat yo'q),
  `TelegramRateLimited` (429, `retry_after`), `TelegramTemporaryError`
  (5xx va tarmoq), `TelegramAPIError` (qolgani).
- `updates` — `read_update()`, `secret_matches()`: kiruvchi `POST` ni
  o'qiydigan sof funksiyalar, `httpx` ham, request obyekti ham kerak emas.
- `models` — `Button` (`callback_data` uzunligi payload qurilganda
  tekshiriladi), `SentMessage`, `BotIdentity`.
