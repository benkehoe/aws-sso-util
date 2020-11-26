import sys
sep = "."
(
    account_name, account_id,
    role_name,
    region_name, short_region_name
) = sys.argv[1:6]
region_index = int(sys.argv[6])
region_str = "" if region_index == 0 else sep + short_region_name
print(account_name + sep + role_name + region_str)
