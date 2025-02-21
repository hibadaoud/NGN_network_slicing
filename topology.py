from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink

import json

class MyTopo(Topo):
    def __init__(self):
        # Initialize topology
        Topo.__init__(self)

        # Add hosts
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        h4 = self.addHost('h4')

        # Add switches
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, protocols='OpenFlow13')
        s2 = self.addSwitch('s2',cls=OVSKernelSwitch, protocols='OpenFlow13')
        s3 = self.addSwitch('s3',cls=OVSKernelSwitch, protocols='OpenFlow13')
        s4 = self.addSwitch('s4', cls=OVSKernelSwitch, protocols='OpenFlow13')

        # Add links with bandwidth capacities
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)
        self.addLink(h4, s4)

        self.addLink(s1, s2, bw=5)
        self.addLink(s1, s3, bw=7)
        self.addLink(s1, s4, bw=20)
        self.addLink(s2, s3, bw=10)
        self.addLink(s2, s4, bw=10)
        self.addLink(s3, s4, bw=5)


def save_host_info(net):
    """
    Collects and saves the MAC addresses and connected ports of the hosts in a JSON file.
    """
    host_info = {}

    for host in net.hosts:
        mac = host.MAC()
        # Get the link information for the host
        intf = host.intfList()[0]  # Assuming the host has only one interface
        link = intf.link
        if link:
            # Get the connected switch and port number
            connected_switch = int(link.intf2.node.name.split("s")[-1])
            connected_port = link.intf2.name.split("-")[-1]
            connected_port = int(connected_port.split("eth")[-1])

            host_info[host.name] = {
                "mac": mac,
                "connected_switch": connected_switch,  # Name of the connected switch
                "src_port": connected_port,  # Port number on the switch
            }

    with open("/tmp/host_info.json", "w") as f:
        json.dump(host_info, f, indent=4)

    print("Host info (MAC and port) saved to /tmp/host_info.json")


def run_topology():
    # Sets the log level
    setLogLevel('info')

    # Create the network with the remote controller
    
    net = Mininet(topo=MyTopo(), link=TCLink, controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653), autoSetMacs=True) #autoStaticArp=True

    # Start the network
    net.start()

    # Save the MAC addresses of the hosts
    save_host_info(net)


    # Open the Mininet CLI for manual interaction
    CLI(net)

    # Stops the network when the CLI is closed
    net.stop()


if __name__ == '__main__':
    run_topology()