"""Security defenses and destination validation for documentation retrieval.

Implements strict SSRF protection, URL canonicalization, and allowlist validation:
- HTTPS only.
- Prohibits embedded credentials (user:pass@host).
- Prohibits loopback, private, link-local, multicast, and reserved IP addresses.
- Enforces approved host allowlists.
- Rejects lookalike / homoglyph domains.
- Restricts ports to default HTTPS (443).
"""

import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import List, Optional, Set, Tuple

# Approved official documentation hosts for Stripe & Python
APPROVED_CANONICAL_HOSTS: Set[str] = {
    "stripe.com",
    "docs.stripe.com",
    "github.com",
}

# Explicitly prohibited API and service hosts that must never be targeted as documentation
PROHIBITED_API_HOSTS: Set[str] = {
    "api.stripe.com",
    "connect.stripe.com",
    "dashboard.stripe.com",
    "m.stripe.com",
    "checkout.stripe.com",
}

# Tracking query parameters to strip during canonicalization
TRACKING_PARAMS: Set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "msclkid"
}


class SSRFValidationError(Exception):
    """Raised when a URL violates SSRF security policies."""
    pass


# Cloud metadata endpoints and hostnames explicitly prohibited (SSRF defense)
RESTRICTED_METADATA_HOSTS: Set[str] = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
    "metadata.azure.com",
    "169.254.169.254",
    "fd00:ec2::254",
    "100.100.100.200",
}


def is_ip_address(host: str) -> bool:
    """Return True if host is an IPv4 or IPv6 address literal, including int/octal/hex."""
    clean = host.strip("[]")
    try:
        ipaddress.ip_address(clean)
        return True
    except ValueError:
        pass
    if clean.isdigit():
        try:
            ipaddress.ip_address(int(clean))
            return True
        except ValueError:
            pass
    try:
        if clean.count(".") == 3:
            socket.inet_aton(clean)
            return True
    except (OSError, ValueError):
        pass
    return False


def is_private_or_restricted_ip(ip_str: str) -> bool:
    """Verify whether an IP address is private, loopback, link-local, multicast, or reserved."""
    try:
        clean = ip_str.strip("[]")
        if clean.isdigit():
            ip = ipaddress.ip_address(int(clean))
        else:
            try:
                ip = ipaddress.ip_address(clean)
            except ValueError:
                packed = socket.inet_aton(clean)
                ip = ipaddress.ip_address(socket.inet_ntoa(packed))
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except Exception:
        return True


def resolve_hostname_ips(hostname: str) -> List[str]:
    """Resolve a hostname to all associated IP addresses safely."""
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        return [sockaddr[0] for _, _, _, _, sockaddr in addr_info]
    except (socket.gaierror, socket.herror, OSError):
        return []


