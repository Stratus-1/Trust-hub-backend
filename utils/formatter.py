from datetime import datetime

def format_establishment_date(date_str: str) -> str:
    """Returns a standard readable date: '9 July 2025'"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return date.strftime("%-d %B %Y")  # Linux/macOS: %-d | Use %#d on Windows if needed

def format_legal_establishment_date(date_str: str) -> str:
    """Returns a legal date format: '9th day of July 2025'"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    day = date.day
    # Determine ordinal suffix
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} day of {date.strftime('%B %Y')}"

def generate_trust_name(user_input: str) -> str:
    return f"The {user_input} Hong Kong Foreign Trust"

def generate_trust_number(latest_id: int) -> str:
    year_suffix = datetime.now().strftime("%y")
    return f"32{latest_id:02}/{year_suffix}"
