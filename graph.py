import matplotlib.pyplot as plt

# Sample function to parse iperf output (assuming a standard format)
def parse_iperf_results(file_path):
    """
    Parses iperf output stored in a text file.
    Extracts the time intervals and throughput values.
    """
    time_intervals = []
    throughput_values = []

    with open(file_path, "r") as file:
        for line in file:
            parts = line.split()
            if len(parts) >= 7 and parts[1].startswith("0.0-"):  # Looks for throughput lines
                try:
                    time_intervals.append(float(parts[1].split('-')[-1]))  # Extracts the time interval (end time)
                    throughput_values.append(float(parts[-2]))  # Extracts the throughput value
                except ValueError:
                    continue  # Skip lines that don't match expected format

    return time_intervals, throughput_values

# Assume files are named "basic_results.txt" and "controlled_results.txt"
basic_results_file = "basic_results.txt"
controlled_results_file = "controlled_results.txt"

# Parse iperf output
basic_time, basic_throughput = parse_iperf_results(basic_results_file)
controlled_time, controlled_throughput = parse_iperf_results(controlled_results_file)

# Plot throughput over time
plt.figure(figsize=(10, 5))
plt.plot(basic_time, basic_throughput, label="Basic Controller (No Restriction)", marker="o")
plt.plot(controlled_time, controlled_throughput, label="Flow Allocator (Controlled)", marker="s")

plt.xlabel("Time (seconds)")
plt.ylabel("Throughput (Mbps)")
plt.title("Throughput Over Time Comparison")
plt.legend()
plt.grid(True)

# Display the plot
plt.show()
