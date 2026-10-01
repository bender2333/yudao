import math

# (lower bound in meters, fare in yuan); left-closed, right-open.
TIERS = [
    (32000, 7),
    (52000, 8),
    (72000, 9),
    (92000, 10),
]


def Sum_money(distance_meters):
    distance = math.ceil(distance_meters)
    if distance < 6000:
        return 3
    if distance < 12000:
        return 4
    if distance < 22000:
        return 5
    if distance < 32000:
        return 6
    fare = 7
    for lower, tier_fare in TIERS:
        if distance >= lower:
            fare = tier_fare
    if distance >= 92000:
        fare += (distance - 92000) // 20000
    return fare


def calculate_estimated_time(distance_meters, transfer_count):
    minutes = (distance_meters / 1000.0) * 1.5 + transfer_count * 5
    return int(round(minutes))
