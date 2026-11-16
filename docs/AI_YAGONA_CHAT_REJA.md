# Yagona AI chat: reja (2026-11-11)

**Maqsad:** foydalanuvchi platformani bitta chat orqali boshqaradi.

- AI savolga javob beradi, muammoni tekshiradi va aniq yechim aytadi.
- Yechim topilmasa, Support'ga zayavka qoldiradi.
- Reklamani chatdan o'zgartiradi: pauza, byudjet va boshqalar.
- Matn va ovoz bilan ishlaydi.
- Reklama bo'limidagi tugmalar avvalgidek qoladi.

**Qoida:** mavjud API'lar o'zgarmaydi. Yangi chat alohida endpoint, alohida prompt va alohida jadvallar bilan quriladi. Eski `/api/v1/chat` va `/api/v1/support` 6-bosqichgacha tegilmaydi.

Bu reja kodni tekshirib yozildi: backend `main` 70f7c92, frontend `main` 8047ad0. Kod hali yozilmagan.

---

## Boshlashdan oldin: tekshiruvda topilganlar

Bular eski chatdagi kamchiliklar. Eski chat tegilmaydi, lekin yangi chat bularni takrorlamasligi kerak.

### Prompt va kod mosligi (chat_answer v28)

1. Promptda 7 ta tool nomi yo'q: `daily_figures`, `lead_counts`, `lead_forms`, `recent_changes`, `agent_proposals`, `open_problems`, `audiences`. AI ularni faqat umumiy tavsifdan taxmin qiladi.
2. Kontekstda 5 ta bo'lim bor, lekin prompt ularni tushuntirmaydi: «Business», «Last 30 days», «Audiences», «Since the change», «The ad group it is about».
3. Promptda `%%SUPPORT%%` belgisi boshqa belgilar bilan birga kelmasligi kerak deyilgan. Kod buni tekshirmaydi.
4. `{{ language }}` o'rniga til nomi emas, kodi qo'yiladi (`uz`/`ru`/`en`).
5. Prompt 714 qator. Taxminan 55% faqat ba'zi savollarda kerak, ayrim qoidalar 6 martagacha takrorlangan.

### Ishlash

6. Prompt keshi standart holatda o'chiq (`ANTHROPIC_PROMPT_CACHE=false`, `app/common/env.py:165`). Prod `.env`'da yoqilganmi, bu tekshirilmagan.
7. Backend javobni bo'lak-bo'lak `html` qilib yuboradi. Kabinet bu maydonni o'qimaydi (`packages/api/src/live/bridges/chat.ts:183`), shuning uchun javob ekranga oxirida birdaniga chiqadi.
8. Jonli eval yo'q. `core/evals/cases/chat.json`da 6 ta holat bor, lekin ular haqiqiy modelga yuborilmaydi.

### Support

9. AI'ning Support'ga uzatishi doskada zayavka ochmaydi. `raise_ticket` faqat avtomatik trigger'lardan chaqiriladi, `TicketReason`da AI uchun sabab yo'q.
10. Mehmonga doskada kartochka ochib bo'lmaydi, chunki `board_cards.owner_id` bo'sh bo'lolmaydi.
11. Bilim bazasi (FAQ) yo'q. Bor narsalar: `tutorials` jadvali va koddagi `GUIDES` (`ads/selectors/failures.py`, `rejections.py`).

### Reklama o'zgarishlari

12. Chatdan faqat byudjet, pauza va yoqish mumkin. `actions` esa ko'proq turni qo'llaydi: EndTime, SpendCap, Rename, Audience, NewAdvert, NewGroup, NewAd, Copy, Delete, revert.
13. Chatdagi «Yoqish» Reklama ekranidagidan farq qiladi. Ekran `start_delivery` bilan ichidagi hali ishga tushmagan qismlarni ham yoqadi, chat esa faqat bitta `Resume` qiladi.
14. Chatda tasdiqlash bosilganda sahifa doirasi qayta tekshirilmaydi, bu faqat tayyorlashda tekshiriladi.
15. Chatdan qilingan o'zgarish jurnalda `user` deb yoziladi. Chat uchun alohida belgi yo'q.

### Ovoz

