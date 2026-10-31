"""Test-only synthetic people in Crustdata Person Search shape (not real people). The live runs use real records
fetched by scripts/fetch_talent_pools.py; these exist so the unit tests run offline at the same scale."""
from __future__ import annotations

import random
from datetime import date

FIRST = ["Asha", "Ravi", "Meena", "Sunil", "Lakshmi", "Farhan", "Divya", "Manoj", "Rekha", "Prakash", "Anita", "Gopal",
         "Nisha", "Kiran", "Salma", "Vijay", "Uma", "Harish", "Geeta", "Naveen"]
LAST = ["Rao", "Shetty", "Pillai", "Yadav", "Mishra", "Qureshi", "Menon", "Kulkarni", "Bose", "Chauhan", "Naidu", "Patil"]
CITY = {"Bangalore": "Bengaluru, Karnataka, India", "Mumbai": "Mumbai, Maharashtra, India", "Delhi NCR": "Gurugram, Haryana, India",
        "Hyderabad": "Hyderabad, Telangana, India", "Pune": "Pune, Maharashtra, India", "Chennai": "Chennai, Tamil Nadu, India"}
TITLES = {"delivery": ["Delivery Executive", "Delivery Associate"], "warehouse": ["Warehouse Associate", "Picker Packer"],
          "support": ["Customer Support Executive", "Customer Care Executive"], "retail": ["Retail Sales Associate", "Cashier"],
          "security": ["Security Guard", "Security Officer"], "hospitality": ["Barista", "Steward"]}
EMPLOYERS = ["Shadowfax", "Delhivery", "Ecom Express", "Udaan", "Teleperformance", "Concentrix", "Trent", "Lifestyle",
             "SIS Security", "G4S", "Third Wave Coffee", "Chai Point"]


def person(i: int, fam: str, city: str, rng: random.Random, title: str | None = None) -> dict:
    name = f"{FIRST[i % len(FIRST)]} {LAST[(i // len(FIRST)) % len(LAST)]}"
    start = date(rng.randint(2018, 2025), rng.randint(1, 12), 1)
    past_start = date(start.year - rng.randint(1, 4), rng.randint(1, 12), 1)
    cur_co, past_co = rng.sample(EMPLOYERS, 2)
    url = f"https://www.linkedin.com/in/test-{name.lower().replace(' ', '-')}-{i}"
    return {
        "crustdata_person_id": 900000 + i,
        "basic_profile": {"name": name, "headline": f"{title or TITLES[fam][0]} at {cur_co}",
                          "location": {"full_location": CITY[city], "raw": CITY[city]}},
        "experience": {"employment_details": {
            "current": [{"name": cur_co, "title": title or rng.choice(TITLES[fam]), "start_date": f"{start.isoformat()}T00:00:00",
                         "seniority_level": "Entry Level", "company_headcount_latest": 5000}],
            "past": [{"name": past_co, "title": rng.choice(TITLES[fam]), "start_date": f"{past_start.isoformat()}T00:00:00",
                      "end_date": f"{start.isoformat()}T00:00:00"}],
        }},
        "social_handles": {"professional_network_identifier": {"profile_url": url}},
        "_source": {"endpoint": "person/search", "origin": "test"},
        "_family": fam,
    }


def shift_pool(n: int = 1200, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    fams, cities = list(TITLES), list(CITY)
    return [person(i, fams[i % len(fams)], cities[(i // len(fams)) % len(cities)], rng) for i in range(n)]


def engineer_pool(n: int = 120, seed: int = 5) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        p = person(i, "support", "Bangalore", rng, title=rng.choice(["Senior Backend Engineer", "Backend Engineer", "Software Engineer II"]))
        p["experience"]["employment_details"]["current"][0]["name"] = rng.choice(["Razorpay", "Juspay", "PhonePe", "Cred", "Paytm"])
        p["basic_profile"]["headline"] = "Backend engineer, payments"
        p.pop("_family")
        out.append(p)
    return out
