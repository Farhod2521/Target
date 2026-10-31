# Reklama joylashuvi: frontend qo'llanma

Reklama yaratishda joy tanlash uchun. Faqat Meta draftlari uchun ishlaydi.
Google o'zgarmaydi: u `GET /launch/drafts/{id}/areas` dan foydalanadi.

Barcha yo'llar `/api/v1` ostida va odatdagi avtorizatsiya bilan chaqiriladi.

## Ikki rejim

| Rejim | Foydalanuvchi nima qiladi | Reklama kimga chiqadi |
|---|---|---|
| `list` | Shahar, viloyat yoki mamlakatni qidirib tanlaydi | Tanlangan joylarga. Ro'yxat bo'sh bo'lsa, biznes mamlakatiga |
| `map` | Xaritaga nuqta qo'yadi va radius belgilaydi | Nuqta atrofidagi doiraga |

Bir vaqtda bitta rejim ishlaydi. `map` rejimida `places` targetingga kirmaydi.

## Oqim

1. Tahrirlash oynasi ochilganda `GET /launch/drafts/{id}/edit` chaqiriladi, joy ma'lumoti `geo` da keladi.
2. `list` rejimida foydalanuvchi yozadi, `/locations` natijalari ko'rsatiladi.
3. Tanlangan natija `geo.places` ga qo'shiladi.
4. `map` rejimida xaritadan `lat`, `lng`, slayderdan `km` olinadi.
5. Saqlashda `PUT /launch/drafts/{id}/edit` ga butun forma yuboriladi.

## 1. Joy qidirish

```
GET /launch/drafts/{id}/locations?q=Tashkent&country=UZ
```

| Parametr | Ma'nosi |
|---|---|
| `q` | Qidiruv matni, ko'pi bilan 100 belgi. 2 belgidan qisqa bo'lsa `[]` qaytadi |
| `country` | Ixtiyoriy, ISO-2 kod. Shu mamlakat qatorlari birinchi turadi, boshqalari ham qoladi. Berilmasa, biznes mamlakati olinadi |

Javob:

```json
[
  {
    "id": "2420901",
    "name": "Tashkent",
    "type": "city",
    "context": "Toshkent Shahri, Uzbekistan",
    "countryCode": "UZ"
  }
]
```

- `type`: `city`, `region` yoki `country`.
- `context` ni nom yonida ko'rsating, u bir xil nomli joylarni ajratadi.
- Nomlar `ru` va `en` foydalanuvchilariga o'z tilida, `uz` foydalanuvchilariga inglizcha keladi.
- So'rovni yozish to'xtagach 300 ms kutib yuboring.

## 2. Joylarni o'qish va saqlash

`GET /launch/drafts/{id}/edit` javobidagi `geo`:

```json
{
  "mode": "map",
  "places": [{ "id": "2420901", "name": "Tashkent", "type": "city" }],
  "km": 12,
  "address": "Alexanderplatz, Berlin",
  "lat": 52.520008,
  "lng": 13.404954,
  "minKm": 1,
  "maxKm": 80,
  "placeLimit": 10
}
```

| Maydon | Qoida |
|---|---|
| `places` | Qidiruv qatorini `id` va `name` bilan o'zgartirmasdan yuboring. `area:` bilan boshlanadigan `id` ham o'zgarmaydi |
| `km` | `minKm` dan `maxKm` gacha. Maxsus kategoriyada `minKm` 24 bo'ladi, shuning uchun bu qiymatlarni kodda yozib qo'ymang |
| `lat`, `lng` | Ikkalasi birga yuboriladi. `null` bo'lishi mumkin, 0,0 atrofidagi nuqta qabul qilinmaydi |
| `address` | Ko'rsatish uchun matn, ko'pi bilan 300 belgi |
| `minKm`, `maxKm`, `placeLimit` | Faqat o'qish uchun, backend chegarasi |

Saqlash:

```
PUT /launch/drafts/{id}/edit
```

