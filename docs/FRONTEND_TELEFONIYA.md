# Ofis telefoniyasi (UTeL): API va frontend qo'llanmasi

Backend: `feat/office-telephony` shoxi, migratsiyalar `0046`–`0049`. Avval backend deploy qilinadi.
OpenAPI'ni qayta generatsiya qiling: quyidagi barcha javoblarning sxemasi unda bor.

Sozlama **bitta**: Sotuv va Support doskalari bitta UTeL ulanishidan foydalanadi.
Ovoz bizning server orqali o'tmaydi: brauzer to'g'ridan-to'g'ri UTeL'ga ulanadi (WebRTC).

## 0. Nima quriladi

| # | Qism | Qayerda | Bo'lim |
|---|---|---|---|
| 1 | «Telefoniya» sozlama sahifasi | yangi sahifa, faqat superuser va Owner | 2 |
| 2 | Brauzer softfoni (JsSIP) | ofis qobig'ida, hamma sahifada | 3 |
| 3 | Kiruvchi qo'ng'iroq oynasi, «qo'ng'iroqda» holati | ofis qobig'ida | 4 |
| 4 | Kartada qo'ng'iroqlar ro'yxati va qo'ng'iroq tugmasi | `boards/CardPanel.tsx` | 5 |
| 5 | Qo'ng'iroqlar jurnali | yangi sahifa | 6 |

Hamma yo'l `/api/v2/office/telephony` ostida. Xato shakli odatdagidek:
`{"code": "...", "detail": "..."}`, `detail` o'zbekcha — foydalanuvchiga shundayligicha ko'rsating.

## 1. Kim nimani ko'radi

`GET /api/v2/office/me`:

