# FleetWatch — mijozga demo ssenariysi

To'rt xil odam tizimdan foydalanadi, va demo shu to'rttasining kunini ketma-ket
ko'rsatishi kerak. Har biri alohida ekran va alohida qurilma:

| # | Rol | Qurilma | Nimani ko'radi |
|---|-----|---------|----------------|
| 1 | **Dispetcher** | noutbuk, brauzer | reyslar, xarita, mashinalar — kunlik ish |
| 2 | **Haydovchi** | Android telefon | o'z reysi, yoqilg'i, xarajat, yo'l varaqasi |
| 3 | **Yuk mijozi** | ikkinchi telefon | yukim qayerda — Telegram xabari |
| 4 | **Avtopark egasi** | sizning telefoningiz | pul: yo'qotish, kechikish, ertalabki xulosa |

Tartib tasodifiy emas. Dispetcher ishni boshlaydi, haydovchi uni bajaradi,
mijoz natijani ko'radi, ega esa pulni sanaydi. Egadan boshlansa, raqamlar
qayerdan kelgani tushunarsiz qoladi.

---

## Kirish ma'lumotlari

**Panel:** https://fleet.eduly.uz · **API:** https://fleetapi.eduly.uz

| Rol | Login | Parol |
|-----|-------|-------|
| Avtopark egasi (admin) | `demo@silkroad.uz` | `DEMO_PASSWORD` |
| Dispetcher (manager) | `dispecher@silkroad.uz` | `DEMO_PASSWORD` |
| Haydovchi (mobil) | `haydovchi@silkroad.uz` | `DEMO_PASSWORD` |

Parol `DEMO_PASSWORD` muhit o'zgaruvchisidan olinadi — kodda ham, shu faylda
ham yozilmagan, chunki demo tashkiloti haqiqiy mijozlar bilan bitta bazada
turadi.

