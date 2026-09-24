import random
import time
import requests
from decimal import Decimal

from django.core.management.base import BaseCommand
from decouple import config

from apps.locations.models import City
from apps.hotels.models import Hotel
from apps.adventures.models import Adventure
from apps.vehicles.models import Vehicle


UNSPLASH_ACCESS_KEY = config("UNSPLASH_ACCESS_KEY", default="")
UNSPLASH_URL = "https://api.unsplash.com/search/photos"


# ---------- REAL CITY DATA (name, state, lat, long) ----------
CITIES = [
    ("Goa", "Goa", 15.2993, 74.1240),
    ("Manali", "Himachal Pradesh", 32.2432, 77.1892),
    ("Delhi", "Delhi", 28.7041, 77.1025),
    ("Mumbai", "Maharashtra", 19.0760, 72.8777),
    ("Jaipur", "Rajasthan", 26.9124, 75.7873),
    ("Udaipur", "Rajasthan", 24.5854, 73.7125),
    ("Rishikesh", "Uttarakhand", 30.0869, 78.2676),
    ("Munnar", "Kerala", 10.0889, 77.0595),
    ("Darjeeling", "West Bengal", 27.0360, 88.2627),
    ("Leh", "Ladakh", 34.1526, 77.5771),
    ("Shimla", "Himachal Pradesh", 31.1048, 77.1734),
    ("Varanasi", "Uttar Pradesh", 25.3176, 82.9739),
]

HOTEL_PREFIXES = ["The Grand", "Royal", "Taj", "Le Meridien", "Sunset", "Hillview",
                  "Ocean Pearl", "Heritage", "Green Valley", "The Imperial"]
HOTEL_SUFFIXES = ["Resort", "Palace", "Retreat", "Inn", "Suites", "Grand Hotel"]
AMENITIES_POOL = ["WiFi", "Pool", "Spa", "Gym", "Restaurant", "Bar",
                  "Room Service", "Parking", "AC", "Breakfast Included"]

ADVENTURES = [
    ("Paragliding", "EASY", 2), ("River Rafting", "MEDIUM", 3),
    ("Trekking", "HARD", 6), ("Scuba Diving", "MEDIUM", 3),
    ("Bungee Jumping", "HARD", 1), ("Zip Lining", "EASY", 1),
    ("Camping", "EASY", 12), ("Rock Climbing", "HARD", 4),
    ("Kayaking", "MEDIUM", 2), ("Hot Air Balloon", "EASY", 2),
]

VEHICLES = [
    ("Royal Enfield Classic 350", "BIKE"), ("Honda Activa", "SCOOTER"),
    ("Maruti Swift", "CAR"), ("Mahindra Thar", "CAR"),
    ("KTM Duke 390", "BIKE"), ("Toyota Innova", "CAR"),
    ("Vespa VXL", "SCOOTER"), ("Hyundai Creta", "CAR"),
]

_image_cache = {}


