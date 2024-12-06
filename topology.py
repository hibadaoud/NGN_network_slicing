from mininet.topo import Topo

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
        s1 = self.addSwitch('s1', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', protocols='OpenFlow13')
        s4 = self.addSwitch('s4', protocols='OpenFlow13')

        # Add links with bandwidth capacities
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)
        self.addLink(h4, s4)

        self.addLink(s1, s2, bw=5)
        self.addLink(s1, s3, bw=7)
        self.addLink(s2, s4, bw=10)
        self.addLink(s3, s4, bw=5)
        self.addLink(s2, s3, bw=10)
        self.addLink(s1, s4, bw=20)

# Make the topology available to Mininet
topos = {'mytopo': (lambda: MyTopo())}