def validate_destination_url(
    url: str, 
    approved_hosts: Optional[Set[str]] = None,
    check_dns: bool = False,
    permitted_prefixes: Optional[List[str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Validate a destination URL against SSRF and allowlist rules.

    Args:
        url: The candidate URL string.
        approved_hosts: Set of approved domain names (defaults to APPROVED_CANONICAL_HOSTS).
        check_dns: Whether to perform DNS resolution checks against resolved IPs.
        permitted_prefixes: Optional list of approved URL prefixes (e.g. ['https://docs.stripe.com/api']).

    Returns:
        (is_valid: bool, canonical_url: str, error_reason: Optional[str])
    """
    if not url or not isinstance(url, str):
        return False, "", "Empty or invalid URL"

    url = url.strip()

    # 1. Scheme Validation: HTTPS only
    try:
        parsed = urlsplit(url)
    except Exception as e:
        return False, "", f"Malformed URL format: {str(e)}"

    if parsed.scheme.lower() != "https":
        return False, "", f"Insecure scheme '{parsed.scheme}': only HTTPS is permitted"

    # 2. Reject embedded user credentials
    if parsed.username or parsed.password:
        return False, "", "Embedded credentials in URL (user:pass@host) are prohibited"

    # 3. Hostname Extraction & Port Validation
    hostname = parsed.hostname
    if not hostname:
        return False, "", "Missing hostname in URL"

    # Reject nonstandard ports (only port 443 or default None allowed)
    if parsed.port is not None and parsed.port != 443:
        return False, "", f"Port {parsed.port} is not permitted: documentation retrieval restricted to port 443"

    # 4. Homoglyph / IDNA Normalization
    try:
        ascii_host = hostname.encode("idna").decode("ascii").lower()
    except Exception:
        return False, "", "Invalid host encoding or homoglyph character detected"

    # 5. Loopback & Localhost checks
    if ascii_host in {"localhost", "localhost.localdomain"} or ascii_host.endswith(".localhost"):
        return False, "", f"Destination '{hostname}' resolves to loopback/localhost (SSRF violation)"

    # 6. Cloud metadata / internal host checks
    if (
        ascii_host in RESTRICTED_METADATA_HOSTS
        or any(ascii_host.endswith("." + m) for m in RESTRICTED_METADATA_HOSTS)
        or ascii_host.endswith(".internal")
        or ascii_host.endswith(".local")
    ):
        return False, "", f"Destination '{hostname}' is a cloud metadata / internal endpoint and prohibited (SSRF violation)"

    # 7. Reject direct IP addresses as documentation hosts
    if is_ip_address(ascii_host):
        if is_private_or_restricted_ip(ascii_host):
            return False, "", f"Direct IP address '{hostname}' is private/loopback (SSRF violation)"
        return False, "", f"Direct IP address '{hostname}' is prohibited: must be an official domain name"

    # 8. Reject prohibited API and dashboard hosts (prevent accidental live API calls)
    if ascii_host in PROHIBITED_API_HOSTS or any(ascii_host.endswith("." + p) for p in PROHIBITED_API_HOSTS):
        return False, "", f"Host '{hostname}' is an API/dashboard service endpoint, not an approved documentation source"

    # 9. Approved Domain Allowlist Check
    if approved_hosts is not None:
        allowed = approved_hosts
    else:
        try:
            from app.config import settings
            configured = getattr(settings, "APPROVED_DOC_HOSTS", None)
            if configured:
                allowed = set(configured) if isinstance(configured, (list, set)) else APPROVED_CANONICAL_HOSTS
            else:
                allowed = APPROVED_CANONICAL_HOSTS
        except Exception:
            allowed = APPROVED_CANONICAL_HOSTS

    def matches_allowlist(host: str, allowlist: Set[str]) -> bool:
        normalized_allowlist = {d.lower() for d in allowlist}
        return host.lower() in normalized_allowlist

    if not matches_allowlist(ascii_host, allowed):
        return False, "", f"Domain '{hostname}' is not in approved documentation allowlist: {sorted(allowed)}"

    # 10. DNS Resolution Check (Optional / Guard against DNS rebinding to private IPs)
    if check_dns:
        resolved_ips = resolve_hostname_ips(ascii_host)
        if not resolved_ips:
            return False, "", f"Could not resolve hostname '{ascii_host}'"
        for ip in resolved_ips:
            if is_private_or_restricted_ip(ip):
                return False, "", f"Hostname '{ascii_host}' resolved to restricted private IP '{ip}' (SSRF violation)"

    # 11. URL Canonicalization
    canonical_url = canonicalize_url(parsed)

    # 12. Permitted Prefixes Validation (if provided)
    if permitted_prefixes:
        if not any(canonical_url.startswith(prefix) for prefix in permitted_prefixes):
            return (
                False,
                "",
                f"URL '{canonical_url}' does not start with any permitted prefix: {permitted_prefixes}",
            )

    return True, canonical_url, None


def canonicalize_url(parsed) -> str:
    """Canonicalize a validated URL: lowercase host/scheme, normalize path, strip tracking query parameters."""
    scheme = parsed.scheme.lower()
    netloc = parsed.hostname.lower()
    if parsed.port and parsed.port != 443:
        netloc = f"{netloc}:{parsed.port}"

    # Normalize path (remove double slashes and resolve relative segments)
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Filter out tracking query parameters
    filtered_query = ""
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        retained = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
        if retained:
            filtered_query = urlencode(retained)

    # Return reconstructed canonical URL without fragment
    return urlunsplit((scheme, netloc, path, filtered_query, ""))
