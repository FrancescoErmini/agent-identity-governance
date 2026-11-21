"""Deterministic synthetic data: same accounts and visits on every run."""
import random
from datetime import date, timedelta

from faker import Faker

from .db import SCHEMA, conn

TERRITORIES = ["NORTH", "CENTRE", "SOUTH"]
REPS = {"NORTH": "luca", "CENTRE": "giulia", "SOUTH": "marco"}
SPECIALTIES = ["cardiology", "nephrology", "general practice"]
PRODUCTS = ["Cardiox", "Renalis", "Glucomed", "Pressil"]
OUTCOMES = ["interested", "neutral", "follow-up needed", "not interested"]
NEXT_STEPS = ["Send the new clinical study", "Book a follow-up in 4 weeks", "Invite to the regional congress",
              "Leave samples at the next visit", "Introduce the medical science liaison",
              "Share patient leaflets", "Check stock at the local pharmacy"]


def seed() -> None:
    with conn() as c:
        c.execute(SCHEMA)
        if c.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]:
            return

        fake = Faker("it_IT")
        Faker.seed(42)
        rnd = random.Random(42)

        accounts = []
        for i in range(300):
            territory = TERRITORIES[i % 3]
            accounts.append((f"ACC-{i:05d}", f"Dr. {fake.last_name()}", rnd.choice(SPECIALTIES),
                             fake.city(), territory, REPS[territory]))
        c.cursor().executemany("INSERT INTO accounts VALUES (%s, %s, %s, %s, %s, %s)", accounts)

        start = date(2026, 1, 1)
        visits = []
        for i in range(1500):
            acc = accounts[rnd.randrange(len(accounts))]
            incomplete = rnd.random() < 0.2  # agent-dq has work to do
            visits.append((
                f"VIS-{i:05d}", acc[0], acc[5], start + timedelta(days=rnd.randrange(300)),
                None if incomplete else rnd.choice(OUTCOMES),
                ", ".join(rnd.sample(PRODUCTS, 2)),
                None if incomplete else rnd.choice(NEXT_STEPS),
            ))
        c.cursor().executemany("INSERT INTO visits VALUES (%s, %s, %s, %s, %s, %s, %s)", visits)


if __name__ == "__main__":
    seed()
