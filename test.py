
"""
Manual test script for the agent core:
  1. A request with no real matches -> tests it asks a clarifying question
     honestly instead of fabricating, and that follow-up context is remembered.
  2. A request likely to succeed -> tests real booking end-to-end.
 
Run: python3 test_agent.py
 
After it finishes, go check your Supabase 'appointments' table for a new row
with "Ravi Kumar" and today's/tomorrow's date — don't just trust the printed
text, confirm it against the actual database.
"""
 
from agent import run_agent
 
print("=" * 60)
print("TEST 1: multi-turn conversation with a constraint that has no matches")
print("=" * 60)
 
result1 = run_agent(
    "I need the earliest available female cardiologist after 3 PM today. "
    "I don't want to travel more than 10 km from Mangalagiri, and I want "
    "under 20 minutes of waiting time. My name is Lakshmi Reddy."
)
print("\n--- Turn 1 reply ---")
print(result1["reply"])
 
result2 = run_agent("Increase the distance to 15 km", conversation_history=result1["history"])
print("\n--- Turn 2 reply (should remember name/specialization/etc from turn 1) ---")
print(result2["reply"])
 
print("\n" + "=" * 60)
print("TEST 2: a request that should actually succeed end-to-end")
print("=" * 60)
 
result3 = run_agent("I need a dermatologist tomorrow morning, my name is Ravi Kumar.")
print("\n--- Tool calls made ---")
for step in result3["steps"]:
    print(f"  -> {step['tool']}({step['input']})")
    print(f"     output: {step['output']}")
 
print("\n--- Final reply ---")
print(result3["reply"])
 
print("\n" + "=" * 60)
print("Now go check your Supabase 'appointments' table for a real row with")
print("'Ravi Kumar' — don't trust the text above until you see it in the DB.")
print("=" * 60)