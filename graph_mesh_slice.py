from datetime import datetime
import matplotlib.pyplot as plt
import re
import os

def parse_iperf_file(filename):
    times = []
    throughput = []

    pattern = re.compile(
        r'\[\s*\d+\]\s+(\d+\.\d+)-(\d+\.\d+)\s+sec\s+[\d\.]+\s+\w+\s+([\d\.]+)\s+Mbits/sec'
    )

    with open(filename) as f:
        for line in f:
            match = pattern.search(line)
            if match:
                try:
                    start = float(match.group(1))
                    end = float(match.group(2))
                    value = float(match.group(3))

                    if end - start <= 5.1:  # scarta i riepiloghi finali
                        mid = (start + end) / 2
                        times.append(mid)
                        throughput.append(value)

                except ValueError:
                    continue

    return times, throughput


# Parse file
t_x1, t_h1_h2 = parse_iperf_file("netbench/h2_server_slice.txt")
t_x2, t_h4_h3 = parse_iperf_file("netbench/h3_server_slice.txt")

# In caso abbiano lunghezze diverse, trunca alla min
min_len = min(len(t_x1), len(t_x2))
t_x = t_x1[:min_len]
t_h1_h2 = t_h1_h2[:min_len]
t_h4_h3 = t_h4_h3[:min_len]

print("h1-h2 Throughput:", t_h1_h2)
print("h4-h3 Throughput:", t_h4_h3)

# --- Plot throughput ---
plt.figure(figsize=(10, 6))
plt.plot(t_x, t_h1_h2, color='g', label="h1 → h2 (6M requested)", marker="o")
plt.plot(t_x, t_h4_h3, color='b', label="h4 → h3 (4M requested)", marker="s")

# Plot total throughput
total_throughput = [a + b for a, b in zip(t_h1_h2, t_h4_h3)]
plt.plot(t_x, total_throughput, label="Total Throughput", color='black')

# Reference lines
plt.axhline(y=10, color='black', linestyle='--', label="Link Capacity (10M)")
plt.axhline(y=6, color='g', linestyle='--', label="Requested BW h1-h2 (6M)")
plt.axhline(y=4, color='b', linestyle='--', label="Requested BW h4-h3 (4M)")

plt.title("UDP Throughput Over Time (Congested Link with Slicing)")
plt.xlabel("Time (s)")
plt.ylabel("Throughput (Mbps)")
plt.legend()
plt.grid(True)
plt.tight_layout()

# Salva il grafico con timestamp
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
filename = f"netbench/throughput_plot_mesh_{timestamp}.png"
plt.savefig(filename)

plt.show()
print(f"Plot saved as {filename}")
