from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import swisseph as swe
import pytz
from timezonefinder import TimezoneFinder
from typing import Optional

app = FastAPI(title="Vedic Astro-Numerology API v2.0")

tf = TimezoneFinder()

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. NUMEROLOGY ENGINE (Chaldean & Cycles)
# ==========================================

CHALDEAN_MAP = {
    'A': 1, 'I': 1, 'J': 1, 'Q': 1, 'Y': 1,
    'B': 2, 'K': 2, 'R': 2,
    'C': 3, 'G': 3, 'L': 3, 'S': 3,
    'D': 4, 'M': 4, 'T': 4,
    'E': 5, 'H': 5, 'N': 5, 'X': 5,
    'U': 6, 'V': 6, 'W': 6,
    'O': 7, 'Z': 7,
    'F': 8, 'P': 8
}

# Vedic Numerology Friendship Map (1-9)
NUMERO_FRIENDS = {
    1: [1, 2, 3, 9],
    2: [1, 5, 3],
    3: [1, 2, 9, 5, 7],
    4: [1, 5, 6, 8],
    5: [1, 4, 6],
    6: [5, 8, 4, 7],
    7: [1, 3, 6, 5],
    8: [5, 6, 4],
    9: [1, 2, 3]
}

def reduce_to_single_digit(num: int) -> int:
    if num == 0: return 0
    return (num - 1) % 9 + 1

def check_master_number(compound: int) -> Optional[int]:
    if compound in [11, 22, 33, 44]:
        return compound
    return None

def calculate_moolank(day: int):
    # For day only, 11 and 22 are master numbers.
    if day in [11, 22]:
        return {"single": reduce_to_single_digit(day), "compound": day, "master": day}
    return {"single": reduce_to_single_digit(day), "compound": day, "master": None}

def calculate_name_number(name: str):
    name = name.upper()
    total = sum(CHALDEAN_MAP.get(char, 0) for char in name)
    return {"single": reduce_to_single_digit(total), "compound": total, "master": check_master_number(total)}

def calculate_bhagyank(day: int, month: int, year: int):
    # For full date total, 11, 22, 33 are master numbers.
    total = day + month + sum(int(digit) for digit in str(year))
    return {"single": reduce_to_single_digit(total), "compound": total, "master": check_master_number(total)}

def calculate_yearly_period(day: int, month: int, predict_year: int):
    # Personal Year = Day + Month + Predict Year
    total = day + month + sum(int(digit) for digit in str(predict_year))
    return {"single": reduce_to_single_digit(total), "compound": total, "master": check_master_number(total)}

# ==========================================
# 2. ASTROLOGY ENGINE (Vimshottari Dasha)
# ==========================================

DASHA_LORDS = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = [7, 20, 6, 10, 7, 18, 16, 19, 17]
TOTAL_DASHA_YEARS = 120
NAKSHATRA_SPAN = 360 / 27 # 13 degrees 20 minutes

# Required to point to ephemeris files if installed locally, otherwise uses built-in Moshier
# swe.set_ephe_path('/path/to/ephe') 

def calculate_moon_longitude(year, month, day, hour, minute, lat, lon):
    # 1. Automatically find the timezone string (e.g., 'Asia/Kolkata') from coordinates
    tz_str = tf.timezone_at(lng=lon, lat=lat)
    if tz_str is None:
        tz_str = 'UTC' # Fallback if in the middle of the ocean
        
    local_tz = pytz.timezone(tz_str)
    
    # 2. Localize the birth time based on the exact city
    local_dt = local_tz.localize(datetime(year, month, day, hour, minute))
    
    # 3. Convert safely to UTC for the Swiss Ephemeris
    utc_dt = local_dt.astimezone(pytz.utc)
    utc_decimal_hour = utc_dt.hour + (utc_dt.minute / 60.0) + (utc_dt.second / 3600.0)
    
    # 4. Use the UTC date and time for the Julian Day calculation
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, utc_decimal_hour)
    
    # Set Sidereal mode to Lahiri Ayanamsa (Vedic standard)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    
    # Get Moon position (Planet 1) in Sidereal zodiac
    # swe.FLG_SWIEPH (ephemeris), swe.FLG_SIDEREAL (vedic)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    res, flag_ret = swe.calc_ut(jd, swe.MOON, flags)
    
    moon_long = res[0]
    return moon_long

