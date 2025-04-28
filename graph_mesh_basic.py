from datetime import datetime
import matplotlib.pyplot as plt
import re

import re

def parse_iperf_file(filename):
    throughput = []

    # Regex per righe dettagliate per intervallo
    pattern = re.compile(
        r'\[\s*\d+\]\s+(\d+\.\d+)-\s*(\d+\.\d+)\s+sec\s+[\d\.]+\s+\w+\s+([\d\.]+)\s+Mbits/sec'
    )

    with open(filename) as f:
        for line in f:
            match = pattern.search(line)
            if match:
                try:
                    start = float(match.group(1))
                    end = float(match.group(2))
                    value = float(match.group(3))

                    # Ignora righe di "sommario" (es. 0.0–30.2 sec)
                    if end - start <= 5.1:  # tolleranza piccola su 5 secondi
                        throughput.append(value)

                except ValueError:
                    continue
    return throughput


# Read data
t_h1_h2 = parse_iperf_file("netbench/h2_server_basic.txt")
t_h4_h3 = parse_iperf_file("netbench/h3_server_basic.txt")
t_h6_h5 = parse_iperf_file("netbench/h5_server_basic.txt")

print("h1-h2 Throughput:", t_h1_h2)
print("h4-h3 Throughput:", t_h4_h3)
print("h6-h5 Throughput:", t_h6_h5)


# Time axis: assuming 5-second intervals
x = [i * 5 for i in range(len(t_h1_h2))]

# --- Plot throughput ---
plt.figure(figsize=(10, 6))
plt.plot(x, t_h1_h2, color='g', label="h1 → h2 (6M requested)", marker="o")
plt.plot(x, t_h4_h3, color='b', label="h4 → h3 (4M requested)", marker="s")
plt.plot(x, t_h6_h5, color='orange', label="h6 → h5 (4M requested)", marker="^")

# Plot total throughput
total_throughput = [sum(values) for values in zip(t_h1_h2, t_h4_h3, t_h6_h5)]
plt.plot(x, total_throughput, label="Total Throughput", color='black')

# Reference lines
plt.axhline(y=10, color='black', linestyle='--', label="Link Capacity (10M)")
plt.axhline(y=6, color='g', linestyle='--', label="Requested BW h1-h2 (6M)")
plt.axhline(y=4, color='b', linestyle='--', label="Requested BW h4-h3 (4M)")
plt.axhline(y=2, color='orange', linestyle='--', label="Requested BW h6-h5 (4M)")

plt.title("UDP Throughput Over Time (Congested Link without Slicing)")
plt.xlabel("Time (s)")
plt.ylabel("Throughput (Mbps)")
plt.legend()
plt.grid(True)
plt.tight_layout()

# Salva il grafico con timestamp
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
filename = f"netbench/throughput_plot_basic_{timestamp}.png"
plt.savefig(filename)

plt.show()
print(f"Plot saved as {filename}")
