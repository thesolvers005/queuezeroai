"""
Idempotent Supabase demo-data seeder for QueueZero AI.

Adds hospitals (spread across real sub-locality coordinates per city),
doctors (several per specialization per city), live queue rows, and
7-day appointment schedules — so the booking agent's radius search and
"after 3pm" time filtering actually have realistic data to return.

Schema (confirmed by introspecting the live Supabase project — see
tools.py / db.py for how these are read):
    hospitals(id, name, branch, city, address, latitude, longitude, created_at)
    doctors(id, hospital_id, name, gender, specialization, experience_years,
            rating, created_at)
    queues(id, doctor_id, waiting_people, average_wait_mins, priority_queue,
           updated_at)          -- one row per doctor; doctor_search_view
                                    inner-joins on this, so a doctor with no
                                    queue row won't show up in find_doctors.
    schedules(id, doctor_id, date, start_time, end_time, slot_duration_mins,
              slots jsonb[{time: "HH:MM", is_available: bool}], created_at)

Re-running this script is safe: every insert is preceded by a check against
existing rows on a natural key (hospital name+branch+city, doctor
name+specialization+hospital_id, doctor_id+date for schedules/queues).
"""

import os
import random
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (.env).")

client = create_client(SUPABASE_URL, SUPABASE_KEY)

random.seed(42)  # reproducible demo data across re-runs

SPECIALIZATIONS = [
    "Cardiology", "ENT", "Dermatology", "Orthopedics", "Neurology",
    "Psychiatry", "Pediatrics", "Gynecology", "General Medicine", "Dentistry",
]
DOCTORS_PER_SPEC_PER_CITY = 2

START_DATE = date(2026, 7, 12)
NUM_DAYS = 8  # 2026-07-12 .. 2026-07-19 inclusive
DATES = [(START_DATE + timedelta(days=i)).isoformat() for i in range(NUM_DAYS)]

SLOT_DURATION_MINS = 15
DAY_START = "09:00:00"
DAY_END = "20:00:00"
BOOKED_FRACTION = 0.30

# city -> [(hospital_name, branch_label, lat, lon), ...] spread across a real
# ~15-20km radius using actual sub-locality coordinates.
CITY_HOSPITALS = {
    "Hyderabad": [
        ("Sunshine Hospitals", "Banjara Hills Branch", 17.4156, 78.4347),
        ("Medicover Hospitals", "Kukatpally Branch", 17.4849, 78.4138),
        ("Star Hospitals", "LB Nagar Branch", 17.3467, 78.5500),
        ("Rainbow Hospitals", "Uppal Branch", 17.4058, 78.5590),
    ],
    "Vijayawada": [
        ("Andhra Hospitals", "Benz Circle Branch", 16.5093, 80.6528),
        ("Sunrise Hospitals", "Governorpet Branch", 16.5175, 80.6225),
        ("Amma Hospitals", "Patamata Branch", 16.5152, 80.6650),
        ("Ramesh Hospitals", "Gunadala Branch", 16.5308, 80.6725),
    ],
    "Mangalagiri": [
        ("NRI Hospital", "Tadepalli Branch", 16.4762, 80.6039),
        ("Sri Sai Hospitals", "Nidamanuru Branch", 16.4650, 80.5300),
        ("Lakshmi Hospitals", "Atmakur Branch", 16.3900, 80.5200),
        ("Global Hospitals", "Kesarapalli Branch", 16.4550, 80.5950),
    ],
    "Guntur": [
        ("Manipal Hospitals", "Brodipet Branch", 16.3126, 80.4404),
        ("Sri Ramachandra Hospitals", "Lakshmipuram Branch", 16.2975, 80.4450),
        ("Guntur General Hospital", "Pattabhipuram Branch", 16.2850, 80.4550),
        ("Kamineni Hospitals", "Nagarampalem Branch", 16.3200, 80.4200),
    ],
    "Bangalore": [
        ("Manipal Hospitals", "Koramangala Branch", 12.9352, 77.6245),
        ("Narayana Health", "Whitefield Branch", 12.9698, 77.7500),
        ("Columbia Asia", "Indiranagar Branch", 12.9719, 77.6412),
        ("Apollo Hospitals", "Jayanagar Branch", 12.9250, 77.5938),
        ("Fortis Hospitals", "Hebbal Branch", 13.0358, 77.5970),
    ],
    "Chennai": [
        ("Apollo Hospitals", "Adyar Branch", 13.0012, 80.2565),
        ("MIOT International", "Anna Nagar Branch", 13.0850, 80.2101),
        ("Fortis Malar Hospital", "T Nagar Branch", 13.0418, 80.2341),
        ("Gleneagles Global Health City", "Velachery Branch", 12.9791, 80.2183),
        ("SIMS Hospital", "Perambur Branch", 13.1170, 80.2470),
    ],
    "Mumbai": [
        ("Kokilaben Hospital", "Andheri Branch", 19.1136, 72.8697),
        ("Lilavati Hospital", "Bandra Branch", 19.0596, 72.8295),
        ("Hiranandani Hospital", "Powai Branch", 19.1197, 72.9059),
        ("Wockhardt Hospitals", "Dadar Branch", 19.0178, 72.8478),
        ("Kokilaben Dhirubhai Ambani", "Borivali Branch", 19.2288, 72.8567),
    ],
    "Pune": [
        ("Sahyadri Hospitals", "Kothrud Branch", 18.5074, 73.8077),
        ("Ruby Hall Clinic", "Hinjewadi Branch", 18.5913, 73.7389),
        ("Jehangir Hospital", "Viman Nagar Branch", 18.5679, 73.9143),
        ("Columbia Asia", "Kharadi Branch", 18.5515, 73.9400),
        ("Noble Hospital", "Hadapsar Branch", 18.5089, 73.9260),
    ],
    "Delhi": [
        ("Max Super Speciality Hospital", "Dwarka Branch", 28.5921, 77.0460),
        ("Fortis Hospital", "Rohini Branch", 28.7041, 77.1025),
        ("Apollo Hospitals", "Saket Branch", 28.5245, 77.2066),
        ("Indraprastha Apollo", "Vasant Kunj Branch", 28.5200, 77.1590),
        ("BLK-Max Super Speciality", "Karol Bagh Branch", 28.6519, 77.1909),
    ],
    "Kolkata": [
        ("AMRI Hospitals", "Salt Lake Branch", 22.5800, 88.4171),
        ("Fortis Hospital", "Howrah Branch", 22.5958, 88.2636),
        ("Belle Vue Clinic", "Behala Branch", 22.5000, 88.3100),
        ("Peerless Hospital", "Garia Branch", 22.4649, 88.3927),
        ("Charnock Hospital", "Dum Dum Branch", 22.6420, 88.4200),
    ],
}