**Tashkilot:** Silk Road Logistics — 12 mashina, 12 haydovchi, 60 kunlik
reyslar tarixi, 30 kunlik GPS. Boshqa tenantlarga (jumladan Default Fleet'ga)
hech qanday skript tegmaydi.

---

## Yig'ilishdan oldin (30–40 daqiqa)

### 1. Ma'lumotlarni yangilash

```bash
export DEMO_PASSWORD='...'
./scripts/demo-setup.sh
```

Bu avtoparkni noldan qayta quradi — vaqt belgilari yangi bo'lishi uchun.
Ertalab seed qilib tushdan keyin ko'rsatsangiz, mashinalar olti soatdan beri
qimirlamagan bo'lib ko'rinadi, shuning uchun **yig'ilishdan 1 soat oldin**
ishga tushiring.

Skript oxirida Telegram havolalarini chop etadi. Ularni yo'qotmang.

### 2. Telegram havolalarini ochish

Skript chiqargan ro'yxatdan:

- **Avtopark egasi havolasi** (`Direktor — Sanjar Aliyev`) → **o'z
  telefoningizda** oching. Bot `/start` ga javob bersa, ulanish tayyor.
- **Bitta yuk mijozi havolasi** (masalan `TR-2026-0021`) → **ikkinchi
  telefonda** oching. Ikkinchi telefon bo'lmasa — Telegram Web'da ikkinchi
  akkaunt, yoki mijozning o'z telefonida (bu eng kuchli variant: yuk egasi
  o'zi ulanadi).

Tekshirish:

```bash
ssh root@139.59.132.176 "cd /root/fleet && docker compose -f docker-compose.prod.yml \
  --env-file .env.prod exec -T api python demo_fire.py status"
```

Ikkala qatorda ham `✓ ... faol` turishi kerak. `havola ochilmagan` bo'lsa —
Telegram buyruqlari jim qoladi va demo yarmi yo'qoladi.

### 3. Xaritani jonlantirish (ixtiyoriy, lekin kuchli ta'sir qiladi)

Noutbukdan serverga ulanib, demo davomida ishlab tursin:

```bash
ssh root@139.59.132.176 "cd /root/fleet && docker compose -f docker-compose.prod.yml \
  --env-file .env.prod exec -T api python simulate_live.py --compress 300"
```

Harakatdagi 3 ta mashina xaritada real vaqtda siljiydi, har biri **o'z
reysining yo'nalishi bo'ylab**. Ctrl-C bilan to'xtaydi. To'xtatilsa ham
pozitsiyalar joyida qoladi — hech narsa buzilmaydi.

### 4. Telefonni tayyorlash

- `FleetWatchDriver-release.apk` o'rnatilgan bo'lsin.
- **Oldindan kirib chiqing** — APK repodagi eski nusxa bo'lishi mumkin; agar
  login ishlamasa, buni mijoz oldida emas, uyda bilganingiz yaxshi.
- Telefonni Wi-Fi/mobil internetga ulang (ilova `fleetapi.eduly.uz` ga boradi).

### 5. Brauzerni tayyorlash

Uchta tab oching va oldindan kirib qo'ying (login ekrani demo vaqtini yeydi):

1. `fleet.eduly.uz/trips` — dispetcher (dispecher@silkroad.uz)
2. `fleet.eduly.uz/map` — xarita
3. `fleet.eduly.uz/leakage` — yo'qotishlar (admin bilan: demo@silkroad.uz)

---

## Demo ssenariysi (~18 daqiqa)

### 1-qism. Dispetcher — kunlik ish (5 daqiqa)

**Reyslar** (`/trips`) dan boshlang. Jadval ko'rinadi: 94 ta reys, 6 tasi
hozir jarayonda.

Aytadigan gap: *"Bu — dispetcherning ertalabki ekrani. Qaysi yuk qayerda,
qaysi biri kechikyapti, qancha pul keltiradi."*

Ko'rsatish kerak bo'lgan uch narsa:

1. **Kechikkan reys.** `TR-2026-00xx` — Yekaterinburgga ketayotgan reys
   jadvalidan ~11 soat orqada. Qizil/ogohlantirish belgisi bilan turadi.
   *"Buni dispetcher qidirmaydi — tizim o'zi ko'rsatadi."*
2. **Chegaradagi reys.** Statusi «Chegarada» — mashina Gishtko'prikda
   navbatda turibdi. **Chegara navbati** (`/queue`) bo'limiga o'ting.
3. **Xarita** (`/map`). Mashinalar jonli siljiyapti (agar 3-qadamni
   bajargan bo'lsangiz). Bitta mashinani bosing — kim haydayapti, qaysi
   yukda, qancha tezlikda.

### 2-qism. Yuk mijozi — «yukim qayerda?» (4 daqiqa)

**Bu demoning eng kuchli qismi. Shoshilmang.**

Reyslar ro'yxatidan jarayondagi reysni oching (mijoz havolasini ochgan
reysni — masalan `TR-2026-0021`). Pastroqda **«Yuk egasiga Telegram orqali
xabar»** kartochkasi bor. Unda allaqachon obuna turadi: ism, telefon,
«Faol» belgisi.

Aytadigan gap: *"Yuk egasi bizning tizimga kirmaydi, parol olmaydi, ilova
o'rnatmaydi. Dispetcher unga bitta havola yuboradi — tamom. Shundan keyin
yuk qayerga yetganini o'zi biladi va sizga qo'ng'iroq qilmaydi."*

Endi **ikkinchi telefonni mijozga ko'rsating** va reyslar ro'yxatiga qayting.
O'sha reysning yonidagi keyingi status tugmasini bosing (masalan
«Chegarada»).

**Bir necha soniyada ikkinchi telefonga Telegram xabari tushadi**: reys
raqami, yangi statusi, xaritadagi joyi.

Bu bitta harakat butun mahsulotni tushuntiradi: dispetcher bitta tugma bosdi
— mijoz xabardor bo'ldi. Qo'ng'iroq yo'q, «hozir haydovchiga aloqaga chiqaman»
yo'q.

> Agar tugmani ikkinchi marta bosish kerak bo'lsa (reysni faqat bir marta
> oldinga surish mumkin), xabarni qo'lda takrorlang:
> `demo_fire.py customer status TR-2026-0021 --status at_border`

Ertalabki xabarni ham ko'rsating:

```bash
... exec -T api python demo_fire.py customer daily
```

Har bir faol mijozga yukining joriy holati, joyi va tezligi tushadi.

### 3-qism. Haydovchi — telefondagi ilova (4 daqiqa)

