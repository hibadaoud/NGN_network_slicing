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
t_h1_h4 = parse_iperf_file("tmp/h4_slice.txt")
t_h2_h5 = parse_iperf_file("tmp/h5_slice.txt")
# t_h3_h6 = parse_iperf_file("h6_slice.txt")

print("h1-h4 Throughput:", t_h1_h4)
print("h2-h5 Throughput:", t_h2_h5)
# print("h3-h6 Throughput:", t_h3_h6)


# Time axis: assuming 5-second intervals
x = [i * 5 for i in range(len(t_h1_h4))]

# --- Plot throughput ---
plt.figure(figsize=(10, 6))
plt.plot(x, t_h1_h4, color='g', label="h1 → h4 (5M requested)", marker="o")
plt.plot(x, t_h2_h5, color='b', label="h2 → h5 (5M requested)", marker="s")
# plt.plot(x, t_h3_h6, color='orange', label="h3 → h6 (4M requested)", marker="^")

# Plot total throughput
total_throughput = [sum(values) for values in zip(t_h1_h4, t_h2_h5)]
plt.plot(x, total_throughput, label="Total Throughput", color='black')

# Reference lines
plt.axhline(y=10, color='black', linestyle='--', label="Link Capacity (10M)")
plt.axhline(y=5, color='g', linestyle='--', label="Requested BW h1-h4 (5M)")
plt.axhline(y=5, color='b', linestyle='--', label="Requested BW h2-h5 (5M)")
# plt.axhline(y=4, color='orange', linestyle='--', label="Requested BW h3-h6 (4M)")

plt.title("UDP Throughput Over Time (Congested Link with Slicing)")
plt.xlabel("Time (s)")
plt.ylabel("Throughput (Mbps)")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()
