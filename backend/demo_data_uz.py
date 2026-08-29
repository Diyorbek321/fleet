"""Static data pools for the Uzbek demo tenant (see ``seed_demo_uz.py``).

Kept apart from the seeding logic so the numbers a presenter cares about —
plate numbers, driver names, corridors, fuel prices — can be edited without
touching the generation code.

Money is UZS throughout. Diesel is priced around 13 000–14 500 so'm/litre,
which is the range Uzbek fleets were paying at the time of writing; freight
rates are the going market rates for a 20 t tent/reefer semi.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Organization                                                                #
# --------------------------------------------------------------------------- #

ORG_NAME = "Silk Road Logistics"
ORG_CONTACT_NAME = "Sanjar Aliyev"
ORG_CONTACT_PHONE = "+998 90 123 45 67"
ORG_NOTES = "Demo tenant — prezentatsiya uchun generatsiya qilingan ma'lumot."

# No password here on purpose. The demo tenant lives on production alongside
# real customers, so its credential is a live one: committing it to the repo
# publishes a working login to anyone who reads the source. The seeder reads it
# from the DEMO_PASSWORD environment variable instead and refuses to run
# without it.
DEMO_USERS = [
    ("demo@silkroad.uz", "admin"),
    ("dispecher@silkroad.uz", "manager"),
]

# --------------------------------------------------------------------------- #
# Cities & corridors — real coordinates                                        #
# --------------------------------------------------------------------------- #

CITIES: dict[str, tuple[float, float]] = {
    "Toshkent": (41.2995, 69.2401),
    "Samarqand": (39.6270, 66.9750),
    "Buxoro": (39.7747, 64.4286),
    "Navoiy": (40.0844, 65.3792),
    "Qarshi": (38.8600, 65.7900),
    "Termiz": (37.2242, 67.2783),
    "Guliston": (40.4897, 68.7842),
    "Jizzax": (40.1158, 67.8422),
    "Urganch": (41.5500, 60.6333),
    "Nukus": (42.4531, 59.6103),
    "Andijon": (40.7821, 72.3442),
    "Farg'ona": (40.3842, 71.7843),
    "Namangan": (40.9983, 71.6726),
    "Shymkent (QZ)": (42.3417, 69.5901),
    "Olmaota (QZ)": (43.2220, 76.8512),
    "Aqto'be (QZ)": (50.2839, 57.1670),
    "Moskva (RF)": (55.7558, 37.6173),
    "Qozon (RF)": (55.7963, 49.1088),
    "Yekaterinburg (RF)": (56.8389, 60.6057),
    "Bishkek (QG)": (42.8746, 74.5698),
    "Dushanbe (TJ)": (38.5598, 68.7870),
}

# (origin, destination, distance_km, typical_rate_uzs, international)
CORRIDORS: list[tuple[str, str, float, int, bool]] = [
    ("Toshkent", "Samarqand", 310, 4_500_000, False),
    ("Toshkent", "Buxoro", 580, 7_800_000, False),
    ("Toshkent", "Urganch", 1_060, 14_500_000, False),
    ("Toshkent", "Nukus", 1_250, 17_000_000, False),
    ("Toshkent", "Andijon", 340, 4_800_000, False),
    ("Toshkent", "Termiz", 680, 9_600_000, False),
    ("Samarqand", "Buxoro", 270, 3_900_000, False),
    ("Buxoro", "Urganch", 480, 6_800_000, False),
    ("Namangan", "Toshkent", 300, 4_300_000, False),
    ("Qarshi", "Toshkent", 520, 7_200_000, False),
    ("Toshkent", "Shymkent (QZ)", 130, 3_200_000, True),
    ("Toshkent", "Olmaota (QZ)", 840, 13_500_000, True),
    ("Toshkent", "Moskva (RF)", 3_360, 62_000_000, True),
    ("Samarqand", "Moskva (RF)", 3_580, 66_000_000, True),
    ("Toshkent", "Qozon (RF)", 2_620, 48_000_000, True),
    ("Toshkent", "Yekaterinburg (RF)", 2_450, 44_000_000, True),
    ("Toshkent", "Bishkek (QG)", 620, 9_800_000, True),
    ("Toshkent", "Dushanbe (TJ)", 350, 6_400_000, True),
]

# Border crossings the international corridors pass through.
BORDER_POSTS: dict[str, tuple[float, float]] = {
    "Gishtko'prik (UZ–QZ)": (41.1900, 69.0600),
    "Yallama (UZ–QZ)": (40.9310, 68.6520),
    "Daut-ota (UZ–QZ)": (41.5100, 68.1900),
    "Oybek (UZ–TJ)": (40.2200, 69.4700),
}

# --------------------------------------------------------------------------- #
# Fleet                                                                        #
# --------------------------------------------------------------------------- #

# (name, plate, model, year, base_mileage_km)
TRUCKS: list[tuple[str, str, str, int, int]] = [
    ("Yo'lbars 01", "01 A 447 BC", "MAN TGX 18.440", 2021, 486_000),
    ("Yo'lbars 02", "01 A 512 CD", "Mercedes-Benz Actros 1841", 2022, 342_000),
    ("Yo'lbars 03", "01 B 108 EF", "Volvo FH 460", 2023, 218_000),
    ("Yo'lbars 04", "01 B 774 GH", "Scania R450", 2020, 612_000),
    ("Yo'lbars 05", "10 C 236 JK", "DAF XF 105.460", 2019, 748_000),
    ("Yo'lbars 06", "10 C 891 LM", "MAN TGX 18.480", 2022, 297_000),
    ("Chinor 07", "30 D 345 NP", "Shacman X3000", 2023, 164_000),
    ("Chinor 08", "30 D 620 QR", "Howo TX 440", 2021, 389_000),
    ("Chinor 09", "40 E 173 ST", "Isuzu Forward FVR", 2022, 231_000),
    ("Chinor 10", "40 E 958 UV", "Kamaz 54901 NEO", 2023, 142_000),
    ("Zarafshon 11", "01 F 264 WX", "Volvo FH 500", 2020, 566_000),
    ("Zarafshon 12", "01 F 703 YZ", "Mercedes-Benz Actros 1845", 2024, 87_000),
]

# (name, phone, license, email)
DRIVERS: list[tuple[str, str, str, str]] = [
    ("Alisher Karimov", "+998 90 234 11 45", "AA 4471203", "a.karimov@silkroad.uz"),
    ("Sherzod Rahimov", "+998 91 556 20 18", "AA 5120887", "sh.rahimov@silkroad.uz"),
    ("Bekzod To'xtayev", "+998 93 118 74 62", "AB 1084432", "b.toxtayev@silkroad.uz"),
    ("Jasur Ergashev", "+998 94 774 09 33", "AB 7745901", "j.ergashev@silkroad.uz"),
    ("Dilshod Nazarov", "+998 90 236 55 71", "AC 2360114", "d.nazarov@silkroad.uz"),
    ("Otabek Yusupov", "+998 97 891 42 06", "AC 8916620", "o.yusupov@silkroad.uz"),
    ("Rustam Sobirov", "+998 99 345 18 27", "AD 3451178", "r.sobirov@silkroad.uz"),
    ("Sardor Qodirov", "+998 90 620 73 54", "AD 6207739", "s.qodirov@silkroad.uz"),
    ("Farrux Mamatov", "+998 91 173 66 90", "AE 1736604", "f.mamatov@silkroad.uz"),
    ("Ulug'bek Xolmatov", "+998 93 958 31 12", "AE 9583312", "u.xolmatov@silkroad.uz"),
    ("Aziz Tursunov", "+998 94 264 87 45", "AF 2648871", "a.tursunov@silkroad.uz"),
    ("Nodir Ismoilov", "+998 90 703 25 68", "AF 7032556", "n.ismoilov@silkroad.uz"),
]

# --------------------------------------------------------------------------- #
# Geofences — depots, customer sites and border posts count as "authorized"    #
# --------------------------------------------------------------------------- #

# (name, category, lat, lng, radius_m)
GEOFENCES: list[tuple[str, str, float, float, float]] = [
    ("Sergeli baza (asosiy garaj)", "depot", 41.2205, 69.2180, 900),
    ("Yangiyo'l omborxonasi", "depot", 41.1130, 69.0450, 700),
    ("Samarqand terminali", "depot", 39.6540, 66.9330, 700),
    ("Buxoro mijoz ombori", "customer", 39.7690, 64.4600, 600),
    ("Nukus tarqatish markazi", "customer", 42.4400, 59.6300, 600),
    ("Andijon mijoz ombori", "customer", 40.7700, 72.3200, 600),
    ("Gishtko'prik bojxonasi", "border", 41.1900, 69.0600, 1_200),
    ("Yallama bojxonasi", "border", 40.9310, 68.6520, 1_200),
    ("Shymkent tranzit bazasi", "customer", 42.3300, 69.5800, 800),
    ("Moskva Domodedovo ombori", "customer", 55.4200, 37.9000, 1_000),
]

# --------------------------------------------------------------------------- #
# Vendors, stations, cargo                                                     #
# --------------------------------------------------------------------------- #

FUEL_STATIONS_UZ = [
    "UzGasTrade AGSh — Sergeli",
    "Uzbekneftgaz AYoQSh — Yangiyo'l",
    "Sardor Oil — Jizzax",
    "Neftgaz Servis — Guliston",
    "Zarafshon Petrol — Navoiy",
    "Oq Yo'l AYoQSh — Samarqand",
]
FUEL_STATIONS_FOREIGN = [
    "KazMunayGas — Shymkent",
    "Helios — Olmaota",
    "Rosneft — Orenburg",
    "Lukoil — Samara",
    "Gazpromneft — Qozon",
]

SERVICE_VENDORS = [
    "MAN Servis Toshkent",
    "Avtoservis Chilonzor",
    "Zangiota TIR Servis",
    "Volvo Truck Center Toshkent",
    "Yangi Hayot avtoustaxonasi",
    "Samarqand Diesel Servis",
]

MAINT_NOTES = [
    "Rejali texnik ko'rik — nosozlik topilmadi.",
    "Moy va filtr almashtirildi.",
    "Tormoz kolodkalari 40% qoldi — keyingi ko'rikda almashtiriladi.",
    "G'ildiraklar aylantirildi, bosim tekshirildi.",
    "Akkumulyator quvvati past — almashtirildi.",
    "Sovutish tizimi tozalandi, antifriz quyildi.",
]

SHIPPERS = [
    "Artel Electronics",
    "UzAuto Motors",
    "Coca-Cola Ichimlik Uzbekiston",
    "Akfa Group",
    "Uzbekiston Temir Yo'llari",
    "Global Textile Group",
    "Nestle Uzbekistan",
    "EPAM Agro Trade",
]
CONSIGNEES = [
    "Korzinka Distribution Center",
    "Makro Savdo MChJ",
    "Wildberries UZ ombori",
    "Uzum Market fulfilment",
    "Havas Retail",
    "Mediapark Logistics",
    "Bek Trade Group",
    "Sharq Savdo MChJ",
]
CARGO = [
    ("Maishiy texnika (konteynerda)", 18_500, False),
    ("To'qimachilik mahsulotlari", 14_200, False),
    ("Muzlatilgan go'sht mahsulotlari", 16_800, True),
    ("Sut mahsulotlari", 12_400, True),
    ("Qurilish materiallari", 22_000, False),
    ("Avtoehtiyot qismlar", 9_600, False),
    ("Meva-sabzavot (yangi)", 19_300, True),
    ("Kimyoviy xomashyo (xavfsiz sinf)", 20_100, False),
]

DIESEL_PRICE_UZS = (13_000, 14_600)
