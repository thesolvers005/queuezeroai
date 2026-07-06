"""
Tests db.py directly — no LLM involved. Run this to confirm the database
layer itself works correctly, independent of whether the local model is
calling tools correctly.
 
Run: python3 test_db.py
"""
 
import db
from locations import resolve_location
 
print("=== resolve_location('Mangalagiri') ===")
coords = resolve_location("Mangalagiri")
print(coords)
 
print("\n=== find_doctors(specialization='Cardiology', gender='female', near coords, max_distance_km=10) ===")
doctors = db.find_doctors(
    specialization="Cardiology",
    gender="female",
    near_latitude=coords["latitude"],
    near_longitude=coords["longitude"],
    max_distance_km=10,
)
print(f"Found {len(doctors)} doctors")
for d in doctors[:5]:
    print(f"  - {d['doctor_name']} | rating {d['rating']} | {d['distance_km']}km | wait {d['average_wait_mins']}min")
 
if doctors:
    first_doctor_id = doctors[0]["doctor_id"]
    print(f"\n=== find_available_slots(doctor_id='{first_doctor_id}', after_time='15:00') ===")
    slots = db.find_available_slots(first_doctor_id, after_time="15:00")
    print(f"Found {len(slots)} slots")
    for s in slots[:5]:
        print(f"  - {s['date']} {s['time']}")
else:
    print("\nNo doctors found matching those filters — can't test find_available_slots meaningfully.")
    print("If find_doctors above returned 0, check: did you seed the DB? Is gender lowercase 'female' in your data?")
 