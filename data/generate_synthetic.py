import json
import random
import uuid
import datetime
from pathlib import Path

# Data for generation
INDIAN_FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Rayaan", "Ayaan", "Krishna", "Ishaan",
    "Diya", "Sanya", "Kavya", "Ananya", "Myra", "Aadhya", "Pari", "Navya", "Riya", "Avni",
    "Rahul", "Rajat", "Ramesh", "Suresh", "Ravi", "Amit", "Sumit", "Raj", "Manoj", "Sanjay",
    "Pooja", "Neha", "Simran", "Sneha", "Kriti", "Shreya", "Nidhi", "Swati", "Divya", "Priya",
    "Karthik", "Arun", "Bala", "Ganesh", "Hari", "Prabhu", "Vijay", "Anand", "Srinivas", "Venkatesh",
    "Meenakshi", "Lakshmi", "Saraswati", "Bhavani", "Anitha", "Deepa", "Geetha", "Kala", "Radha", "Uma",
    "Sourav", "Abhishek", "Rohan", "Vikram", "Gaurav", "Nitin", "Tarun", "Varun", "Ashish", "Vivek",
    "Shalini", "Jyoti", "Kiran", "Rekha", "Sunita", "Anita", "Geeta", "Seema", "Renu", "Sarita"
]

INDIAN_LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Malhotra", "Singh", "Patel", "Shah", "Desai", "Mehta", "Chauhan",
    "Reddy", "Rao", "Kumar", "Iyer", "Pillai", "Nair", "Menon", "Das", "Bose", "Ghosh",
    "Sen", "Mukherjee", "Banerjee", "Chatterjee", "Mishra", "Pandey", "Tiwari", "Yadav", "Jain", "Bhat",
    "Sinha", "Srivastava", "Agarwal", "Kaur", "Ahluwalia", "Gill", "Dhillon", "Kapur", "Chopra", "Khanna",
    "Garg", "Bansal", "Goyal", "Mittal", "Nigam", "Saxena", "Mathur", "Joshi", "Deshpande", "Kulkarni",
    "Natarajan", "Raman", "Krishnan", "Swaminathan", "Venkataraman", "Naidu", "Chowdary", "Prasad", "Rajan", "Sundaram"
]

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com", "rediffmail.com"]

PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]
PAYMENT_METHOD_WEIGHTS = [0.40, 0.35, 0.15, 0.10]

LANGUAGE_PREFS = ["english", "hindi", "hinglish", "tamil", "telugu"]
LANGUAGE_WEIGHTS = [0.4, 0.3, 0.2, 0.05, 0.05]

# Load error codes from JSON
ERROR_CODES_FILE = Path(__file__).parent / "bank_error_codes.json"
try:
    with open(ERROR_CODES_FILE, "r") as f:
        ERROR_CODES = json.load(f)
except FileNotFoundError:
    print(f"Error: {ERROR_CODES_FILE} not found. Ensure the file exists.")
    exit(1)

# Categorize errors based on frequency
TRANSIENT_ERRORS = [k for k, v in ERROR_CODES.items() if v.get("category") == "transient"]
RECOVERABLE_ERRORS = [k for k, v in ERROR_CODES.items() if v.get("category") == "recoverable"]
TERMINAL_ERRORS = [k for k, v in ERROR_CODES.items() if v.get("category") == "terminal"]
SUSPICIOUS_ERRORS = [k for k, v in ERROR_CODES.items() if v.get("category") == "suspicious"]

# Assign weights to error categories (realistic distribution)
ERROR_CATEGORIES = [TRANSIENT_ERRORS, RECOVERABLE_ERRORS, TERMINAL_ERRORS, SUSPICIOUS_ERRORS]
ERROR_CATEGORY_WEIGHTS = [0.45, 0.35, 0.15, 0.05]

def generate_phone_number():
    """Generates a realistic Indian mobile number."""
    prefix = random.choice(["9", "8", "7", "6"])
    suffix = "".join([str(random.randint(0, 9)) for _ in range(9)])
    return f"+91{prefix}{suffix}"

def generate_timestamp(days_ago_range=(1, 30)):
    """Generates a random timestamp within the last N days."""
    days_ago = random.randint(days_ago_range[0], days_ago_range[1])
    hours_ago = random.randint(0, 23)
    minutes_ago = random.randint(0, 59)
    seconds_ago = random.randint(0, 59)
    
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = datetime.timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago, seconds=seconds_ago)
    return (now - delta).isoformat()

def generate_amount():
    """Generates a realistic payment amount in INR."""
    # Bias towards smaller amounts, but allow larger ones
    amount = random.choices(
        [random.randint(99, 999), random.randint(1000, 4999), random.randint(5000, 19999), random.randint(20000, 49999)],
        weights=[0.5, 0.3, 0.15, 0.05],
        k=1
    )[0]
    return amount

def generate_record():
    """Generates a single synthetic failed payment record."""
    first_name = random.choice(INDIAN_FIRST_NAMES)
    last_name = random.choice(INDIAN_LAST_NAMES)
    domain = random.choice(EMAIL_DOMAINS)
    email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1,99)}@{domain}"
    
    method = random.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS, k=1)[0]
    language = random.choices(LANGUAGE_PREFS, weights=LANGUAGE_WEIGHTS, k=1)[0]
    
    # Select error code based on realistic category distribution
    error_category = random.choices(ERROR_CATEGORIES, weights=ERROR_CATEGORY_WEIGHTS, k=1)[0]
    # Filter error category by method if applicable (e.g. UPI_TIMEOUT only for upi)
    applicable_errors = error_category
    if method == "upi":
        applicable_errors = [e for e in error_category if "CARD" not in e and "NETBANKING" not in e]
    elif method == "card":
        applicable_errors = [e for e in error_category if "UPI" not in e and "NETBANKING" not in e]
    elif method == "netbanking":
        applicable_errors = [e for e in error_category if "UPI" not in e and "CARD" not in e]
        
    if not applicable_errors:
        applicable_errors = error_category # fallback
        
    error_code = random.choice(applicable_errors)
    error_info = ERROR_CODES[error_code]
    
    is_subscription = random.random() < 0.2
    
    record = {
        "payment_id": f"pay_test_{uuid.uuid4().hex[:14]}",
        "order_id": f"order_test_{uuid.uuid4().hex[:14]}",
        "amount": generate_amount(),
        "currency": "INR",
        "method": method,
        "error_code": error_code,
        "error_description": error_info["description"],
        "customer": {
            "name": f"{first_name} {last_name}",
            "email": email,
            "phone": generate_phone_number(),
            "language_pref": language
        },
        "created_at": generate_timestamp(),
        "retry_count": random.randint(0, 3)
    }
    
    if is_subscription:
        record["subscription_id"] = f"sub_test_{uuid.uuid4().hex[:14]}"
        
    return record

def main():
    num_train = 45
    num_test = 25
    
    train_records = [generate_record() for _ in range(num_train)]
    test_records = [generate_record() for _ in range(num_test)]
    
    output_dir = Path(__file__).parent
    
    train_file = output_dir / "synthetic_payments.json"
    test_file = output_dir / "synthetic_test_set.json"
    
    with open(train_file, "w") as f:
        json.dump(train_records, f, indent=2)
        
    with open(test_file, "w") as f:
        json.dump(test_records, f, indent=2)
        
    print(f"Generated {num_train} train records in {train_file.name}")
    print(f"Generated {num_test} test records in {test_file.name}")

if __name__ == "__main__":
    main()
