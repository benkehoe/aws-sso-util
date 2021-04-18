# Example formatter for aws-sso-util configure populate
# This script is roughly equivalent to the default profile formatting
# You would use this like:
# aws-sso-util configure populate --profile-name-process "python3 profile_name_format_process.py"

import sys

# separate fields with a dot
sep = "."

# Unpack the inputs, which are always in this order
(
    account_name,
    account_id,
    role_name,
    region_name,
    short_region_name,
) = sys.argv[1:6]

region_index, num_regions = (int(v) for v in sys.argv[6:8])

fields = [account_name, role_name]

# If this is the first (or only) region, consider it the default and don't add it to the profile name
# If it's not the first region, use the short region name (a 5-character abbreviation)
if region_index != 0:
    fields.append(short_region_name)

# Print profile name to stdout
print(sep.join(fields))
