# Developer sahifasi: tizim xatolari (`/ofis/muhandis/`)

Backend: `fix/meta-error-tickets`. Front sahifasi (`apps/office/src/pages/dev/`) va
`packages/api/src/officeDev.ts` shartnomasi tayyor; endi ular haqiqiy backendga ulanadi.

Kim ko'radi: Engineer roli va superuser. Boshqalarga 404.

## Endpointlar (`/api/v1/office/faults`)

| Metod | Yo'l | Javob |
|---|---|---|
| GET | `/office/faults` | Ochiq xatolar, oxirgisi birinchi (200 tagacha): `FaultSummary[]` |
| GET | `/office/faults/{ref}` | Bitta xato 6 harfli havola bo'yicha (katta-kichik harf farqi yo'q), yopilgani ham: `FaultDetail` |
| POST | `/office/faults/{ref}/settle` | «Hal qilindi»: 204. Ro'yxatdan chiqadi |

`FaultSummary`: `ref`, `title` («Reklama yaratish — kutilmagan xato»), `state` (hozircha har doim `new`: kim ko'rayotgani yozilmaydi), `times`, `customers` (hozircha har doim 1: bir qator = bir mijoz), `customerName`, `lastAt`.

`FaultDetail` qo'shimcha: `settled`, `kind` (kod: `unknown`, `schema_error`, `unavailable`, `not_applied`, `stalled`, `not_launchable`), `customer` (`business` bo'sh), `screen` (kod joyi, masalan `ads.creation`), `url` (nima haqida: `launch:<id>` yoki `action:<id>`), `at`, `device` (bo'sh), `stack` («Xato: …» qatori, traceback, «Kontekst:» JSON), `shown` (bo'sh: mijoz ko'rgan matn saqlanmaydi, sahifa blokni yashiradi).

## Frontda qilingan (front `fix/developer-faults`)

- Karta: sarlavha, `Kod`, «Nima haqida» (launch → mijozning reklama sahifasiga havola, amal → qisqa id), «Kod joyi», birinchi/oxirgi vaqt; bo'sh `business`, `device`, `shown` ko'rsatilmaydi.
- Log bloki: «Xato:» qatori qizil, «Kontekst:» xira; uzun qatorlar blok ichida aylanadi, telefonda karta kengaymaydi.
- `/office/queues` backendda yo'q: o'qish qayta urinilmaydi, so'rov to'xtaydi, bo'lim chiqmaydi.
- `launch` bloki kelmaydi, chiqmaydi. Mock haqiqiy shaklga keltirildi.

## Telegram

Har bir yangi yoki takrorlangan tizim xatosi staff botda Engineer'larga boradi (bir xato soatiga bir marta): havola, kod, joy, mijoz, xato matni, «Developer sahifasida ochish» va launch bo'lsa «Reklama» havolasi. Yonida `xato_<REF>.txt` fayli (kontekst va traceback), trace yoqilgan bo'lsa launch trace fayli ham. Meta rad etgan launchlar endi Developerga bormaydi, ular Support kanbaniga tushadi.