| Shart | Nima ochiladi |
|---|---|
| `can.telephony: true` | Sozlama sahifasi (2-bo'lim). Boshqalarga bu yo'llar **404** |
| `boards` bo'sh emas | Softfon, jonli oyna, jurnal, kartadagi qo'ng'iroqlar |
| `boards` bo'sh | Telefoniyaning hech narsasi yo'q, yo'llar **404** |

Jurnalda va audioda: superuser, Owner va Sotuv rahbari hamma qo'ng'iroqni ko'radi. Qolgan
xodim o'zinikini va hech kim javob bermaganlarini ko'radi. Buni backend o'zi filtrlaydi.

## 2. Sozlama sahifasi

| Yo'l | Nima qiladi | Tana |
|---|---|---|
| `GET /` | Sahifa holati | — |
| `PUT /connection` | UTeL'ga kiradi, ichki nomerlarni o'qiydi, hodisalar manzilini o'rnatadi | `{"tenant", "email", "password"}` |
| `DELETE /connection` | Ulanish, nomerlar, biriktirishlar va qo'ng'iroqlar tarixini o'chiradi | — |
| `POST /sync` | Ichki nomerlarni UTeL'dan qayta o'qiydi | — |
| `POST /hook` | Hodisalar manzilini qayta o'rnatadi | — |
| `PATCH /extensions/{id}` | Nomerni xodimga beradi / oladi, brauzer telefonini yoqadi / o'chiradi | `{"user_id"?, "softphone"?}` |

**Oltitasi ham bir xil javob qaytaradi** — har amaldan keyin sahifani shu javob bilan yangilang.
`GET` dan boshqalari UTeL'ga murojaat qiladi: javob 1–15 soniya kutilishi mumkin, tugmani
kutish holatiga o'tkazing.

```json
{
  "connected": true,
  "connection": {
    "tenant": "utc181",
    "api_email": "api@firma.uz",
    "connected_at": "2026-11-12T09:00:00Z",
    "synced_at": "2026-11-12T09:00:01Z",
    "sip_domain": "utc181.utel.uz",
    "sip_socket": "wss://utc181.utel.uz:8089/ws",
    "hook_set_at": "2026-11-12T09:00:02Z",
    "last_event_at": null,
    "events_last_day": 0,
    "last_error": "",
    "route_url": "https://…/webhooks/utel/…/route"
  },
  "extensions": [
    {
      "id": "…", "number": "101", "title": "Operator 1",
      "user": {"id": "…", "name": "Ali Valiyev", "email": "ali@…"},
      "softphone": true, "is_gone": false, "sip_refused_at": null
    }
  ],
  "staff": [{"id": "…", "name": "Ali Valiyev", "email": "ali@…"}]
}
```

Ulanmagan: `connected: false`, `connection: null`, `extensions: []`, `staff` to'la.

| Maydon | Frontda |
|---|---|
| `connected` | `false`: faqat kirish formasi. `true`: holat kartasi va nomerlar jadvali |
| `hook_set_at` | `null`: sariq ogohlantirish «UTeL hodisa yubormayapti», `last_error` matni, «Qayta o'rnatish» (`POST /hook`) |
| `last_event_at`, `events_last_day` | «Oxirgi hodisa», «24 soatda N ta». `null`: «Hali hodisa kelmagan» |
| `synced_at` | «Nomerlar yangilangan», yonida «Yangilash» (`POST /sync`) |
| `route_url` | «Aqlli yo'naltirish manzili»: nusxalash tugmasi bilan. **Maxfiy**, faqat shu sahifada ko'rsating. Izoh: «UTeL kabinetida Aqlli yo'naltirish modulining tashqi manziliga qo'ying» |
| `extensions[].user` | `null`: «Biriktirilmagan». Tanlov `staff` dan |
| `extensions[].softphone` | Switch |
| `extensions[].is_gone` | `true`: qator xira, «UTeL'da yo'q», xodim tanlovi o'chiq |
| `extensions[].sip_refused_at` | `null` emas: qizil belgi «UTeL parolni rad etdi, telefon to'xtatilgan». Switch'ni qayta yoqish yoki «Yangilash» (parol o'zgargan bo'lsa) tozalaydi |

Qoidalar:
- `tenant`: `utc181`, `utc181.utel.uz`, `https://utc181.utel.uz/…` — hammasi qabul qilinadi.
- `password` saqlanmaydi. `autocomplete="off"`, javobdan keyin maydonni tozalang.
- Ulangan holatda formani qayta yuborish mumkin («Qayta kirish»). **Boshqa** `tenant` kiritilsa
  eski nomerlar, biriktirishlar va qo'ng'iroqlar tarixi o'chadi — tasdiq so'rang. «Uzish» ham shunday.
- `PATCH` da faqat yuborilgan maydon o'zgaradi; `{"user_id": null}` nomerni bo'shatadi.
- Bir xodimda bitta nomer: ikkinchisi berilsa avvalgisi o'zi bo'shaydi (javobda ko'rinadi).
- Nomerlar tartibi backenddan tayyor keladi, qayta saralamang.

## 3. Softfon

`npm i jssip` (3.13 sinalgan). Softfon ofis qobig'ida yashaydi, sahifa almashganda uzilmaydi.

### 3.1. Sozlamani olish

`GET /me` — har kirishda bir marta. Javobda `Cache-Control: no-store`.

```json
{
  "enabled": true,
  "reason": "", "reason_label": "",
  "extension": "101",
  "sip": {
    "socket": "wss://utc181.utel.uz:8089/ws",
    "domain": "utc181.utel.uz",
    "uri": "sip:101@utc181.utel.uz",
    "login": "101",
    "password": "…"
  },
  "rules": {
    "start_delay_max_seconds": 6,
    "retry_max": 3,
    "retry_base_seconds": 10,
    "retry_step_seconds": 8,
    "retry_jitter_seconds": 5,
    "never_retry_codes": [401, 403]
  }
}
```

| `enabled` | `reason` | Frontda |
|---|---|---|
| `true` | `""` | Softfonni ishga tushiring |
| `false` | `not_connected` | Softfon yo'q, hech narsa ko'rsatmang |
| `false` | `no_extension` | Softfon yo'q. Qo'ng'iroq tugmasi `tel:` havolasi bo'ladi |
| `false` | `softphone_off` | Xuddi shunday: `tel:` (xodim MicroSIP ishlatadi) |
| `false` | `sip_refused` | Softfon yo'q, bir marta `reason_label` ni ko'rsating |

`sip.password` faqat xotirada tursin: `localStorage`, log, Sentry'ga **yozilmaydi**.

### 3.2. Ulanish

```js
const ua = new JsSIP.UA({
  sockets: [new JsSIP.WebSocketInterface(sip.socket)],
  uri: sip.uri,
  authorization_user: sip.login,
  password: sip.password,
  register: true,
  session_timers: false,
});
// qo'ng'iroq: pcConfig: { rtcpMuxPolicy: 'require' }, mediaConstraints: { audio: true, video: false }
```

### 3.3. Qayta urinish qoidalari — majburiy

Noto'g'ri yoki shoshilinch urinishlar UTeL'da **butun ofis IP'sini 20–30 daqiqaga bloklaydi**:
hamma nomer, MicroSIP ham to'xtaydi. Shuning uchun qoidalarni o'zingiz tanlamang, `rules` dan oling:

1. Birinchi ulanishdan oldin `0 … start_delay_max_seconds` tasodifiy kuting.
2. Ro'yxatdan o'tish xato bersa, ko'pi bilan `retry_max` marta qayta urining. N-urinishdan oldin
   kutish: `retry_base_seconds + N × retry_step_seconds + tasodifiy(0 … retry_jitter_seconds)`.
3. Javob kodi `never_retry_codes` da bo'lsa (401, 403) — **umuman qayta urinmang**, 3.4 ga o'ting.
4. Softfon faqat **bitta tab'da** ishlaydi (`BroadcastChannel` yoki `navigator.locks` bilan). Ikkinchi
   tab ro'yxatdan o'tmaydi; qo'ng'iroq tugmasi bosilsa birinchi tab'ga xabar yuboradi.
5. Allaqachon ulangan softfonni qayta ishga tushirmang (hot reload, sahifa almashishi).
6. JsSIP'ning o'z avtomatik qayta ulanishini cheklang, u shu qoidalardan tashqariga chiqmasin.

### 3.4. UTeL parolni rad etsa

`POST /me/refused` (tanasiz). Javob — yana `GET /me` shakli:

| Javob | Frontda |
|---|---|
| `enabled: true` | Parol UTeL'da o'zgargan ekan: yangi `sip.password` bilan **bir marta** urining. Yana rad etilsa yana `POST /me/refused` |
| `enabled: false`, `reason: "sip_refused"` | To'xtang. `reason_label` ni ko'rsating. Rahbar sozlamada tuzatmaguncha `GET /me` ham shuni qaytaradi |

### 3.5. Qo'ng'iroq qilish

Mijoz raqami kartada tayyor formatda keladi (`client.phone`, `+998901234567`):

```js
ua.call(`sip:${phone}@${sip.domain}`, options);   // "+" bilan, aks holda UTeL 603 qaytaradi
```

Raqam `+` bilan boshlanmasa qo'ng'iroq tugmasini o'chiring. Softfon yo'q xodimda tugma
`<a href="tel:+998…">`.

### 3.6. Muhim holatlar

| Holat | Nima qilish kerak |
|---|---|
| Mikrofon ruxsati yo'q / band (`NotAllowedError`, `NotReadableError`) | Javob bermang va qo'ng'iroq qilmang; aniq xabar chiqaring. Mikrofonsiz javob berilsa mijoz xodimni eshitmaydi |
| Gaplashayotganda ikkinchi kiruvchi | `486 Busy` bilan rad eting; UTeL keyingi xodimga o'tkazadi |
| Chiquvchida `603 Rejected` | Raqam `+` siz yoki nomerga chiquvchi ruxsat yo'q: «UTeL chiquvchi qo'ng'iroqqa ruxsat bermadi, rahbarga ayting» |
| Ro'yxatdan o'tish o'zi uzildi | Shu nomer boshqa qurilmada (MicroSIP) ulangan. Qoidalar bo'yicha qayta urining, bo'lmasa xabar bering |
| Xodim mijozni eshitmaydi | `peerconnection` → `track` hodisasida oqimni `<audio autoplay>` ga ulang |
| REGISTER `Request Timeout` | Katta ehtimol bilan IP bloki. Urinishni to'xtating, «20–30 daqiqadan keyin» deb ayting |

Tugmalar: javob berish, rad etish, tugatish, ovozni o'chirish (`mute`), ushlab turish (`hold`),
raqam terish (`sendDTMF`), boshqa nomerga o'tkazish (`refer('sip:102@domain')`).
Konsolga yozing: `UA start`, `REGISTERED`, `INVITE keldi`, `chiquvchi → progress → javob / FAILED`.

## 4. Jonli holat

### 4.1. Socket

`wss://<api>/api/v2/office/telephony/ws?token=<access token>` — ofis qobig'ida bitta ulanish.
Token yaroqsiz yoki xodimda doska yo'q bo'lsa `1008` bilan yopiladi (qayta urinmang, tokenni yangilang).
Sahifa hech narsa yubormaydi. Uzilsa 3–5 soniyada qayta ulaning; ulanganda yana `snapshot` keladi.

| `type` | Tana | Ma'nosi |
|---|---|---|
| `snapshot` | `{calls: [...], busy: ["101"]}` | Ulanganda bir marta: hozirgi butun holat |
| `call.ringing` | `{call: {...}}` | Qo'ng'iroq jiringlayapti (yangi yoki boshqa nomerga o'tdi) |
| `call.talking` | `{call: {...}}` | Javob berildi |
| `call.ended` | `{call_id}` | Tugadi |

```json
{
  "call_id": "144753d0-…",
  "direction": "in", "direction_label": "Kiruvchi",
  "state": "ringing",
  "number": "+998901234567",
  "extension": "101",
  "staff": {"id": "…", "name": "Ali Valiyev", "email": "ali@…"},
  "started_at": "2026-11-12T09:00:00Z",
  "clients": [
    {"id": "…", "name": "Shop", "email": "…", "sales_card_id": "…", "support_card_id": null}
  ]
}
```

- Holatni `call_id` bo'yicha saqlang: bir qo'ng'iroq uchun `call.ringing` bir necha marta keladi.
- `extension` bo'sh yoki guruh nomeri (masalan `5200`) bo'lishi mumkin, shunda `staff: null`.
- `clients` bo'sh: notanish raqam. Bir nechta: bir raqam bir nechta mijozda.
- Socket ishlamasa: `GET /live` (`{calls, busy}`, snapshot bilan bir xil) ni 10 soniyada so'rang.

### 4.2. Kiruvchi qo'ng'iroq oynasi

| Hodisa | Oyna |
|---|---|
| `call.ringing`, `direction: "in"` | Hammada kichik oyna: raqam, mijoz nomi, «Kartani ochish» (`sales_card_id` / `support_card_id`, xodim ko'ra oladigan doskaniki) |
| Softfonga INVITE keldi | Shu xodimda **softfon oynasi** (javob / rad etish). U ustuvor: shu `call` uchun kichik oynani ko'rsatmang |
| `call.talking`, `staff` men emas | Kichik oynani yoping |
| `call.talking`, `staff` men | Mijoz kartasini oching |
| `call.ended` | Yoping |

Softfon INVITE'ini socket'dagi qo'ng'iroq bilan raqam bo'yicha bog'lang (INVITE'dagi `From` raqami
= `call.number`, oxirgi 9 raqamini solishtiring).

### 4.3. «Qo'ng'iroqda» holati

`busy` — hozir gaplashayotgan ichki nomerlar. Xodimlar ro'yxatida (`boards/{board}/staff`,
sozlama jadvali) shu nomerdagi xodim yonida «qo'ng'iroqda» belgisi. `call.talking` kelganda
`call.extension` ni qo'shing, `call.ended` da olib tashlang.

## 5. Kartada

`GET /cards/{id}` → yangi maydon `calls` (eng yangisi tepada, ko'pi bilan 50 ta). Mijozning Sotuv va
Support kartasida **bir xil** ro'yxat: qo'ng'iroqlar mijoz raqamiga bog'langan.

```json
{
  "id": "…",
  "direction": "in", "direction_label": "Kiruvchi",
  "answered": true,
  "number": "+998901234567",
  "started_at": "2026-11-12T09:00:00Z",
  "duration_seconds": 65, "talk_seconds": 60,
  "extension": "101",
  "staff": {"id": "…", "name": "Ali Valiyev", "email": "ali@…"},
  "has_recording": true
}
```

| Maydon | Frontda |
|---|---|
| `answered: false` | Qizil «Javobsiz» |
| `talk_seconds` | Suhbat vaqti `m:ss`. `duration_seconds` gudok bilan — ko'rsatish shart emas |
| `staff` | Kim gaplashgan. `null`: hech kim olmagan yoki nomer biriktirilmagan |
| `has_recording` | `true`: ▶ tugmasi (6.2) |

Kartada «📞 Qo'ng'iroq» tugmasi: `client.phone` ga (3.5).

**Javobsiz qo'ng'iroq.** Mijoz qo'ng'iroq qilib, hech kim olmasa, uning ochiq kartalarida:
- `history` ga `kind: "missed_call"`, `label: "Javobsiz qo'ng'iroq"`, `body`: raqam;
- kartaning `due_at` **hozirgi vaqtga** qo'yiladi (oldin muddat bo'lmasa yoki keyinroq bo'lsa).

Front uchun yangi ish yo'q: karta «muddati o'tgan» bo'lib ko'rinadi, filtrlar ishlaydi. Xodim qayta
qo'ng'iroq qilgach muddatni odatdagidek o'zi oladi yoki o'zgartiradi.

## 6. Jurnal

### 6.1. Ro'yxat

`GET /calls`

| Parametr | Qiymat | |
|---|---|---|
| `scope` | `all` (standart), `known`, `unknown` | `unknown`: bazada yo'q raqamlar |
| `direction` | `in`, `out` | |
| `answered` | `true`, `false` | `false`: javobsizlar |
| `mine` | `true` | Faqat mening qo'ng'iroqlarim |
| `q` | raqam bo'lagi | Faqat raqamlari olinadi: `90 123` ham ishlaydi |
| `limit`, `offset` | 1–100 (standart 50), 0… | |

Javob: `{"total": 123, "calls": [...]}`. Har element 5-bo'limdagi shakl **va** `clients`
(4.1 dagidek: `sales_card_id`, `support_card_id` bilan).

Taklif qilinadigan tablar: «Hammasi», «Javobsiz» (`answered=false`), «Notanish» (`scope=unknown`),
«Meniki» (`mine=true`). Qatorda: vaqt, yo'nalish, raqam, mijoz (kartaga havola), xodim, suhbat vaqti, ▶.
Notanish raqam qatorida karta ochilmaydi — faqat «Qo'ng'iroq qilish».

### 6.2. Audio

`GET /calls/{id}/recording` — `audio/wav`, **token bilan** (`Authorization` sarlavhasi). Shuning
uchun `<audio src>` ga to'g'ridan-to'g'ri qo'yib bo'lmaydi:

```js
const blob = await api.get(`/calls/${id}/recording`, { responseType: 'blob' });
audio.src = URL.createObjectURL(blob);   // yopilganda URL.revokeObjectURL
```

▶ bosilgandagina yuklang (fayl daqiqasiga ~1 MB). Blob bo'lgani uchun oldinga-orqaga surish ishlaydi.

## 7. Xatolar

| `code` | HTTP | Qachon | Frontda |
|---|---|---|---|
| `tenant_shape` | 422 | UTeL manzili noto'g'ri | `tenant` maydoni ostida |
| `exchange_refused_login` | 422 | UTeL login yoki parolni qabul qilmadi | `password` maydoni ostida |
| `exchange_unreachable` | 502 | UTeL javob bermadi | Toast, «Qayta urinish» |
| `exchange_session_ended` | 409 | UTeL saqlangan kalitni rad etdi (parol almashgan) | Kirish formasi: «Login va parolni qayta kiriting» |
| `not_connected` | 409 | Ulanish yo'q | `GET /` ni qayta o'qing |
| `extension_not_found` | 404 | Nomer o'chgan | `GET /` ni qayta o'qing |
| `extension_gone` | 409 | UTeL'da yo'q nomerni berishga urinish | Toast |
| `not_staff` | 422 | Tanlangan odam faol xodim emas | Toast |
| `call_not_found` | 404 | Qo'ng'iroq yo'q yoki bu xodimga ko'rinmaydi | Toast |
| `no_recording` | 404 | Yozuv yo'q yoki UTeL bermadi | «Yozuv topilmadi» |

## 8. Tekshirish ro'yxati

Sozlama
- [ ] `can.telephony: false` da menyu bandi yo'q
- [ ] Noto'g'ri parol: xato `password` ostida
- [ ] Xodimga ikkinchi nomer berilganda birinchisi «Biriktirilmagan» bo'ladi
- [ ] `is_gone` va `sip_refused_at` belgilari ko'rinadi
- [ ] `route_url` nusxalanadi, boshqa sahifada ko'rinmaydi

Softfon
- [ ] Ikki tab ochilganda faqat bittasi ro'yxatdan o'tadi
- [ ] 401/403 da qayta urinish yo'q, `POST /me/refused` ketadi
- [ ] Xato bo'lganda urinishlar soni `retry_max` dan oshmaydi (Network'da sanang)
- [ ] Mikrofon rad etilganda javob tugmasi ishlamaydi, xabar chiqadi
- [ ] Kiruvchi va chiquvchi qo'ng'iroqda ikki tomon bir-birini eshitadi
- [ ] Parol `localStorage` va loglarda yo'q

Jonli
- [ ] Kiruvchi qo'ng'iroqda oyna bir marta chiqadi (softfon + socket ikkita emas)
- [ ] Boshqa xodim javob berganda oyna yopiladi
- [ ] Socket uzilib qayta ulanganda eski qo'ng'iroqlar osilib qolmaydi

Karta va jurnal
- [ ] Qo'ng'iroq tugagach kartani qayta ochganda u `calls` da bor
- [ ] Javobsiz qo'ng'iroqdan keyin karta «muddati o'tgan» bo'ladi
- [ ] Audio ▶ bosilgandagina yuklanadi va o'ynaydi
- [ ] «Notanish» tabida mijozsiz raqamlar

## 9. Backend tomonda hali haqiqiy UTeL'da tekshirilmagan

Kod UTeL hujjati va boshqa loyihadagi ishlab turgan ulanish bo'yicha yozilgan, lekin bizning
tenantda hali sinalmagan. Sinovda farq chiqsa backend tuzatadi, API shakli o'zgarmaydi:

- qo'ng'iroq tarixidagi vaqt zonasi (Toshkent vaqti deb olingan);
- jonli hodisalardagi (`dial_started`, `dial_answered`) ichki nomer maydonlari;
- aqlli yo'naltirish so'rovining aniq shakli.
