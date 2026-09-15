"""Indian state metadata based on Census 2011 population figures."""

# Keys become table suffixes; each value is (display name, Census 2011 population).
# Current 28 Indian states are included; union territories are excluded.
STATE_POPULATIONS = {
    "andhra_pradesh": ("Andhra Pradesh", 49_386_799),
    "arunachal_pradesh": ("Arunachal Pradesh", 1_383_727),
    "assam": ("Assam", 31_205_576),
    "bihar": ("Bihar", 104_099_452),
    "chhattisgarh": ("Chhattisgarh", 25_545_198),
    "goa": ("Goa", 1_458_545),
    "gujarat": ("Gujarat", 60_439_692),
    "haryana": ("Haryana", 25_351_462),
    "himachal_pradesh": ("Himachal Pradesh", 6_864_602),
    "jharkhand": ("Jharkhand", 32_988_134),
    "karnataka": ("Karnataka", 61_095_297),
    "kerala": ("Kerala", 33_406_061),
    "madhya_pradesh": ("Madhya Pradesh", 72_626_809),
    "maharashtra": ("Maharashtra", 112_374_333),
    "manipur": ("Manipur", 2_855_794),
    "meghalaya": ("Meghalaya", 2_966_889),
    "mizoram": ("Mizoram", 1_097_206),
    "nagaland": ("Nagaland", 1_978_502),
    "odisha": ("Odisha", 41_974_218),
    "punjab": ("Punjab", 27_743_338),
    "rajasthan": ("Rajasthan", 68_548_437),
    "sikkim": ("Sikkim", 610_577),
    "tamil_nadu": ("Tamil Nadu", 72_147_030),
    "telangana": ("Telangana", 35_193_978),
    "tripura": ("Tripura", 3_673_917),
    "uttar_pradesh": ("Uttar Pradesh", 199_812_341),
    "uttarakhand": ("Uttarakhand", 10_086_292),
    "west_bengal": ("West Bengal", 91_276_115),
}

# Assumption requested by the dataset model: half of each state's population
# is represented by generated student records.
STUDENT_POPULATION_RATIO = 0.02


def student_count_for_state(population):
    """Return the estimated student count using the 2% assumption."""
    return max(1, round(population * STUDENT_POPULATION_RATIO))


# Precompute the row count used by the seeder for every state table.
STATE_STUDENT_COUNTS = {
    table_name: student_count_for_state(population)
    for table_name, (_, population) in STATE_POPULATIONS.items()
}
