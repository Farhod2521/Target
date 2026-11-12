# Ulanish uzilgan: eski ma'lumotni «jonli» deb ko'rsatmaslik

Backend o'zgardi (2026-11-12, branch `fix/connection-honest`, migratsiya yo'q).
Bu hujjat frontend uchun: nima keladi va qayerda nimani o'zgartirish kerak.

## Muammo nima edi

Meta (yoki Google) ulanishi ishlamay qolsa, backend u akkauntni o'qiy olmaydi.
Kampaniyalar esa oxirgi o'qilgan holatda qolardi: «Ishlayapti», byudjet,
sarf. Mijoz ekranga qarab reklama ishlayapti deb o'ylardi, aslida holat
noma'lum edi.

Productionda o'lchangan (2026-11-12): 30 ta akkauntda 166 ta kampaniya uzilgan
ulanish ortida «Ishlayapti» deb turgan, eng eskisi 17-sentabrdan beri
o'qilmagan.

## Backend endi nima qiladi

1. Reklama ro'yxati va dashboard javobida ulanish uzilgani **alohida blok**
   bilan aytiladi: qaysi tarmoq, nega, qachondan, oxirgi o'qish qachon bo'lgan.
2. Uzilgan ulanish ortidagi har bir kampaniya qatorida `frozenSince` keladi:
   qatordagi hamma narsa shu vaqtdagi holat.
3. Qatorlarning o'zi **o'zgartirilmaydi**: `status`, byudjet va raqamlar oxirgi
   o'qilgandek qoladi. Ularni «noma'lum» qilib ko'rsatish frontendning ishi
   (pastda).
4. Ulanish qayta ishlasa (mijoz qayta ulasa yoki Meta tokenni yana tan olsa),
   blok va belgilar o'zi yo'qoladi.

## 1. Reklama ro'yxati: `GET /api/v1/campaigns` (v2 ham shu maydonlarni beradi)

### Yangi blok `disconnected`

Ulanish ishlasa `null`. Uzilgan bo'lsa:

```json
"disconnected": {
  "network": { "id": "meta", "letter": "M", "name": "Meta" },
  "status": "invalid",
  "code": "190",
  "lostAt": "2026-11-11T17:40:02+00:00",
  "lastSyncedAt": "2026-11-11T17:34:30+00:00"
}
```

| Maydon | Tur | Ma'nosi |
|---|---|---|
| `network` | obyekt | Qaysi tarmoq ulanishi uzilgan |
| `status` | `"invalid" \| "revoked" \| "expired"` | Pastdagi jadvalga qarang |
| `code` | `string \| null` | Tarmoqning o'z xato kodi (masalan `190`). Mijozga ko'rsatilmaydi |
| `lostAt` | `string \| null` (ISO) | Qachon uzilgani. Eski uzilishlarda `null` bo'lishi mumkin |
| `lastSyncedAt` | `string \| null` (ISO) | Akkauntlar oxirgi marta qachon o'qilgan |

`status` qiymatlari va tavsiya etilgan matn:

| `status` | Sababi | Mijozga matn |
|---|---|---|
| `revoked` | Mijoz o'zi uzgan yoki Facebook'da ilovani o'chirgan | «Meta ulanishi uzilgan.» |
| `expired` | Kirish muddati tugagan | «Meta'ga kirish muddati tugadi.» |
| `invalid` | Meta tokenni rad etyapti (parol o'zgargan, xavfsizlik tekshiruvi) | «Meta ulanishi ishlamayapti.» |

Har uchala holatda bitta amal: **«Qayta ulash»** tugmasi (mavjud ulanish
oqimi).

### Qatordagi yangi maydon `frozenSince`

| Qiymat | Ma'nosi |
|---|---|
| `null` | Qator o'qilyapti, hammasi odatdagidek |
| ISO vaqt | Qator uzilgan ulanish ortida; hamma narsa shu vaqtdagi holat |
| `""` (bo'sh) | Uzilgan ulanish ortida va hech qachon o'qilmagan |

### Hisoblagich `counts.frozen`

`counts.running` ichidan nechtasi uzilgan ulanish ortida ekanini aytadi.
`counts.running` o'zi o'zgarmagan (eski frontend buzilmasligi uchun).

## 2. Dashboard: `GET /api/v1/metrics/numbers`

Yangi maydon `disconnected` (bu javobda nomlar snake_case):

```json
"disconnected": {
  "provider": "meta",
  "status": "invalid",
  "code": "190",
  "lost_at": "2026-11-11T17:40:02Z",
  "last_synced_at": "2026-11-11T17:34:30Z"
}
```

Ulanish ishlasa `null`.

## Frontendda nima qilish kerak

### Reklama ro'yxati

1. `disconnected != null` bo'lsa, ro'yxat tepasida doimiy ogohlantirish:
   - sarlavha: yuqoridagi jadvaldagi matn;
   - ikkinchi qator: «Ko'rsatilgan ma'lumot {lastSyncedAt} holatiga. Reklama
     hozir ishlayaptimi — noma'lum.»;
   - tugma: «Qayta ulash».
2. `frozenSince != null` bo'lgan qatorda:
   - holat nishoni o'rniga kulrang **«Holati noma'lum»**, tagida
     «{frozenSince} holatiga: {status matni}»;
   - yoqish/o'chirish, byudjet va tahrir tugmalari o'chiriladi (backend baribir
     rad etadi);
   - raqamlar qoladi, lekin xiraroq.
3. «Ishlayapti: N» hisoblagichi: `counts.running - counts.frozen` ko'rsatilsin;
   `counts.frozen > 0` bo'lsa yonida «+ {frozen} ta noma'lum».
4. `state == "not_connected"` va qatorlar bor bo'lsa, qatorlarni yashirmang:
   mijoz nima borligini ko'rsin, faqat jonli emasligi aytilsin.

### Dashboard

`disconnected != null` bo'lsa, tepada bitta qator: «Meta ulanishi uzilgan.
Raqamlar {last_synced_at} gacha.» va «Qayta ulash» tugmasi. Tanlangan davr
`last_synced_at` dan keyingi kunlarni o'z ichiga olsa, o'sha kunlar bo'sh
bo'ladi — bu nol sarf emas, o'qilmagan kunlar.

## Tekshirish

Backend testlari: `tests/pg/test_connection_frozen.py`.

Qo'lda: staging bazada bitta ulanishni `status = 'invalid'` qilib, ro'yxat va
dashboardni oching; `status = 'active'` ga qaytarilsa, blok va belgilar
yo'qolishi kerak.

## Hali qilinmagan

- Telegram kunlik hisobot va AI chat uzilgan ulanish ortidagi kampaniyalarni
  hali «ishlayapti» deb o'qishi mumkin.
- Uzilganda Meta tomonda reklama to'xtatilmaydi (keyingi bosqichlarda
  ogohlantirish qo'shiladi).
