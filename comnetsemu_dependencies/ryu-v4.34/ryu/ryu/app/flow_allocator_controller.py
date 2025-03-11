import json
import logging
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.topology import event
from ryu.topology.api import get_link
from ryu.app.wsgi import WSGIApplication
from flow_allocator_handler_websocket import FlowWebSocketHandler
from path_finder import PathFinder
import time


from pprint import pprint

class FlowAllocator(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(FlowAllocator, self).__init__(*args, **kwargs)
        
        # Configure the logger
        formatter = logging.Formatter("[%(funcName)s] %(message)s")
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Avoid duplicating logs
        self.logger.propagate = False
        
        self.logger.setLevel("INFO")
        self.logger.info("Initializing FlowAllocator...")
        
        
        # Start the WebSocket server in a separate thread
        self.websocket_handler = FlowWebSocketHandler(flow_allocator=self, host="0.0.0.0", port=8765, logger=self.logger)
        threading.Thread(target=self.websocket_handler.start, daemon=True).start()
        self.logger.info("WebSocket handler started!")
        
        
        self.host_to_switch = {}
        self._init_host_to_switch()
        
        self.flow_reservations = {}
        
        self.links = {}  

        self.datapaths = {}
        
        self.flow_capacity = {}
        self._init_flow_capacity()

        self.path_finder = PathFinder(self.flow_capacity, self.logger)
            
    def _init_host_to_switch(self):
        """
        Reads `/tmp/host_info.json` and initializes the host_to_switch dictionary.
        """
        self.logger.info("Initializing host_to_switch dictionary from Mininet output...")

        # Path to the JSON file generated by Mininet
        host_info_file = "/tmp/host_info.json"

        if not os.path.exists(host_info_file):
            self.logger.error(f"Host info file not found: {host_info_file}")
            return False

        try:
            with open(host_info_file, "r") as f:
                host_info: dict = json.load(f)

            # Populate the map using MAC as key and also save the host name
            for host_name, details in host_info.items():
                mac = details["mac"]
                self.host_to_switch[mac] = {
                    "name": host_name,
                    "connected_switch": details["connected_switch"],
                    "src_port": details["src_port"]
                }

            self.logger.info(f"Host-to-switch mapping initialized: {self.host_to_switch}")
            return True

        except json.JSONDecodeError:
            self.logger.error("Error decoding JSON file. Ensure Mininet has generated the file correctly.")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error reading host info file: {e}")
            return False
    
    def _init_flow_capacity(self):
        """
        Initializes the flow capacity dictionary based on bandwidth info from switch_links_info.json
        """
        self.logger.info("Initializing flow capacity dictionary...")

        # Read the JSON file
        try:
            with open("/tmp/switch_links_info.json", "r") as f:
                switch_links = json.load(f)
        except FileNotFoundError:
            self.logger.error("switch_links_info.json not found")
            return
        except json.JSONDecodeError:
            self.logger.error("Error decoding switch_links_info.json")
            return
        
        self.logger.info(f"Switch links info: {switch_links}")

        # Process each link
        for link_str, info in switch_links.items():
            # Parse switches from string like "s1-s2"
            sw1, sw2 = link_str.split("-")
            sw1_id = int(sw1.lstrip("s"))
            sw2_id = int(sw2.lstrip("s"))
            
            # Get bandwidth, default to 10 if not specified
            bw = info.get("bandwidth", 10)

            # Add both directions to flow capacity
            self.flow_capacity[(sw1_id, sw2_id)] = bw
            self.flow_capacity[(sw2_id, sw1_id)] = bw

        self.logger.info(f"Flow capacities initialized: {self.flow_capacity}")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath  # Add datapath
            self.logger.info(f"Switch connected: dpid={datapath.id}")
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)  # Remove datapath
            self.logger.info(f"Switch disconnected: dpid={datapath.id}")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id  # Datapath ID of the switch
        self.logger.info(f"Switch connected: dpid={dpid}")
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Default rule to handle all packets
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match, instructions=instructions
        )
        self.logger.debug(f"Adding flow: match={match}, actions={actions}")
        datapath.send_msg(mod)
        self.logger.info(f"Flow added successfully.")
    
    def _delete_flow(self, datapath, match):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(
            datapath=datapath, command=ofproto.OFPFC_DELETE, out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
            match=match
        )
        self.logger.debug(f"Deleting flow: match={match}")
        datapath.send_msg(mod)
        self.logger.info(f"Flow deleted successfully.")
         
    # ------------------------------------------------
    # 2) Topology (SwitchEnter, LinkAdd, LinkDelete)
    # ------------------------------------------------
    @set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        old_links = dict(self.links)
        self.logger.info(f"Switch entered: {ev.switch.dp.id}")
        # self._get_topology_data()
        if old_links != self.links:
            self.logger.info(f"Switch added. Updated links: {self.links}")

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        self._get_topology_data()

    @set_ev_cls(event.EventLinkDelete)
    def link_delete_handler(self, ev):
        self.logger.info(f"Link deleted. Updated links: {self.links}")
        
    def _get_topology_data(self):
        """
        Updates topology data by collecting information from get_switch() and get_link().
        """
        # Resets the dictionaries
        self.links.clear()
                
        # Gets the link data
        link_list = get_link(self, None)
        for link in link_list:
            src_dpid = int(link.src.dpid)
            dst_dpid = int(link.dst.dpid)
            src_port_no = int(link.src.port_no)
            dst_port_no = int(link.dst.port_no)

            # Maps the links in the dictionaries
            self.links[(src_dpid, dst_dpid)] = {
                "src_port": src_port_no,
                "dst_port": dst_port_no,
                "src_hw_addr": link.src.hw_addr,
                "dst_hw_addr": link.dst.hw_addr,
            }
    
    # 1. Endpoint for flow allocation

    def allocate_flow(self, src_mac, dst_mac, bandwidth):
        """
        Internal function to allocate a flow between two MAC addresses.
        """
        # Check if src_mac and dst_mac exist in host_to_switch mapping
        if src_mac not in self.host_to_switch or dst_mac not in self.host_to_switch:
            self.logger.error(f"Host not found: {src_mac} -> {dst_mac}")
            return False

        src_details = self.host_to_switch[src_mac]
        dst_details = self.host_to_switch[dst_mac]

        # Converts the switch string (e.g., "s1") into dpid (int)
        src_dpid = int(src_details["connected_switch"].lstrip("s"))
        dst_dpid = int(dst_details["connected_switch"].lstrip("s"))

        src_datapath = self.datapaths.get(src_dpid)
        if src_datapath is None:
            self.logger.error(f"Datapath not found for dpid: {src_dpid}")
            return False

        dst_datapath = self.datapaths.get(dst_dpid)
        if dst_datapath is None:
            self.logger.error(f"Datapath not found for dpid: {dst_dpid}")
            return False

        # Create dictionaries for switches for path_finder
        src_switch = {"dpid": src_dpid}
        dst_switch = {"dpid": dst_dpid}

        # Find the path with enough bandwidth
        path, available_bandwidth = self.path_finder.find_max_bandwidth_path(src_switch, dst_switch, bandwidth)
        if not path:
            self.logger.error("No path found with sufficient bandwidth.")
            return False

        self.logger.info(f"Path found: {path}, available bandwidth: {available_bandwidth} Mbps")

        # Update remaining capacity and install flows
        for i in range(len(path) - 1):
            link = (path[i], path[i + 1])
            reverse_link = (path[i + 1], path[i])
            self.flow_capacity[link] -= bandwidth
            self.flow_capacity[reverse_link] -= bandwidth
            self.path_finder.link_capacities[link] = self.flow_capacity[link]
            self.path_finder.link_capacities[reverse_link] = self.flow_capacity[reverse_link]
        
        self.path_finder.build_graph()  # Rebuild the graph

        
        # Ottieni src_port e dst_port dai dizionari
        src_port = self.host_to_switch[src_mac]['port']
        dst_port = self.host_to_switch[dst_mac]['port']

        # Installa le regole di flusso
        self.install_path_flows(path, src_mac, dst_mac, src_port, dst_port)
        self.install_path_flows(path[::-1], dst_mac, src_mac, dst_port, src_port)
        
        self.logger.info(f"Flow successfully allocated from {src_mac} to {dst_mac}.")

        return True

    def install_path_flows(self, path, src_mac, dst_mac, src_port, dst_port, bandwidth):
        """
        Installs flow rules along the given path.
        Args:
            path (list): List of switch IDs in the path.
            src_mac (str): Source MAC address.
            dst_mac (str): Destination MAC address.
            src_port (int): Source port.
            dst_port (int): Destination port.
            bandwidth (int): Bandwidth limit in Mbps.

        """
        for i in range(len(path)):
            datapath = self.get_datapath(path[i])
            parser = datapath.ofproto_parser

            try:
                if i == 0:
                    self.logger.info(f"First switch: {path[i]} -> {path[i + 1]}")
                    # First switch: match src_mac and forward to the next switch
                    out_port = self.links[(path[i], path[i + 1])]["src_port"]
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac, in_port=src_port)
                
                elif i == len(path) - 1:
                    self.logger.info(f"Last switch: {path[i]} -> host B")
                    # Last switch: forward to destination port
                    out_port = dst_port
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                else:
                    self.logger.info(f"Intermediate switch: {path[i]} -> {path[i + 1]}")
                    # Intermediate switches
                    out_port = self.links[(path[i], path[i + 1])]["src_port"]
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)

                # Azioni di uscita
                actions = [parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, 1, match, actions)

            except KeyError:
                self.logger.error(f"Link not found: {path[i]} -> {path[i + 1]}")
                return

        self.logger.info(f"Flow rules installed along path: {path}")

    def get_datapath(self, switch_id):
        """
        Maps a switch ID to its datapath object.

        Args:
            switch_id (str): Switch ID.

        Returns:
            datapath: The OpenFlow datapath object for the switch.
        """        
        return self.datapaths[switch_id]

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handles the PacketIn event to learn host locations and forward packets.
        Args:
            ev: The event object containing the packet and metadata.
        """
        
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        
        if eth.ethertype in [ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6]:
            return  # Ignore LLDP and IPv6 packets 
        
        src_mac = eth.src
        dst_mac = eth.dst
    
        self.logger.info(f"PacketIn received: {eth.src} -> {eth.dst} on Switch {dpid}, Port {in_port}")
        
        installed = self.check_reservation(src_mac, dst_mac)

        if installed:
            self.logger.info(f"Flow rules installed, resending original packet from {src_mac} to {dst_mac}.")
            actions = [parser.OFPActionOutput(ofproto.OFPP_TABLE)]
            out = parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data
            )
            dp.send_msg(out)
        
        if dst_mac in self.host_to_switch:
            out_port = self.host_to_switch[dst_mac].get("src_port")
            if out_port is None:
                self.logger.error(f"Source port not found for host with MAC {dst_mac}")
                return
            self.logger.info(f"Forwarding packet from {src_mac} to {dst_mac} via Port {out_port}")
        else:
            self.logger.info(f"Host not found: {dst_mac}")
            return

        # Defines the actions for the packet
        actions = [parser.OFPActionOutput(out_port)]

        # # Send the packet to the destination or flood
        payload = b"Forwarded from controller"
        data = msg.data + payload if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data
        )
        dp.send_msg(out)
        
        # pprint(f"\t[host_to_switch]", self.host_to_switch)
