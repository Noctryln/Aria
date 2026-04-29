import time
from datetime import datetime

def get_uptime_str(start_time: float) -> str:
    secs = int(time.time() - start_time)
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}h{m}m{s}s"
    elif m > 0: return f"{m}m{s}s"
    else: return f"{s}s"

def get_current_datetime_indonesian() -> str:
    now = datetime.now()
    days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    months = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    day_name = days[now.weekday()]
    month_name = months[now.month - 1]
    return f"{day_name}, {now.day} {month_name} {now.year} {now.strftime('%H:%M:%S')}"

