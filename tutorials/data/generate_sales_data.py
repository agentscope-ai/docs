# -*- coding: utf-8 -*-
"""Generate sample e-commerce sales data for the tutorial series."""
# pylint: disable=missing-function-docstring
import csv
import random
from datetime import datetime, timedelta

random.seed(42)

PRODUCTS = {
    "Electronics": [
        ("Laptop Pro 15", 1299.99),
        ("Wireless Mouse", 29.99),
        ("USB-C Hub", 49.99),
        ("Mechanical Keyboard", 89.99),
        ("Monitor 27-inch", 399.99),
        ("Webcam HD", 59.99),
    ],
    "Clothing": [
        ("Cotton T-Shirt", 19.99),
        ("Denim Jeans", 49.99),
        ("Running Shoes", 79.99),
        ("Winter Jacket", 129.99),
        ("Wool Scarf", 24.99),
    ],
    "Books": [
        ("Python Programming", 39.99),
        ("Data Science Handbook", 44.99),
        ("AI Revolution", 29.99),
        ("Machine Learning Guide", 54.99),
    ],
    "Home & Kitchen": [
        ("Coffee Maker", 89.99),
        ("Air Purifier", 199.99),
        ("Smart Lamp", 34.99),
        ("Water Bottle", 14.99),
        ("Desk Organizer", 22.99),
    ],
    "Sports": [
        ("Yoga Mat", 29.99),
        ("Resistance Bands Set", 19.99),
        ("Dumbbell Set", 69.99),
        ("Jump Rope", 12.99),
    ],
}

REGIONS = ["North", "South", "East", "West", "Central"]
PAYMENT_METHODS = [
    "Credit Card",
    "PayPal",
    "Bank Transfer",
    "Cash on Delivery",
]
CUSTOMER_TIERS = ["Standard", "Premium", "VIP"]


def generate_sales_data(n_rows: int = 1000) -> list[dict]:
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 12, 31)
    delta = (end_date - start_date).days

    rows = []
    for i in range(1, n_rows + 1):
        category = random.choice(list(PRODUCTS.keys()))
        product_name, base_price = random.choice(PRODUCTS[category])
        quantity = random.randint(1, 10)
        discount = random.choice([0, 0, 0, 0.05, 0.10, 0.15, 0.20])
        unit_price = round(base_price * (1 - discount), 2)
        total = round(unit_price * quantity, 2)
        order_date = start_date + timedelta(days=random.randint(0, delta))

        rows.append(
            {
                "order_id": f"ORD-{i:05d}",
                "date": order_date.strftime("%Y-%m-%d"),
                "product": product_name,
                "category": category,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount": discount,
                "total": total,
                "region": random.choice(REGIONS),
                "payment_method": random.choice(PAYMENT_METHODS),
                "customer_tier": random.choice(CUSTOMER_TIERS),
            },
        )

    rows.sort(key=lambda r: r["date"])
    return rows


if __name__ == "__main__":
    data = generate_sales_data(1000)
    fieldnames = list(data[0].keys())

    with open("sales_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print(f"Generated {len(data)} rows -> sales_data.csv")