16. Ovozni matnga aylantirish uchun `packages/speechkit` (ElevenLabs `scribe_v2`) kodda bor, lekin hech qayerga ulanmagan. Mikrofon yozuvi faqat Support oynasida bor.

---

## 1-bosqich. AI chat + Support birlashadi, Support'ga zayavka tushadi

**Natija:** foydalanuvchi bitta chatga yozadi.

- AI reklama savoliga javob beradi.
- Muammo bo'lsa, AI tekshiradi: to'lov, tarif, blok, Facebook ulanishi, reklama hisobi, lidlar yetkazilishi, rad etilgan reklamalar. Keyin aniq yechim yozadi.
- Yechim topilmasa, «Mutaxassisga yuborish» tugmasini taklif qiladi.
- Foydalanuvchi bossa, Support doskasida zayavka ochiladi va Support Telegram'da xabar oladi.
- Support javobi o'sha chatning o'ziga keladi.

**Backend:**

1. **Endpoint.** Yangi `/api/v2/assistant`: sessiyalar, savol berish, oqim (stream), tugmalar, zayavka. Eski `/chat` bilan umumiy jadval ishlatilmaydi.
2. **Jadvallar.** Yangi `assistant_sessions` va `assistant_messages`. Bitta oqimda AI javobi va Support xodimining javobi turadi, xabar egasi `user`, `ai` yoki `staff` bo'ladi.
3. **Support javobi.** Support xodimi javob yozganda xabar mijozning Support chatiga saqlanadi va yangi chatga ham ko'rinadi. Ofis va Telegram oqimi o'zgarmaydi.
4. **Prompt.** Yangi `core/agent/prompts/assistant/v1.md`, taxminan 250 qator.
   - Doim yuboriladigan asosiy qism keshlanadi.
   - Faqat kerakli bo'limlar kontekst bilan birga oxirida qo'shiladi.
   - Tool'larni qanday o'qish tushuntirmasi tool javobining ichida keladi.
   - v28'dagi takrorlar olib tashlanadi, hamma tool va kontekst bo'limlari nomi bilan yoziladi.
5. **Mavjud tool'lar.** 15 ta look-up o'zgarishsiz qayta ishlatiladi.
6. **Yangi tool'lar:**
   - `account_health`. Faqat o'qiydi, Meta'ga so'rov yubormaydi. Tekshiradi: tarif va to'lovlar, blok va uning sababi, Facebook ulanishi va ruxsatlar, reklama hisobi holati (saqlangan maydonlardan), lid yetkazish (jadval, Telegram), ochiq muammolar ro'yxati.
   - `help_search`. Bilim bazasidan qidiradi: yangi `help_articles` jadvali (muammo → qadamlar, uz/ru/en), `tutorials` va mavjud `GUIDES`.
   - `create_ticket`. Darhol yubormaydi, faqat tugma tayyorlaydi. Bosilganda `send_to_support(source=ai_chat)` va `raise_ticket(reason=ai, ref=ai:{message_id})` chaqiriladi. Tavsif ichida savol, AI tekshirgan narsalar va qisqa xulosa bo'ladi.
7. **Doska.** `TicketReason`ga `ai` sababi qo'shiladi va ofisda «AI chatdan» deb ko'rinadi.
8. **Mehmon.** Ism va telefon so'raladi, mehmon Support chati ochiladi (bor yo'l). Doskada kartochka ochilmaydi, qarang: savol B.
9. **Oqim.** Javob bo'lak-bo'lak (`delta`) keladi. Tugmalar holati alohida maydonda keladi.
10. **Limitlar.** Mavjud chat kvotasi qayta ishlatiladi. Zayavka uchun alohida limit bo'ladi.
11. **Eval.** Jonli eval yoziladi. Holatlar: to'lov o'tmagan, akkaunt bloklangan, Facebook uzilgan, reklama rad etilgan, lid kelmayapti, mavzudan tashqari savol, «operator kerak». Har bir prompt o'zgarishidan keyin ishga tushiriladi.

**Ofis:**

- `help_articles`ni tahrirlash sahifasi.
- Zayavkada «AI chatdan» belgisi.

**Frontend:**

