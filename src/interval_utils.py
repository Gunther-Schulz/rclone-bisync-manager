def parse_interval(interval_str):
    interval_str = interval_str.lower()
    if interval_str == 'hourly':
        return 3600  # 1 hour in seconds
    elif interval_str == 'daily':
        return 86400  # 24 hours in seconds
    elif interval_str == 'weekly':
        return 604800  # 7 days in seconds
    elif interval_str == 'monthly':
        return 2592000  # 30 days in seconds (approximate)
    elif interval_str == 'yearly':
        return 31536000  # 365 days in seconds (approximate)

    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])

        if unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600
        elif unit == 'd':
            return value * 86400
        elif unit == 'w':
            return value * 604800
        elif unit == 'y':
            return value * 31536000
        else:
            raise ValueError(f"Invalid interval unit: {unit}")
    except (ValueError, IndexError):
        raise ValueError(f"Invalid interval format: {interval_str}")
