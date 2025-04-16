import re
from collections import defaultdict
import matplotlib.pyplot as plt

def parse_and_label_flows(filepath):
    flow_map = {}          # flow_id -> source IP
    flow_data = defaultdict(list)
    time_stamps = defaultdict(list)

    with open(filepath, 'r') as f:
        for line in f:
            # First, map flow IDs to sender IPs
            match_conn = re.search(r'\[\s*(\d+)\].*connected with ([\d\.]+) port', line)
            if match_conn:
                flow_id = match_conn.group(1)
                src_ip = match_conn.group(2)
                flow_map[flow_id] = src_ip

            # Then, collect throughput lines
            match_data = re.search(r'\[\s*(\d+)\]\s+[\d\.]+-\s*([\d\.]+) sec\s+[\d\.]+ MBytes\s+([\d\.]+) Mbits/sec', line)
            if match_data:
                flow_id = match_data.group(1)
                timestamp = float(match_data.group(2))
                throughput = float(match_data.group(3))

                label = flow_map.get(flow_id, f"Flow {flow_id}")
                flow_data[label].append(throughput)
                time_stamps[label].append(timestamp)
    print(flow_map)           
    print(flow_data)
    return flow_data, time_stamps

def plot_flow_data(flow_data, time_stamps):
    plt.figure(figsize=(10, 6))
    flow_data[list(flow_data.keys())[0]].pop()  # Remove the last element of the first flow
    flow_data[list(flow_data.keys())[1]].pop()  # Remove the last element of the first flow

    print(flow_data)
    x = [i * 5 for i in range(len(flow_data[list(flow_data.keys())[1]]))]  # Assuming all flows have the same length

    for label in flow_data:
        y = flow_data[label]
        plt.plot(x, y, label=label)
        
    # Plot total throughput
    total_throughput = [sum(values) for values in zip(*[flow_data[label] for label in flow_data])]
    plt.plot(x, total_throughput, label="Total Throughput", color='black')

    # Reference lines
    plt.axhline(y=10, color='black', linestyle='--', label="Link Capacity (10M)")
    plt.axhline(y=6, color='blue', linestyle='--', label="Requested BW h1-h2 (6M)")
    plt.axhline(y=4, color='orange', linestyle='--', label="Requested BW h3-h2 (4M)")

    plt.title("UDP Throughput at Server (h2)")
    plt.xlabel("Time (s)")
    plt.ylabel("Throughput (Mbps)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

# Run it
flows, times = parse_and_label_flows("tmp/h2_server_slice.txt")
plot_flow_data(flows, times)