Tanasi: `GET /edit` dan olingan butun forma, o'zgargan `geo` bilan. Javob yangilangan draft bo'ladi.
Backend faqat o'zgargan qismni saqlaydi. Qamrov fonda qayta hisoblanadi.

`list` rejimida `places` bo'sh yuborilsa, reklama biznes mamlakatiga chiqadi.
Shuning uchun "butun O'zbekiston" matnini umumiy matnga almashtiring.

## Xatolar

| Status | Holat | Javob | Frontend nima qiladi |
|---|---|---|---|
| `422` | Qidiruv bermagan joy yoki joylar soni oshgan | `problems["audience.places"]` | Xabarni joylar ro'yxati ostida ko'rsatadi |
| `422` | Radius chegaradan tashqarida | `problems["geo.km"]` | Xabarni slayder ostida ko'rsatadi |
| `422` | Nuqta yo'q | `problems["audience.geo_mode"]` | Nuqta qo'yishni so'raydi |
| `400` | Reklama akkaunti ulanmagan | `code: "no_ad_account"` | `detail` ni ko'rsatadi |
| `400` | Meta ruxsati tugagan | `code: "connection_unusable"` | `detail` ni ko'rsatadi |
| `404` | Draft topilmadi, Google draft yoki taklif hali tayyor emas | `detail` | Joy bo'limini ko'rsatmaydi |
| `429` | Daqiqasiga 60 tadan ko'p qidiruv | `detail` | Birozdan keyin qayta so'raydi |
| `503` | Meta javob bermadi | `code: "place_search_failed"` | Qayta urinishni taklif qiladi |

Noto'g'ri `q` yoki `country` FastAPI'ning oddiy `422` javobini qaytaradi.

## Kodda nima o'zgaradi

**`packages/api/src/launch.ts`**

```ts
export interface Place {
  id: string;
  name: string;
  type: "city" | "region" | "country";
  context?: string;
  countryCode?: string;
}

geo: {
  mode: "list" | "map";
  places: Place[];
  km: number;
  address: string;
  lat: number | null;
  lng: number | null;
  minKm: number;
  maxKm: number;
  placeLimit: number;
};

export const usePlaces = (id: string, q: string, country = "") =>
  useQuery({
    queryKey: ["launch", id, "places", q, country],
    queryFn: () =>
      api.get<Place[]>(
        `${base(id)}/locations?q=${encodeURIComponent(q)}&country=${country}`,
      ),
    placeholderData: keepPreviousData,
  });
```

Eski `/launch/places` yo'li backendda yo'q. Uni `live/pending.ts` va mock handlerlardan ham almashtiring.

**`apps/cabinet/src/pages/launch/EditGeo.tsx`**

- `usePlaces` ga draft `id` sini bering va so'rovga 300 ms debounce qo'shing.
- `KM_MIN`, `KM_MAX` o'rniga `geo.minKm`, `geo.maxKm` ishlating.
- `geo.places` uzunligini `geo.placeLimit` bilan cheklang.
- Hozirgi SVG rasm o'rniga haqiqiy xarita qo'ying va nuqtani `geo.lat`, `geo.lng` ga yozing.
- "Joylashuvimni topish" tugmasi koordinatani `address` ga emas, `lat` va `lng` ga yozsin.
- `type` matnida `country` holatini qo'shing.

## Hozircha yo'q

- **Qamrov API:** `GET .../reach?km=` backendda yo'q. Radius ostidagi qamrov blokini yashirib turing.
- **Manzil yozib nuqta topish:** geocoder hali ulanmagan. Foydalanuvchi nuqtani xaritada o'zi qo'yadi.
- **Xarita sozlamasi API'si:** yo'q. OpenStreetMap ishlatilsa, `https://tile.openstreetmap.org/{z}/{x}/{y}.png` va OpenStreetMap attribution'i kerak.
- **Bir nechta nuqta:** bitta draftda bitta nuqta.

`geoSearch` flag'ini yuqoridagi o'zgarishlar va qamrov bloki hal bo'lgach yoqing.
