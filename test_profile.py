import json
from coach_prompts import load_personal_data, build_user_profile

config = load_personal_data()
profile = build_user_profile(config)
print(json.dumps(profile, indent=4, ensure_ascii=False))