MALE_FIRST = [
    "Arjun", "Vikram", "Rohan", "Aditya", "Karthik", "Suresh", "Ravi", "Manoj",
    "Vivek", "Sandeep", "Ajay", "Nikhil", "Pranav", "Rajesh", "Ashok", "Sameer",
    "Varun", "Gopal", "Harish", "Deepak",
]
FEMALE_FIRST = [
    "Priya", "Divya", "Ananya", "Meera", "Kavya", "Shreya", "Pooja", "Neha",
    "Swati", "Ritu", "Anjali", "Nandini", "Bhavana", "Lakshmi", "Sowmya",
    "Radhika", "Sneha", "Madhuri", "Kirti", "Vidya",
]
LAST_NAMES = [
    "Sharma", "Reddy", "Rao", "Iyer", "Menon", "Naidu", "Gupta", "Varma",
    "Prasad", "Chowdary", "Pillai", "Kumar", "Nair", "Mehta", "Joshi",
    "Verma", "Bhat", "Kapoor", "Desai", "Bose",
]


def _fetch_all(table, columns, filters=None):
    """
    Paginated select — Supabase/PostgREST caps a single select() at 1000 rows
    by default, which would silently truncate existence checks once seeded
    tables (e.g. schedules) grow past that and break idempotency.
    """
    rows = []
    page_size = 1000
    start = 0
    while True:
        query = client.table(table).select(columns)
        if filters:
            query = filters(query)
        page = query.range(start, start + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def _gen_doctor(city, spec, i):
    """
    Deterministic per-(city, spec, i) doctor identity: a pure function of its
    inputs via a locally seeded RNG, so re-running the script always derives
    the exact same name/gender/hospital/experience/rating for a given slot
    instead of depending on shared global random state (which drifts across
    runs once some names are already taken and get retried).
    """
    rnd = random.Random(f"{city}|{spec}|{i}")
    gender = rnd.choice(["male", "female"])
    first_pool = MALE_FIRST if gender == "male" else FEMALE_FIRST
    name = f"Dr. {rnd.choice(first_pool)} {rnd.choice(LAST_NAMES)}"
    experience_years = rnd.randint(3, 25)
    rating = round(rnd.uniform(3.5, 5.0), 1)
    return name, gender, experience_years, rating


def _gen_slot_times():
    times = []
    t = datetime(2000, 1, 1, 9, 0)
    morning_end = datetime(2000, 1, 1, 13, 0)
    while t < morning_end:
        times.append(t.strftime("%H:%M"))
        t += timedelta(minutes=SLOT_DURATION_MINS)
    t = datetime(2000, 1, 1, 14, 0)  # lunch break 13:00-14:00
    day_end = datetime(2000, 1, 1, 20, 0)
    while t < day_end:
        times.append(t.strftime("%H:%M"))
        t += timedelta(minutes=SLOT_DURATION_MINS)
    return times


SLOT_TIMES = _gen_slot_times()


def seed_hospitals():
    existing = _fetch_all("hospitals", "id,name,branch,city")
    existing_keys = {(h["name"], h.get("branch"), h["city"]) for h in existing}

    to_insert = []
    for city, hospitals in CITY_HOSPITALS.items():
        for name, branch, lat, lon in hospitals:
            key = (name, branch, city)
            if key in existing_keys:
                continue
            to_insert.append({
                "name": name,
                "branch": branch,
                "city": city,
                "address": f"{branch.replace(' Branch', '')}, {city}",
                "latitude": lat,
                "longitude": lon,
            })

    if to_insert:
        for i in range(0, len(to_insert), 200):
            client.table("hospitals").insert(to_insert[i:i + 200]).execute()

    all_hospitals = _fetch_all("hospitals", "*")
    by_city = {}
    for h in all_hospitals:
        by_city.setdefault(h["city"], []).append(h)
    # stable order so a given (city, spec, i) always maps to the same hospital
    # across runs, regardless of the order rows come back from Postgres
    for city in by_city:
        by_city[city].sort(key=lambda h: h["id"])
    return by_city, len(to_insert)


def seed_doctors(by_city):
    existing = _fetch_all("doctors", "id,name,specialization,hospital_id")
    existing_keys = {(d["name"], d["specialization"], d["hospital_id"]) for d in existing}

    to_insert = []
    per_spec_count = {spec: 0 for spec in SPECIALIZATIONS}

    for city in CITY_HOSPITALS:  # only the 10 target cities
        hospitals = by_city.get(city, [])
        if not hospitals:
            continue
        for spec in SPECIALIZATIONS:
            for i in range(DOCTORS_PER_SPEC_PER_CITY):
                hosp = hospitals[i % len(hospitals)]
                name, gender, experience_years, rating = _gen_doctor(city, spec, i)
                key = (name, spec, hosp["id"])
                if key in existing_keys:
                    continue
                to_insert.append({
                    "hospital_id": hosp["id"],
                    "name": name,
                    "gender": gender,
                    "specialization": spec,
                    "experience_years": experience_years,
                    "rating": rating,
                })
                existing_keys.add(key)
                per_spec_count[spec] += 1

    if to_insert:
        for i in range(0, len(to_insert), 200):
            client.table("doctors").insert(to_insert[i:i + 200]).execute()

    all_doctors = _fetch_all("doctors", "*")
    return all_doctors, len(to_insert), per_spec_count


def seed_queues(all_doctors):
    existing = _fetch_all("queues", "doctor_id")
    have = {q["doctor_id"] for q in existing}

    to_insert = []
    for d in all_doctors:
        if d["id"] in have:
            continue
        to_insert.append({
            "doctor_id": d["id"],
            "waiting_people": random.randint(0, 20),
            "average_wait_mins": random.randint(5, 60),
            "priority_queue": False,
        })

    if to_insert:
        for i in range(0, len(to_insert), 200):
            client.table("queues").insert(to_insert[i:i + 200]).execute()

    return len(to_insert)


def seed_schedules(all_doctors):
    existing = _fetch_all(
        "schedules", "doctor_id,date",
        filters=lambda q: q.in_("date", DATES),
    )
    have = {(s["doctor_id"], s["date"]) for s in existing}

    to_insert = []
    total_available = 0
    total_after_3pm_available = 0

    for d in all_doctors:
        for d_str in DATES:
            key = (d["id"], d_str)
            if key in have:
                continue
            slots = []
            for t in SLOT_TIMES:
                is_available = random.random() >= BOOKED_FRACTION
                slots.append({"time": t, "is_available": is_available})
                if is_available:
                    total_available += 1
                    if t >= "15:00":
                        total_after_3pm_available += 1
            to_insert.append({
                "doctor_id": d["id"],
                "date": d_str,
                "start_time": DAY_START,
                "end_time": DAY_END,
                "slot_duration_mins": SLOT_DURATION_MINS,
                "slots": slots,
            })

    if to_insert:
        for i in range(0, len(to_insert), 200):
            client.table("schedules").insert(to_insert[i:i + 200]).execute()

    return len(to_insert), total_available, total_after_3pm_available


def main():
    print("Seeding hospitals...")
    by_city, new_hospitals = seed_hospitals()
    print(f"  {new_hospitals} new hospitals inserted.")

    print("Seeding doctors...")
    all_doctors, new_doctors, per_spec_count = seed_doctors(by_city)
    print(f"  {new_doctors} new doctors inserted.")

    print("Seeding queues...")
    new_queues = seed_queues(all_doctors)
    print(f"  {new_queues} new queue rows inserted.")

    print("Seeding schedules (2026-07-12 .. 2026-07-19)...")
    new_schedules, total_available, total_after_3pm = seed_schedules(all_doctors)
    print(f"  {new_schedules} new schedule rows inserted.")

    print("\n=== Summary ===")
    print("Hospitals per city (total after seeding):")
    for city in CITY_HOSPITALS:
        print(f"  {city}: {len(by_city.get(city, []))}")

    print("\nNew doctors inserted per specialization:")
    for spec, count in per_spec_count.items():
        print(f"  {spec}: {count}")

    print(f"\nTotal available slots created (new schedules only): {total_available}")
    print(f"  of which after-3pm (>=15:00): {total_after_3pm}")


if __name__ == "__main__":
    main()