- Kabinetda yangi chat sahifasi: bitta oqim, AI va Support javoblari birga.
- «Mutaxassisga yuborish» tugmasi va zayavka holati: yuborildi, ishlanmoqda, hal qilindi.
- Sayt vidjeti mehmon uchun shu yangi endpoint'ga o'tadi.

**Tayyor deb hisoblanadi, qachonki:**

- Eval holatlarining hammasi o'tadi.
- Zayavka doskada ochiladi va Telegram'ga xabar boradi.
- Support javobi yangi chatda ko'rinadi.
- Eski `/chat` va `/support` testlari o'zgarishsiz o'tadi.
- Brauzerda to'liq yo'l sinab ko'riladi.

---

## 2-bosqich. Reklama tahlilini tekshirish va Meta reklamasini chatdan boshqarish

**Natija:** Reklama ekranida tugma bilan qilinadigan har bir o'zgarishni chatda so'rab qilish mumkin. Har o'zgarish faqat tasdiqlash tugmasi bosilgandan keyin bajariladi. Bu bosqichda faqat Meta.

**Tahlil:**

1. Staging nusxasidagi haqiqiy akkauntlarda AI javoblari tekshiriladi. Raqamlar ekran va Ads Manager bilan solishtiriladi, xatolar tuzatiladi.
2. Shu tekshiruvlar evalga qo'shiladi.

**Boshqaruv:**

1. **Bitta yo'l.** Hamma o'zgarish Reklama ekrani ishlatadigan `actions.preview`/`actions.request` orqali o'tadi. Chat uchun alohida yozuv yo'li qilinmaydi.
2. **Yangi `propose_change` qamraydi:**
   - pauza;
   - yoqish (ekrandagidek `start_delivery` bilan);
   - kunlik byudjet;
   - tugash sanasi;
   - xarajat chegarasi;
   - nom o'zgartirish;
   - auditoriya;
   - reklamaga boshqa rasm, video yoki forma qo'yish;
   - yangi guruh va yangi reklama;
   - nusxa olish;
   - o'chirish;
   - oxirgi o'zgarishni bekor qilish.
3. **Tasdiqlashda** sahifa doirasi qayta tekshiriladi. Jurnalga `actor_type = chat` yoziladi.
4. **Holat.** Tugma o'zgarish holatini ko'rsatadi: bajarilmoqda, bajarildi yoki rad etildi va sababi. Mavjud `ActionLog` va `GET /campaigns/actions/{id}` ishlatiladi.
5. **Agent takliflari** (Amallar) chatda tugma bo'lib chiqadi. Mavjud `approve_suggestion` ishlatiladi.
6. **Cheklovlar.** Bitta javobda nechta o'zgarish bo'lishi mumkinligi va o'chirish uchun qo'shimcha tasdiq kerakmi, foydalanuvchi bilan kelishiladi (qarang: savol D).

**Frontend:** har o'zgarish turi uchun tasdiqlash kartochkasi. Unda «nima edi → nima bo'ladi» yoziladi.

**Tayyor deb hisoblanadi, qachonki:**

- Har o'zgarish turi `ads_dry_run` rejimida va bitta haqiqiy test akkauntida sinab ko'riladi.
- Reklama ekranidagi tugmalar va eski testlar o'zgarishsiz ishlaydi.

---

## 3-bosqich. Ovoz bilan yozish

**Natija:** foydalanuvchi ovoz yuboradi, u matnga aylanadi. Foydalanuvchi matnni ko'radi va tuzatishi mumkin, keyin xuddi yozilgan savoldek ishlaydi.

1. **Backend:** `POST /api/v2/assistant/voice`. Faylni tekshirish Support'dagi qoidalar bilan qilinadi (webm/ogg/m4a/mp3, 300 soniyagacha). Matnga aylantirish `speechkit` (ElevenLabs) orqali.
2. **O'zbek tili.** Avval o'zbekcha va aralash (uz/ru) ovozlarda sifat o'lchanadi. Yetarli bo'lmasa, boshqa xizmat tanlanadi (qarang: savol E).
3. **Frontend:** mikrofon tugmasi. Support oynasidagi yozuvchi qayta ishlatiladi.
4. **Xavfsizlik.** Ovozdan kelgan buyruq ham reklamani faqat tasdiqlash tugmasi bilan o'zgartiradi.
5. **Xarajat.** Bir daqiqa ovoz narxi hisoblanadi va kunlik limit qo'yiladi.

