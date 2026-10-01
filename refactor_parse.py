import re

with open('garmin_service.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Refactor _parse_rhr_and_sleep
old_rhr = r"""        score = sleep_dto.get\('sleepScores', \{\}\).get\('overall', \{\}\).get\('value'\)
        result\['sleep_score'\] = f"\{score\}/100" if score is not None else NO_DATA

        deep_secs = sleep_dto.get\('deepSleepSeconds'\)
        if deep_secs is not None:
            result\['deep_sleep'\] = f"\{deep_secs // 3600\}h \{\(deep_secs % 3600\) // 60\}m"

        rem_secs = sleep_dto.get\('remSleepSeconds'\)
        if rem_secs is not None:
            result\['rem_sleep'\] = f"\{rem_secs // 3600\}h \{\(rem_secs % 3600\) // 60\}m""""

new_rhr = """        result['sleep_score'] = _get_or_nodata(sleep_dto.get('sleepScores', {}).get('overall', {}), 'value', lambda x: f"{x}/100")
        result['deep_sleep'] = _get_or_nodata(sleep_dto, 'deepSleepSeconds', lambda x: f"{x // 3600}h {(x % 3600) // 60}m")
        result['rem_sleep'] = _get_or_nodata(sleep_dto, 'remSleepSeconds', lambda x: f"{x // 3600}h {(x % 3600) // 60}m")"""

text = re.sub(old_rhr, new_rhr, text)

# 2. Refactor avg_night_hr in _parse_rhr_and_sleep
old_avg_night = r"""        avg_hr_val = sleep_dto.get\('avgHeartRate'\)
        if avg_hr_val:
            avg_night_hr = f"\{int\(avg_hr_val\)\} bpm""""

new_avg_night = """        avg_night_hr = _get_or_nodata(sleep_dto, 'avgHeartRate', lambda x: f"{int(x)} bpm")
        avg_night_hr = avg_night_hr if avg_night_hr != NO_DATA else None"""

text = re.sub(old_avg_night, new_avg_night, text)

with open('garmin_service.py', 'w', encoding='utf-8') as f:
    f.write(text)
