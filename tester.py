
import subprocess
import json
import re
import os

CONTROLLER_URL = "http://127.0.0.1:8080/allocate_flow"

def get_mininet_macs():
    """
    Reads MAC addresses from a pre-generated file by Mininet.
    """
    mac_file = "/tmp/host_info.json"

    if not os.path.exists(mac_file):
        print("MAC address file not found. Ensure Mininet is running and generating the file.")
        return {}

    with open(mac_file, "r") as f:
        hosts_mac = json.load(f)

    print("Host MACs loaded from file:", hosts_mac)
    return hosts_mac

def extract_mac(ifconfig_output):
    """
    Extracts the MAC address from the ifconfig output.
    """
    match = re.search(r'ether ([0-9a-fA-F:]{17})', ifconfig_output)
    return match.group(1) if match else None


def select_hosts(hosts_mac):
    """
    Allows selection of source and destination hosts.
    """
    print("\nSelect the hosts for packet transmission:\n")
    host_list = list(hosts_mac.items())

    for i, (host, mac) in enumerate(host_list):
        print(f"{i + 1}. {host} - {mac}")

    try:
        src_index = int(input("\nSelect the source host (1/2/...): ")) - 1
        dst_index = int(input("Select the destination host (1/2/...): ")) - 1

        if src_index == dst_index:
            print("Error: Source and destination hosts must be different.")
            return None, None

        src = host_list[src_index][1]
        dst = host_list[dst_index][1]
        
        return src, dst
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None, None


def send_curl_request(src, dst, bandwidth=8):
    """
    Sends a curl request to the REST controller to allocate the flow.
    """
    data = {
        "src": src['mac'],
        "src_switch": src['connected_switch'],
        "src_port": src['src_port'],
        "dst": dst['mac'],
        "bandwidth": bandwidth
    }

    curl_cmd = f"curl -X POST -H 'Content-Type: application/json' -d '{json.dumps(data)}' {CONTROLLER_URL}"
    print(f"\nExecuting: {curl_cmd}\n")

    result = subprocess.run(curl_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = result.stdout.decode().strip()
    stderr = result.stderr.decode().strip()

    if stderr:
        print("Curl error:", stderr)

    try:
        response = json.loads(stdout)
        if response.get("status") == "success":
            print("Flow successfully allocated!")
        else:
            print(f"Error during flow allocation: {response.get('reason', 'Unknown error')}")
    except json.JSONDecodeError:
        print("Error decoding JSON response:", stdout)


def main():
    hosts_mac = get_mininet_macs()

    if not hosts_mac:
        print("No MAC addresses found. Ensure Mininet is running.")
        return

    src, dst = select_hosts(hosts_mac)

    if src and dst:
        send_curl_request(src, dst)


if __name__ == "__main__":
    main()