---

## 4-bosqich. Yangi kampaniyani chatdan yaratish va ishga tushirish

**Natija:** foydalanuvchi chatda «yangi reklama qilamiz» deydi. AI kerakli ma'lumotlarni so'raydi: maqsad, sahifa, byudjet, hudud, media. Keyin mavjud tayyorlash oqimi orqali qoralama tuzadi va «Ishga tushirish» tugmasini beradi.

1. Mavjud `creation.request_creation`, qoralamalar va media kutubxonasi qayta ishlatiladi. Yangi yaratish yo'li qilinmaydi.
2. Rasm va video chatga yuklanadi va kutubxonaga tushadi.
3. Rad etilgan ishga tushirishni AI tushuntiradi va tuzatishni taklif qiladi. Mavjud `refusal` yo'li ishlatiladi.

---

## 5-bosqich. AI o'zi xabar beradi

**Natija:** chat faqat javob bermaydi, muhim narsani o'zi aytadi.

- Kunlik qisqa holat.
- Muammo chiqqanda xabar: to'lov, rad etish, lid kelmay qolishi.
- Agent takliflari tugmalari bilan.
- Xohlagan foydalanuvchiga shu xabarlar Telegram'ga ham boradi.

Mavjud xabar manbalari ishlatiladi: `cached_inbox`, kunlik va haftalik hisobotlar, agent takliflari.

---

## 6-bosqich. Eski chat va Support'ni yangisiga o'tkazish

1. Kabinetdagi eski AI chat va «Yordam» oynasi yangi chatga yo'naltiriladi. Eski suhbatlar ko'chiriladi yoki faqat o'qish uchun qoladi (qarang: savol F).
2. Eski endpoint'lar bir muddat ishlab turadi, keyin o'chiriladi.
3. Telegram support bot yangi chatga ulanadi.

---

## 7-bosqich. Boshqa reklama tarmoqlari

Google Ads va ChatGPT Ads `adskit` port'lari orqali ulanadi. `actions` va look-up'lar tarmoq nomini oladi.

Hozir faqat Meta bilan ishlaydigan yo'llar avval port ortiga o'tkaziladi: rasm yoki video almashtirish, nusxa olish, yangi guruh va yangi reklama, lid formalar.

---

## Siz qaror qilishingiz kerak bo'lgan savollar

**A. Zayavka qachon ochilsin?**
- Tavsiya: faqat foydalanuvchi «Mutaxassisga yuborish» tugmasini bosganda.
- Muqobil: hozirgidek AI o'zi ochadi.

**B. Mehmon (login qilmagan) uchun doskada zayavka kerakmi?**
- Kerak bo'lsa, doskani o'zgartirish kerak: `owner_id` bo'sh bo'lishi mumkin bo'ladi.
- Tavsiya: hozircha yo'q. Mehmon mavjud mehmon chatiga tushadi.

**C. Bilim bazasini kim to'ldiradi?**
- Ofisda kim maqola yozadi va kim tasdiqlaydi.
- Birinchi 20–30 ta maqolani men Support tarixidan va koddagi yechimlardan tayyorlab beraymi?

**D. Chatdan o'chirish va bekor qilish:**
- Bitta javobda nechta o'zgarish bo'lsin? Hozir 2 ta.
- O'chirish uchun ikki marta tasdiq kerakmi?

**E. Ovozni matnga aylantirish xizmati:**
- ElevenLabs kalit va kod bor, lekin o'zbek tilida sifati tekshirilmagan.
- Boshqa xizmat (masalan, OpenAI) yangi kalit va to'lov talab qiladi.

**F. Eski suhbatlar** yangi chatga ko'chirilsinmi yoki faqat o'qish uchun qolsinmi?

**G. Yangi chatda CRM menejer ishlay oladimi?** Hozir menejer reklamani o'zgartira olmaydi.

---

## Ish tartibi

- Har bosqich avval backend, keyin frontend.
- Har bosqich alohida branch'da: `feat/assistant-<bosqich>` ikkala repoda.
- Bosqich oxirida eval, eski testlar va brauzerda sinov.
- Shulardan keyingina keyingi bosqichga o'tiladi.
