"""Project transport policy: explicit rate rejection retries wait five seconds."""
RATE_LIMIT_RETRY_SECONDS = 5
REQUEST_GAP_SECONDS = 5
MAX_RATE_LIMIT_RETRIES = 5

def is_rate_limited(message, status_code=None):
    if status_code == 429:
        return True
    message = str(message).lower()
    return any(marker in message for marker in (
        'http 429', 'status=429', 'limit_burst_rate', 'throttl',
        'ratequota', 'rate limit', 'ratelimit', 'rate_limit'))
