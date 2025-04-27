# commands.py
import os
import json
import asyncio
import sys
import time
import websockets
import psutil
from dotenv import load_dotenv

load_dotenv()
TEST_MODE = os.environ.get("TEST_MODE", "slicing")

WS_SERVER_CONTROLLER_URI = "ws://127.0.0.1:8765"
WS_SERVER_MININET_URI = "ws://127.0.0.1:9876"

def get_mininet_macs():
    mac_file = "/tmp/host_info.json"
    if not os.path.exists(mac_file):
        print("MAC address file not found. Make sure Mininet is running and generating the file.")
        return {}
    with open(mac_file, "r") as f:
        hosts_mac = json.load(f)
    for host, mac_info in hosts_mac.items():
        mac_info['name'] = host
    return hosts_mac

def select_hosts(hosts_mac):
    print("\nSelect the hosts for packet transmission:\n")
    host_list = list(hosts_mac.items())
    for i, (host, mac_info) in enumerate(host_list):
        print(f"{i + 1}. {host} - {mac_info}")
    try:
        src_index = int(input("\nSelect the source host (1,2,...): ")) - 1
        dst_index = int(input("Select the destination host (1,2,...): ")) - 1
        if src_index == dst_index:
            print("Error: the source and destination hosts must be different.")
            return None, None
        src = host_list[src_index][1]
        dst = host_list[dst_index][1]
        return src, dst
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None, None

def run_async(coro):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)

async def send_ws_controller_request(data):
    async with websockets.connect(WS_SERVER_CONTROLLER_URI) as websocket:
        await websocket.send(json.dumps(data))
        response = await websocket.recv()
        return json.loads(response)

def send_mininet_exec_command(host, command, no_output=False):
    async def _send_and_stream():
        try: 
            async with websockets.connect(WS_SERVER_MININET_URI) as websocket:
                await websocket.send(json.dumps({
                    "command": "exec",
                    "host": host,
                    "cmd": command,
                    "no_output": no_output
                }))
                
                if no_output:
                    response = await websocket.recv()
                    data = json.loads(response)
                    print(data.get("output"))
                    return
                
                while True:
                    response = await websocket.recv()
                    data = json.loads(response)

                    if data.get("status") == "stream":
                        print(data.get("output"), flush=True)
                    elif data.get("status") == "done":
                        print(data.get("output"), flush=True)
                        break
                    elif data.get("status") == "error":
                        print(f"Error executing command: {data.get('reason')}")
                        break
        except Exception as e:
            print(f"❌ Connection failed: {e}")
        finally:
            await asyncio.sleep(0.1)
    run_async(_send_and_stream())

def send_websocket_allocate_request(src, dst, bandwidth=8):
    data = {"command": "allocate_flow", "src": src['mac'], "dst": dst['mac'], "bandwidth": bandwidth}
    print(f"\nSending WebSocket request: {data}")
    response = run_async(send_ws_controller_request(data))
    if response.get("status") == "success":
        print("Flow reserved successfully!")
    else:
        print(f"Error in flow reservation: {response.get('reason', 'Unknown error')}")

def send_websocket_delete_request(src, dst):
    data = {"command": "delete_flow", "src": src['mac'], "dst": dst['mac']}
    print(f"\nSending WebSocket request: {data}")
    response = run_async(send_ws_controller_request(data))
    if response.get("status") == "success":
        print("Flow deleted successfully!")
    else:
        print(f"Error in flow deletion: {response.get('reason', 'Unknown error')}")

def send_websocket_dump_flows_request(switch):
    data = {"command": "dump_flows", "switch": switch}
    print(f"\nSending WebSocket request: {data}")
    response = run_async(send_ws_controller_request(data))
    if response.get("status") == "success":
        print("Switch flow table: \n", response.get("result"))
    else:
        print(f"Error in flow dump: {response.get('reason', 'Unknown error')}")

def send_websocket_show_reservation_request():
    data = {"command": "show_reservation"}
    print(f"\nSending WebSocket request: {data}")
    response = run_async(send_ws_controller_request(data))
    if response.get("status") == "success":
        print("Reservation table: \n", response.get("result"))
    else:
        print(f"Error in showing Reservation table: {response.get('reason', 'Unknown error')}")

def handle_allocate(hosts_mac):
    src, dst = select_hosts(hosts_mac)
    if src and dst:
        try:
            bandwidth = int(input("Enter the bandwidth (Mbps): "))
        except ValueError:
            print("Invalid bandwidth value, defaulting to 8 Mbps.")
            bandwidth = 8
        send_websocket_allocate_request(src, dst, bandwidth)

def handle_delete(hosts_mac):
    src, dst = select_hosts(hosts_mac)
    if src and dst:
        send_websocket_delete_request(src, dst)

def handle_dump(hosts_mac):
    switch = input("Enter switch name: ")
    try:
        import subprocess
        dump = subprocess.check_output(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch])
        print("Switch flow table: \n", dump.decode("utf-8"))
    except Exception as e:
        print(f"Error dumping flows: {e}")