def calculate_dasha(moon_long, birth_date: datetime):
    # Calculate Nakshatra (0 to 26)
    nakshatra_index = int(moon_long / NAKSHATRA_SPAN)
    
    # Dasha lord index (0 to 8) corresponds to the repeating cycle of 9 planets
    lord_index = nakshatra_index % 9
    
    # How far along the Moon is in the current Nakshatra
    nakshatra_start = nakshatra_index * NAKSHATRA_SPAN
    degrees_passed = moon_long - nakshatra_start
    fraction_passed = degrees_passed / NAKSHATRA_SPAN
    fraction_remaining = 1.0 - fraction_passed
    
    first_dasha_lord = DASHA_LORDS[lord_index]
    total_years_first_dasha = DASHA_YEARS[lord_index]
    
    # Balance of Dasha at birth (Days = Years * 365.25 for standard astronomical years)
    balance_years = total_years_first_dasha * fraction_remaining
    balance_days = balance_years * 365.25
    
    dasha_sequence = []
    current_date = birth_date
    
    # Calculate Maha Dashas starting from birth
    for i in range(9):
        current_idx = (lord_index + i) % 9
        lord = DASHA_LORDS[current_idx]
        years = DASHA_YEARS[current_idx]
        
        if i == 0:
            # First dasha uses the balance duration
            duration_days = balance_days
        else:
            duration_days = years * 365.25
            
        end_date = current_date + timedelta(days=duration_days)
        
        # Antar Dasha logic for the current Maha Dasha
        antar_dashas = []
        ad_start = current_date
        for j in range(9):
            ad_idx = (current_idx + j) % 9
            ad_lord = DASHA_LORDS[ad_idx]
            ad_years = DASHA_YEARS[ad_idx]
            
            # AD Span = (Maha Dasha Years * Antar Dasha Years) / 120
            ad_span_years = (years * ad_years) / TOTAL_DASHA_YEARS
            ad_span_days = ad_span_years * 365.25
            
            # Sukshma Dasha (Pratyantar)
            sukshma_dashas = []
            sd_start = ad_start
            for k in range(9):
                sd_idx = (ad_idx + k) % 9
                sd_lord = DASHA_LORDS[sd_idx]
                sd_years = DASHA_YEARS[sd_idx]
                
                # SD Span = (AD Years * SD Years) / 120
                sd_span_years = (ad_span_years * sd_years) / TOTAL_DASHA_YEARS
                sd_span_days = sd_span_years * 365.25
                sd_end = sd_start + timedelta(days=sd_span_days)
                
                sukshma_dashas.append({
                    "lord": sd_lord,
                    "start": sd_start.strftime("%Y-%m-%d"),
                    "end": sd_end.strftime("%Y-%m-%d")
                })
                sd_start = sd_end
            
            ad_end = ad_start + timedelta(days=ad_span_days)
            antar_dashas.append({
                "lord": ad_lord,
                "start": ad_start.strftime("%Y-%m-%d"),
                "end": ad_end.strftime("%Y-%m-%d"),
                "sukshma": sukshma_dashas
            })
            ad_start = ad_end

        dasha_sequence.append({
            "maha_lord": lord,
            "start": current_date.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
            "antar": antar_dashas
        })
        current_date = end_date
        
    return {
        "birth_moon_degree": round(moon_long, 4),
        "nakshatra_number": nakshatra_index + 1, # 1-indexed
        "balance_of_dasha": f"{first_dasha_lord} for {round(balance_years, 2)} years",
        "dasha_sequence": dasha_sequence
    }

# ==========================================
# 3. API ENDPOINTS
# ==========================================

class BirthData(BaseModel):
    name: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    lat: float
    lon: float

class PeriodPredictionData(BaseModel):
    dob_day: int
    dob_month: int
    predict_year: int
    predict_month: int = datetime.now().month
    predict_day: int = datetime.now().day

@app.post("/calculate")
def calculate_all(data: BirthData):
    # Numerology (with new v2.0 compound/master logic)
    moolank_info = calculate_moolank(data.day)
    bhagyank_info = calculate_bhagyank(data.day, data.month, data.year)
    name_info = calculate_name_number(data.name)
    
    # Calculate Personal Year for the *current* year automatically
    current_year = datetime.now().year
    personal_year_info = calculate_yearly_period(data.day, data.month, current_year)
    
    friendly_moolank = NUMERO_FRIENDS.get(moolank_info["single"], [])
    friendly_bhagyank = NUMERO_FRIENDS.get(bhagyank_info["single"], [])
    
    # Astrology (with new v2.0 flawless local timezone logic)
    birth_datetime = datetime(data.year, data.month, data.day, data.hour, data.minute)
    moon_long = calculate_moon_longitude(data.year, data.month, data.day, data.hour, data.minute, data.lat, data.lon)
    dasha_results = calculate_dasha(moon_long, birth_datetime)
    
    return {
        "numerology": {
            "moolank": moolank_info,
            "bhagyank": bhagyank_info,
            "name_number": name_info,
            "current_year_prediction": {
                "year": current_year,
                "personal_year": personal_year_info
            },
            "suitable_numbers": list(set(friendly_moolank + friendly_bhagyank))
        },
        "astrology": dasha_results
    }

@app.post("/predict-periods")
def predict_periods(data: PeriodPredictionData):
    """
    Calculates detailed numerological periods for a specific year and month.
    Vedic numerologist logic: Year is top-level cycle, Month is mid-level.
    """
    personal_year_info = calculate_yearly_period(data.dob_day, data.dob_month, data.predict_year)
    
    # Personal Month = Personal Year (single digit) + Predicted Month
    # Must use single digits for cyclical numerology steps
    personal_month_compound = personal_year_info["single"] + data.predict_month
    personal_month_single = reduce_to_single_digit(personal_month_compound)
    
    # Personal Day = Personal Month (single digit) + Predicted Day
    personal_day_compound = personal_month_single + data.predict_day
    personal_day_single = reduce_to_single_digit(personal_day_compound)
    
    return {
        "prediction_year": data.predict_year,
        "prediction_month_name": datetime(2000, data.predict_month, 1).strftime("%B"),
        "prediction_day": data.predict_day,
        "personal_year": personal_year_info,
        "personal_month": {
            "single": personal_month_single,
            "compound": personal_month_compound
        },
        "personal_day": {
            "single": personal_day_single,
            "compound": personal_day_compound
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)