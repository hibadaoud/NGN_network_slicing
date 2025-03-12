import yaml
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
import json

class DynamicTopo(Topo):
    def __init__(self, topology_file):
        """
        Initialize a custom network topology from a YAML file.
        The topology consists of hosts and switches connected via links. The YAML file should define
        the topology structure including hosts, switches, and their interconnections.
        """

        # Initializes the base topology
        Topo.__init__(self)

        # Load the topology from the YAML file
        with open(topology_file, 'r') as f:
            topology_data = yaml.safe_load(f)

        # Use different names to avoid overwriting base attributes
        self.hostNodes = {}
        self.switchNodes = {}

        # Add hosts
        for host in topology_data.get("hosts", {}):
            self.hostNodes[host] = self.addHost(host)

        # Add switches
        for switch in topology_data.get("switches", {}):
            self.switchNodes[switch] = self.addSwitch(switch, cls=OVSKernelSwitch, protocols='OpenFlow13')

        # Add links between hosts and switches
        for link in topology_data.get("links", {}).get("hosts", []):
            node1 = link["node1"]
            node2 = link["node2"]
            self.addLink(self.getNode(node1), self.getNode(node2))

        # Add links between switches with optional bandwidth
        for link in topology_data.get("links", {}).get("switches", []):
            node1 = link["node1"]
            node2 = link["node2"]
            bw = link.get("bw")  # Bandwidth (optional)
            if bw:
                self.addLink(self.getNode(node1), self.getNode(node2), bw=bw)
            else:
                self.addLink(self.getNode(node1), self.getNode(node2))

    def getNode(self, name):
        """Returns the reference of a host or switch given its name."""
        return self.hostNodes.get(name) or self.switchNodes.get(name)

def save_host_info(net: Mininet):
    """
    Collects and saves the MAC addresses and connected ports of the hosts in a JSON file.
    """
    host_info = {}

    for host in net.hosts:
        mac = host.MAC()
        intf = host.intfList()[0]
        link = intf.link
        if link:
            connected_switch = link.intf2.node.name  # Store switch name instead of number
            connected_port = int(link.intf2.name.split("eth")[-1])

            host_info[host.name] = {
                "mac": mac,
                "connected_switch": connected_switch,
                "src_port": connected_port,
            }

    with open("/tmp/host_info.json", "w") as f:
        json.dump(host_info, f, indent=4)

    print("Host info (MAC and port) saved to /tmp/host_info.json")

def save_switch_links_info(net: Mininet):
    """
    Collects and saves the bandwidth information for switch-to-switch links in a JSON file.
    """
    switch_links = {}

    for link in net.links:
        if not isinstance(link, TCLink):  
            continue  # Skip non-TC links

        node1, node2 = link.intf1.node, link.intf2.node

        if isinstance(node1, OVSKernelSwitch) and isinstance(node2, OVSKernelSwitch):
            switch1, switch2 = node1.name, node2.name
            link_pair = tuple(sorted([switch1, switch2]))
            link_pair_reversed = tuple(reversed(link_pair))

            if link_pair not in switch_links:
                bw = link.intf1.params.get('bw') or link.intf2.params.get('bw') or "N/A"
                switch_links["-".join(link_pair)] = {"bandwidth": bw}
                
            if link_pair_reversed not in switch_links:
                bw = link.intf1.params.get('bw') or link.intf2.params.get('bw') or "N/A"
                switch_links["-".join(link_pair_reversed)] = {"bandwidth": bw}

    # Save to a JSON file
    with open("/tmp/switch_links_info.json", "w") as f:
        json.dump(switch_links, f, indent=4)

    print("Switch links info saved to /tmp/switch_links_info.json")

def run_topology():
    # Set log level
    setLogLevel('info')

    # Load the topology dynamically from YAML
    topology_file = "topology.yaml"
    topo = DynamicTopo(topology_file)

    # Create network with remote controller
    net = Mininet(topo=topo, link=TCLink, controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653), autoSetMacs=True, autoStaticArp=True)

    # Start the network
    net.start()

    # Save the MAC addresses of the hosts
    save_host_info(net)
    
    save_switch_links_info(net)

    # Open the Mininet CLI
    CLI(net)

    # Stop the network when CLI exits
    net.stop()


if __name__ == '__main__':
    run_topology()
