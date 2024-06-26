import ipaddress


def is_local_ip(ip: str) -> bool:
    """Check if the IP address is local or remote

    IP addresses are considered local if
    - they are in the local IP ranges
    - they are in the Docker subnets

    Args:
        ip (str): The IP address to check

    Returns:
        bool: True if the IP address is local, False otherwise
    """

    # Define local IPs and Docker subnets
    local_ips = ["127.0.0.1", "::1"]
    docker_subnets = [
        ipaddress.ip_network("172.17.0.0/16"),
        ipaddress.ip_network("172.18.0.0/16"),
        ipaddress.ip_network("172.19.0.0/16"),
        ipaddress.ip_network("192.168.0.0/16"),
    ]

    # Check if the IP is in the local IPs
    if ip in local_ips:
        return True

    # Check if the IP is in any of the Docker subnets
    try:
        ip_addr = ipaddress.ip_address(ip)
        for subnet in docker_subnets:
            if ip_addr in subnet:
                return True
    except ValueError:
        # In case the IP address is not valid
        pass

    return False