def get_image(query, fallback="travel"):
    """Fetch a real image URL from Unsplash for the given query."""
    if query in _image_cache:
        return _image_cache[query]

    # No key -> use keyless source.unsplash.com
    if not UNSPLASH_ACCESS_KEY:
        url = f"https://source.unsplash.com/800x600/?{query.replace(' ', ',')}"
        _image_cache[query] = url
        return url

    try:
        resp = requests.get(
            UNSPLASH_URL,
            params={"query": query, "per_page": 10, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=10,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                pick = random.choice(results)
                url = pick["urls"]["regular"]
                _image_cache[query] = url
                return url
    except Exception as e:
        print(f"  ! image fetch failed for '{query}': {e}")

    # fallback keyless
    url = f"https://source.unsplash.com/800x600/?{fallback}"
    _image_cache[query] = url
    return url


def jitter(base, spread=0.05):
    """Small random offset for lat/long so markers don't stack."""
    return float(base) + random.uniform(-spread, spread)


class Command(BaseCommand):
    help = "Seed the database with cities, hotels, adventures and vehicles (with real images)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh", action="store_true",
            help="Delete all existing data before seeding.",
        )

    def handle(self, *args, **options):
        if options["fresh"]:
            self.stdout.write("Deleting existing data...")
            Vehicle.objects.all().delete()
            Adventure.objects.all().delete()
            Hotel.objects.all().delete()
            City.objects.all().delete()

        self.stdout.write(self.style.WARNING(
            f"Unsplash key: {'FOUND' if UNSPLASH_ACCESS_KEY else 'NOT SET (using keyless source URLs)'}"
        ))

        for name, state, lat, lng in CITIES:
            self.stdout.write(f"\nSeeding {name}...")

            city, _ = City.objects.get_or_create(
                name=name,
                defaults={
                    "state": state,
                    "latitude": Decimal(str(lat)),
                    "longitude": Decimal(str(lng)),
                    "image_url": get_image(f"{name} india travel", "india,travel"),
                    "is_active": True,
                },
            )

            # ---- Hotels (3 per city) ----
            for _ in range(3):
                hname = f"{random.choice(HOTEL_PREFIXES)} {random.choice(HOTEL_SUFFIXES)}"
                rooms = random.randint(15, 60)
                Hotel.objects.create(
                    city=city,
                    name=hname,
                    description=f"A comfortable stay in {name} with modern amenities and great service.",
                    price_per_night=Decimal(str(random.randint(1500, 12000))),
                    total_rooms=rooms,
                    available_rooms=random.randint(3, rooms),
                    latitude=Decimal(str(jitter(lat))),
                    longitude=Decimal(str(jitter(lng))),
                    amenities=random.sample(AMENITIES_POOL, k=random.randint(4, 7)),
                    rating=Decimal(str(round(random.uniform(3.5, 5.0), 1))),
                    image_url=get_image(f"{name} hotel resort", "hotel,resort"),
                    is_active=True,
                )
            self.stdout.write(f"  + 3 hotels")

            # ---- Adventures (3 per city) ----
            for adv_name, difficulty, hours in random.sample(ADVENTURES, k=3):
                cap = random.randint(10, 30)
                Adventure.objects.create(
                    city=city,
                    name=adv_name,
                    description=f"Experience {adv_name.lower()} in {name}. A must-do activity for thrill seekers.",
                    price_per_person=Decimal(str(random.randint(500, 5000))),
                    max_capacity=cap,
                    current_bookings=random.randint(0, cap // 2),
                    duration_hours=hours,
                    difficulty=difficulty,
                    latitude=Decimal(str(jitter(lat))),
                    longitude=Decimal(str(jitter(lng))),
                    image_url=get_image(f"{adv_name} adventure", "adventure,outdoor"),
                    is_active=True,
                )
            self.stdout.write(f"  + 3 adventures")

            # ---- Vehicles (3 per city) ----
            for vname, vtype in random.sample(VEHICLES, k=3):
                price = {"BIKE": (600, 1500), "SCOOTER": (400, 900), "CAR": (1500, 4000)}[vtype]
                Vehicle.objects.create(
                    city=city,
                    name=vname,
                    vehicle_type=vtype,
                    price_per_day=Decimal(str(random.randint(*price))),
                    is_available=True,
                    latitude=Decimal(str(jitter(lat))),
                    longitude=Decimal(str(jitter(lng))),
                    image_url=get_image(f"{vname} {vtype}", "vehicle,transport"),
                )
            self.stdout.write(f"  + 3 vehicles")

            # gentle pause so Unsplash rate limit (50/hr) isn't hit too fast
            if UNSPLASH_ACCESS_KEY:
                time.sleep(1)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! {City.objects.count()} cities, {Hotel.objects.count()} hotels, "
            f"{Adventure.objects.count()} adventures, {Vehicle.objects.count()} vehicles."
        ))