Telefonni oling, ilovani oching (`haydovchi@silkroad.uz` bilan kirilgan).

- **Bosh sahifa** — bugungi reys, mashina, smena.
- **Reyslar** — haydovchiga biriktirilgan reyslar. Reysni ochib statusni
  o'zgartirish mumkin — **va bu ham mijozga Telegram xabarini yuboradi**,
  xuddi dispetcher bosgandek.
- **Yoqilg'i** — quyish yozuvi: litr, narx, kilometraj.
- **Xarajatlar** — yo'l xarajati + **chek rasmini suratga olish**. Bu haqiqiy
  og'riqli nuqta: haydovchining qo'lidagi cheklar oyning oxirida yo'qoladi.
- **Profil** → yo'l varaqasi (mamlakat bo'yicha xarajatlar).

Aytadigan gap: *"Haydovchi qog'oz to'ldirmaydi. Telefonda uch marta bosadi,
va buxgalteriyada hisobot o'zi yig'iladi."*

### 4-qism. Avtopark egasi — pul (5 daqiqa)

Endi `demo@silkroad.uz` (admin) bilan kiring va **Yo'qotishlar**
(`/leakage`) ni oching.

Bu sahifa demoning yakuni, chunki bu yerda **pul** ko'rinadi:

- ikkita mashina 45 L/100 km sarflaydi, avtopark o'rtachasi ~31 L/100 km —
  ortiqcha sarf so'mda hisoblangan;
- ruxsat etilmagan joylarda uzoq to'xtashlar (geozonadan tashqarida);
- uchta shubhali yoqilg'i quyish: haddan tashqari katta hajm, shishirilgan
  narx, imkonsiz sarf.

Aytadigan gap: *"Bu raqamlarni hech kim qo'lda topolmaydi. Oyiga bir necha
million so'm shu yerda oqib ketadi."*

So'ng **telefoningizni oling** va Telegram botni ko'rsating:

```bash
... exec -T api python demo_fire.py owner leakage
... exec -T api python demo_fire.py owner briefing
```

Telefoningizga ketma-ket tushadi:
- yo'qotish ogohlantirishlari (qaysi mashina, qancha pul, xaritada qayerda);
- ertalabki xulosa — kechagi kun raqamlarda, taxminan shunday:

```
⚠️ Ertalabki xulosa · 14.09.2026

🚚 Reyslar — kecha 3 ta yetkazildi, daromad 79 068 192 so'm.
   Hozir yo'lda 5 ta mashina bor.
🛣 Yo'l — kecha 2 124 km bosib o'tildi.
⛽ Yoqilg'i — 836 l quyildi, 11 868 983 so'm to'landi.
💵 Xarajat — haydovchilar kecha 10 710 133 so'm sarfladi.
⚠️ Diqqat — 1 ta ruxsatsiz to'xtash (2.2 soat bekor turish),
   5 ta hujjat/xizmat muddati o'tgan.
```

Bu raqamlar bir-biriga mos: daromad 79 mln, yoqilg'i + xarajat ~22 mln.
Mijoz kalkulyator olib tekshirsa ham hammasi joyida turadi — shuning uchun
raqamlarni ayting, yashirmang.

Aytadigan gap: *"Egasi panelga kirmasa ham bo'ladi. Ertalab choy ichayotganda
telefoniga kechagi kun tushadi. Muhim narsa bo'lsa — darhol xabar keladi."*

Oxirida **Sozlamalar → Telegram xabarnomalari** ni ochib ko'rsating: ikkita
chat ulangan — direktor hammasi, buxgalter faqat pulga oid xabarlar. Kimga
nima borishini o'zi sozlaydi.

---

## Agar nimadir ishlamasa