def handle_ping(hosts_mac):
    src, dst = select_hosts(hosts_mac)
    if src and dst:
        print(f"Pinging {dst['name']} from {src['name']}...")
        send_mininet_exec_command(src['name'], f"ping -c 2 {dst['ip']}")

def show_progress(duration):
    print("\nRunning iperf test:")
    for i in range(duration):
        print(f"[{i + 1}/{duration}] seconds", end="\r", flush=True)
        time.sleep(1)
    print("\nTest completed. Generating plot...\n")

def show_progress_with_cpu(duration):
    print("\nRunning iperf test with system monitoring:\n")
    for i in range(duration):
        cpu = psutil.cpu_percent(interval=0.9)
        sys.stdout.write(f"\r[{i + 1}/{duration}] sec | CPU Usage: {cpu:.1f}%   ")
        sys.stdout.flush()
    print("\nTest completed. Generating plot...\n")

def generate_plot():
    # Call one script if the test is in slicing mode, otherwise call a different script
    if TEST_MODE == "slicing":
        os.system("python3 graph_mesh_slice.py")
    elif TEST_MODE == "basic":
        os.system("python3 graph_mesh_basic.py")
    else:
        print("Invalid TEST_MODE. Please set it to 'slicing' or 'basic'.")
    return

def iperf_test(hosts_mac):
    if TEST_MODE == "slicing":
        iperf_test_slice(hosts_mac)
    elif TEST_MODE == "basic":
        iperf_test_basic(hosts_mac)
    else:
        print("Invalid TEST_MODE. Please set it to 'slicing' or 'basic'.")

def iperf_test_slice(hosts_mac):
    os.makedirs("netbench", exist_ok=True)
    
    test_duration = 60
    sample_interval = 5
    
    # kill any existing iperf processes
    send_mininet_exec_command("h2", "pkill iperf")
    send_mininet_exec_command("h3", "pkill iperf")
    
    send_mininet_exec_command("h2", f"iperf -u -s -b 6M -i {sample_interval} > netbench/h2_server_slice.txt", no_output=True)
    send_mininet_exec_command("h3", f"iperf -u -s -b 4M -i {sample_interval} > netbench/h3_server_slice.txt", no_output=True)
    send_mininet_exec_command("h1", f"iperf -c {hosts_mac['h2']['ip']} -u -b 6M -t {test_duration}", no_output=True)
    send_mininet_exec_command("h4", f"iperf -c {hosts_mac['h3']['ip']} -u -b 4M -t {test_duration}", no_output=True)
    show_progress_with_cpu(test_duration + 5)
    # show_progress(test_duration)
    generate_plot()

def iperf_test_basic(hosts_mac):
    os.makedirs("netbench", exist_ok=True)
    
    test_duration = 120
    sample_interval = 5
    
    send_mininet_exec_command("h2", "pkill iperf")
    send_mininet_exec_command("h3", "pkill iperf")
    send_mininet_exec_command("h5", "pkill iperf")
    
    send_mininet_exec_command("h2", f"iperf -u -s -b 6M -i {sample_interval} > netbench/h2_server_basic.txt", no_output=True)
    send_mininet_exec_command("h3", f"iperf -u -s -b 4M -i {sample_interval} > netbench/h3_server_basic.txt", no_output=True)
    send_mininet_exec_command("h5", f"iperf -u -s -b 2M -i {sample_interval} > netbench/h5_server_basic.txt", no_output=True)
    send_mininet_exec_command("h1", f"iperf -c {hosts_mac['h2']['ip']} -u -b 6M -t {test_duration}", no_output=True)
    send_mininet_exec_command("h4", f"iperf -c {hosts_mac['h3']['ip']} -u -b 4M -t {test_duration}", no_output=True)
    send_mininet_exec_command("h6", f"iperf -c {hosts_mac['h5']['ip']} -u -b 2M -t {test_duration}", no_output=True)
    show_progress(test_duration + 5)
    generate_plot()

def clear_screen():
    os.system("clear" if os.name == "posix" else "cls")
    # print("tester> ", end="", flush=True)

def handle_help(_):
    print("\nAvailable commands:\n")
    for cmd, info in commands.items():
        print(f"  {cmd:<12} {info['description']}")

commands = {
    "allocate": {"description": "Allocate a new flow", "handler": handle_allocate},
    "delete": {"description": "Delete an existing flow", "handler": handle_delete},
    "dump": {"description": "Dump flows from a switch", "handler": handle_dump},
    "show": {"description": "Show flow reservation table", "handler": lambda _: send_websocket_show_reservation_request()},
    "ping": {"description": "Ping between two hosts", "handler": handle_ping},
    "iperf": {"description": "Run iperf based on TEST_MODE", "handler": iperf_test},
    "help": {"description": "Show this help menu", "handler": handle_help},
    "clear": {"description": "Clear the screen", "handler": lambda _: clear_screen()},
    "exit": {"description": "Exit the CLI", "handler": lambda _: exit()}
}
