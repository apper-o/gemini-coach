import re

with open('garmin_service.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Optimize avg_7d_str
old_avg = r"""            avg_7d_str = ""
            avg_7d = stats_raw.get\('lastSevenDaysAvgRestingHeartRate'\)
            if avg_7d is not None:
                diff = today_rhr - int\(avg_7d\)
                diff_sign = f"\+\{diff\}" if diff > 0 else f"\{diff\}"
                avg_7d_str = f" \(Średnia 7-dniowa: \{int\(avg_7d\)\} bpm, odchylenie: \{diff_sign\} bpm\)"
            rhr_str = f"\{today_rhr\} bpm\{avg_7d_str\}""""

new_avg = """            avg_7d = stats_raw.get('lastSevenDaysAvgRestingHeartRate')
            avg_7d_str = f" (Średnia 7-dniowa: {int(avg_7d)} bpm, odchylenie: {'+' if today_rhr - int(avg_7d) > 0 else ''}{today_rhr - int(avg_7d)} bpm)" if avg_7d is not None else ""
            rhr_str = f"{today_rhr} bpm{avg_7d_str}\""""

text = re.sub(old_avg, new_avg, text)

# 2. Optimize profile_str
old_profile = r"""        profile_str = ""
        if profile_m:
            profile_str = f" \(\{profile_m.group\(1\).strip\(\)\}\)"
        elif variant_m:
            profile_str = f" \(\{variant_m.group\(1\).strip\(\)\}\)""""

new_profile = """        profile_str = f" ({profile_m.group(1).strip()})" if profile_m else (f" ({variant_m.group(1).strip()})" if variant_m else "")"""

text = re.sub(old_profile, new_profile, text)

with open('garmin_service.py', 'w', encoding='utf-8') as f:
    f.write(text)