| Muammo | Nima qilish |
|--------|-------------|
| **Xaritada birorta mashina yo'q** | Sahifani yangilang (F5). Seed mashinalarni yangi ID bilan qayta yaratadi, ochiq tab esa eski ID'lardagi lokatsiya keshini ushlab qoladi (`staleTime: Infinity`) — natijada birlashtirish ishlamaydi va hamma marker filtrlanib ketadi |
| Telegram xabari kelmayapti | `demo_fire.py status` — havola ochilganmi? `faol` emas bo'lsa havolani qaytadan oching |
| Xaritada mashina qimirlamayapti | `simulate_live.py` ishlayaptimi? Ishlamasa ham pozitsiyalar to'g'ri — shunchaki statik |
| Mobil ilova kirmayapti | APK eski bo'lishi mumkin. Zaxira: brauzerdan `fleet.eduly.uz` ni telefonda oching |
| Reysni oldinga surib bo'lmadi | `demo_fire.py customer status <REF> --status <holat>` bilan xabarni qo'lda yuboring |
| Ma'lumot eskirgan ko'rinadi | `./scripts/demo-setup.sh` ni qayta ishga tushiring (2–3 daqiqa) |
| Panel sekin ochilyapti | Birinchi yuklanish sekin — shuning uchun tablarni **oldindan** oching |

**Redeploy'dan keyin:** demo skriptlari ishlab turgan konteynerga `docker cp`
bilan ko'chiriladi, image'ga kirmaydi. Konteyner qayta yaratilsa ular
yo'qoladi — `./scripts/demo-setup.sh` ni qayta ishga tushiring.

**Demo kuni frontend'ni yolg'iz deploy qilmang.** Prod'dagi frontend va backend
WebSocket autentifikatsiyasida `?token=` usulini ishlatadi. Repoda commit
qilinmagan holda yangi usul — `Sec-WebSocket-Protocol` subprotocol'i — yozilgan,
va u faqat yangi backend bilan ishlaydi. Faqat frontend deploy qilinsa, WS
403 qaytaradi va xarita jonli yangilanishdan to'xtaydi. Ikkalasi birga
chiqarilishi shart.

---

## Buyruqlar shpargalkasi

Serverda (qisqartirish uchun alias qilib oling):

```bash
alias fw='ssh root@139.59.132.176 "cd /root/fleet && docker compose \
  -f docker-compose.prod.yml --env-file .env.prod exec -T api python"'
```

| Buyruq | Nima qiladi |
|--------|-------------|
| `fw demo_fire.py status` | Nima ulangan — yig'ilishdan oldin tekshiring |
| `fw demo_fire.py owner briefing` | Egaga ertalabki xulosa |
| `fw demo_fire.py owner leakage` | Egaga yo'qotish ogohlantirishlari |
| `fw demo_fire.py owner trips` | Egaga kechikkan reyslar |
| `fw demo_fire.py owner expiry` | Egaga hujjat/texko'rik muddatlari |
| `fw demo_fire.py owner cash` | Egaga kassa nomuvofiqligi |
| `fw demo_fire.py owner all` | Hammasi ketma-ket |
| `fw demo_fire.py customer daily` | Yuk egalariga ertalabki xabar |
| `fw demo_fire.py customer status TR-2026-0021 --status at_border` | Bitta reys holati |
| `fw simulate_live.py --compress 300` | Xaritani jonlantirish |

Har bir buyruq **haqiqiy** xabar yuboradi — hech narsa oldindan yozilgan
emas. Shuning uchun mijoz telefoningizni olib ko'rsa ham hammasi joyida.

---

## Nima qayerdan keladi

| Skript | Vazifasi |
|--------|----------|
| `backend/seed_demo_uz.py` | Avtopark, haydovchilar, GPS, yoqilg'i, texnik xizmat, reyslar, xarajatlar |
| `backend/seed_demo_driver.py` | Mobil ilova uchun haydovchi login |
| `backend/seed_demo_telegram.py` | Yuk egasi obunalari + avtopark egasi chatlari |
| `backend/demo_fire.py` | Xabarlarni qo'lda yuborish (prezentatsiya pulti) |
| `backend/simulate_live.py` | Xaritadagi harakat |
| `backend/demo_data_uz.py` | Ismlar, raqamlar, yo'nalishlar, narxlar — tahrirlash shu yerda |
| `scripts/demo-setup.sh` | Yuqoridagilarni to'g'ri tartibda ishga tushiradi |

Raqamlarni o'zgartirish kerak bo'lsa (masalan mijoz o'z shahrini so'rasa) —
`demo_data_uz.py` ni tahrirlang va `demo-setup.sh` ni qayta ishga tushiring.
Generatsiya kodiga tegish shart emas.
