import json
import logging
import os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, ipv6
from ryu.topology import event
from ryu.topology.api import get_link, get_switch
from ryu.app.wsgi import WSGIApplication
import yaml
from flow_allocator_handler_REST import FlowRequestHandler
import heapq
from path_finder import PathFinder
from time import sleep
import time
import threading


from pprint import pprint

PACKET_TIMEOUT = 5  # Timeout in seconds for duplicate packet detection

# Link dictionary
# links = {
#     (1, 2): { # Link from switch 1 to switch 2 (s1 -> s2) 
#         "src_port": 1, # Source port
#         "dst_port": 1, # Destination port
#         "src_hw_addr": "00:00:00:00:00:01", # Source MAC address
#         "dst_hw_addr": "00:00:00:00:00:02", # Destination MAC address
#     },
#    (2, 1): { # Reverse link from switch 2 to switch 1 (s2 -> s1)
#     ... 
#    },
# }

# Datapath dictionary
# datapaths = {
#     1: {
#         "id": 1,
#         "ports": {
#             1: "00:00:00:00:00:01",
#             2: "00:00:00:00:00:02",
#             3: "00:00:00:00:00:03",
#         },
#     },
#     2: {
#        ...
#     },

class FlowAllocator(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(FlowAllocator, self).__init__(*args, **kwargs)
        
        # Configura il logger
        formatter = logging.Formatter("[%(funcName)s] %(message)s")
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Evita di duplicare i log
        self.logger.propagate = False
        
        self.logger.setLevel("INFO")
        self.logger.info("Initializing FlowAllocator...")
        
        wsgi = kwargs['wsgi']
        wsgi.register(FlowRequestHandler, {'flow_allocator': self})
        self.logger.info("FlowRequestHandler registered!")

        self.host_to_switch = {}
        self._init_host_to_switch()
        
        self.flow_reservations = {}
        # self.mac_to_switch = {}
        
        self.links = {}  

        # self.mac_to_port = {}  # Initialize MAC-to-port dictionary
        self.datapaths = {}
        self.flow_capacity = {
            (1, 2): 5,
            (2, 1): 5,  # Reverse link
            (1, 3): 7,
            (3, 1): 7,  # Reverse link
            (2, 3): 10,
            (3, 2): 10,  # Reverse link
            (2, 4): 10,
            (4, 2): 10,  # Reverse link
            (3, 4): 5,
            (4, 3): 5,  # Reverse link
            (1, 4): 20,
            (4, 1): 20,  # Reverse link
        }

        self.path_finder = PathFinder(self.flow_capacity, self.logger)
        
        # self.switches = {}
    
    def _init_host_to_switch(self):
        """
        Reads `/tmp/host_info.json` and initializes the host_to_switch dictionary.
        """
        self.logger.info("Initializing host_to_switch dictionary from Mininet output...")

        # Percorso del file JSON generato da Mininet
        host_info_file = "/tmp/host_info.json"

        if not os.path.exists(host_info_file):
            self.logger.error(f"Host info file not found: {host_info_file}")
            return False

        try:
            with open(host_info_file, "r") as f:
                host_info: dict = json.load(f)

             # Popoliamo la mappa usando il MAC come chiave e salvando anche il nome dell'host
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
    
    def cleanup_processed_packets(self):
        """
        Thread that periodically cleans up the set of processed packets.
        """
        while True:
            current_time = time.time()
            # Remove packets older than the timeout
            self.processed_packets = {
                k: v for k, v in self.processed_packets.items() if current_time - v < PACKET_TIMEOUT
            }
            self.logger.info(f"Cleaned up processed packets. Remaining: {len(self.processed_packets)}")
            time.sleep(PACKET_TIMEOUT)  # wait for the timeout period

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
        # Create flow mod message
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match, instructions=inst
        )
        self.logger.debug(f"Adding flow: match={match}, actions={actions}")
        datapath.send_msg(mod)
        self.logger.info(f"Flow added successfully.")
        
    # ------------------------------------------------
    # 2) Topologia (SwitchEnter, LinkAdd, LinkDelete)
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
        old_links = dict(self.links)
        # self.logger.info(f"Link added event: {ev.link.to_dict()}")
        # self.logger.info(f"Link added event: {ev.link.src.dpid} -> {ev.link.dst.dpid}")
        self._get_topology_data()
        # if old_links != self.links:
            # self.logger.info(f"Link added. Updated links: {self.links}")
            # self.logger.info(f"Link added. Updated links:")
            # pprint(self.links)

    @set_ev_cls(event.EventLinkDelete)
    def link_delete_handler(self, ev):
        # self._get_topology_data()
        self.logger.info(f"Link deleted. Updated links: {self.links}")
        
    def _get_topology_data(self):
        """
        Aggiorna i dati della topologia raccogliendo informazioni da get_switch() e get_link().
        """
        
        # Resetta i dizionari
        self.links.clear()
        
        
        # Ottieni i dati sui link
        link_list = get_link(self, None)
        for link in link_list:
            src_dpid = int(link.src.dpid)
            dst_dpid = int(link.dst.dpid)
            src_port_no = int(link.src.port_no)
            dst_port_no = int(link.dst.port_no)

            # Mappa i link nei dizionari
            self.links[(src_dpid, dst_dpid)] = {
                "src_port": src_port_no,
                "dst_port": dst_port_no,
                "src_hw_addr": link.src.hw_addr,
                "dst_hw_addr": link.dst.hw_addr,
            }
        
    def allocate_flow(self, src_mac, dst_mac, bandwidth):
        """
        Internal function to allocate a flow once MAC addresses are known.
        """
        
        # Controlla se src_mac e dst_mac esistono nel mapping host_to_switch
        if src_mac not in self.host_to_switch or dst_mac not in self.host_to_switch:
            self.logger.error(f"Host not found: {src_mac} -> {dst_mac}")
            return False

        src_details = self.host_to_switch[src_mac]
        dst_details = self.host_to_switch[dst_mac]

        # Converti la stringa dello switch (es. "s1") in dpid (int)
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

        # Crea i dizionari per gli switch se necessario
        src_switch = {"dpid": src_dpid}
        dst_switch = {"dpid": dst_dpid}

        # Trova il percorso con sufficiente banda
        path, available_bandwidth = self.path_finder.find_max_bandwidth_path(src_switch, dst_switch, bandwidth)
        if not path:
            self.logger.error("No path found with sufficient bandwidth.")
            return False

        self.logger.info(f"Path found: {path}, available bandwidth: {available_bandwidth} Mbps")

        # Aggiorna la capacità residua e installa i flussi
        for i in range(len(path) - 1):
            link = (path[i], path[i + 1])
            reverse_link = (path[i + 1], path[i])
            self.flow_capacity[link] -= bandwidth
            self.flow_capacity[reverse_link] -= bandwidth
            self.path_finder.link_capacities[link] = self.flow_capacity[link]
            self.path_finder.link_capacities[reverse_link] = self.flow_capacity[reverse_link]
        
        self.path_finder.build_graph()  # Rebuild the graph

        self.flow_reservations[(src_mac, dst_mac)] = {
            "path": path,
            "bandwidth": bandwidth,
            "start_time": time.time()
        }
        
        self.logger.info(f"Flow reservation added: {src_mac} -> {dst_mac}")
        return True
    
    
    def check_reservation(self, src_mac, dst_mac):
        """
        Check if a flow reservation exists and apply it.
        """
        reservation = self.flow_reservations.get((src_mac, dst_mac))
        if not reservation:
            self.logger.error(f"Flow not found: {src_mac} -> {dst_mac}")
            return False

        path = reservation["path"]
        bandwidth = reservation["bandwidth"]
        start_time = reservation["start_time"]
        current_time = time.time()
        elapsed_time = current_time - start_time

        # Check if the reservation has expired
        if elapsed_time > 60:
            self.logger.error(f"Flow reservation expired: {src_mac} -> {dst_mac}")
            # Restore capacities
            for i in range(len(path) - 1):
                link = (path[i], path[i + 1])
                reverse_link = (path[i + 1], path[i])
                self.flow_capacity[link] += bandwidth
                self.flow_capacity[reverse_link] += bandwidth
                self.path_finder.link_capacities[link] = self.flow_capacity[link]
                self.path_finder.link_capacities[reverse_link] = self.flow_capacity[reverse_link]

            self.path_finder.build_graph()  # Rebuild the graph
            return False
        
        self.logger.info(f"Applying flow reservation: {src_mac} -> {dst_mac}")

        try:
            src_port = self.host_to_switch[src_mac]['src_port']
        except KeyError:
            self.logger.error(f"Source port not found for host with MAC {src_mac}")
            return False

        try:
            dst_port = self.host_to_switch[dst_mac]['src_port']
        except KeyError:
            self.logger.error(f"Destination port not found for host with MAC {dst_mac}")
            return False
        
        # Installa le regole di flusso
        self.install_path_flows(path, src_mac, dst_mac, src_port, dst_port, bandwidth)
        self.install_path_flows(path[::-1], dst_mac, src_mac, dst_port, src_port, bandwidth)

             
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
        """
        for i in range(len(path)):
            datapath = self.get_datapath(path[i])
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

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

               #  Apply QoS queue instead of meter
                queue_id = self.setup_qos_queue(datapath, out_port, bandwidth)
                actions = [parser.OFPActionSetQueue(queue_id), parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, 1, match, actions)

            except KeyError:
                self.logger.error(f"Link not found: {path[i]} -> {path[i + 1]}")
                return

        self.logger.info(f"Flow rules installed along path: {path}")

    def setup_qos_queue(self, datapath, port, bandwidth):
        """
        Sets up a QoS queue to enforce bandwidth limits.
        Args:
            datapath: OpenFlow switch datapath.
            port: The port number to apply the QoS queue.
            bandwidth: Bandwidth limit in Mbps.
        Returns:
            The queue ID.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        queue_id = 1  # We assume only one queue per port

        ovs_cmd = f"sudo ovs-vsctl -- set Port s{datapath.id}-eth{port} qos=@newqos -- \
            --id=@newqos create QoS type=linux-htb other-config:max-rate={bandwidth * 1000000} \
            queues=0=@q0 -- --id=@q0 create Queue other-config:min-rate={bandwidth * 1000000} \
            other-config:max-rate={bandwidth * 1000000}"

        os.system(ovs_cmd)  # Run the OVS command

        self.logger.info(f"QoS Queue {queue_id} set on switch {datapath.id} port {port} with {bandwidth} Mbps")

        return queue_id
    
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
        
        self.check_reservation(src_mac, dst_mac)
        
        if dst_mac in self.host_to_switch:
            out_port = self.host_to_switch[dst_mac].get("src_port")
            if out_port is None:
                self.logger.error(f"Source port not found for host with MAC {dst_mac}")
                return
            self.logger.info(f"Forwarding packet from {src_mac} to {dst_mac} via Port {out_port}")
        else:
            self.logger.info(f"Host not found: {dst_mac}")
            return

        # Definisce le azioni per il pacchetto
        actions = [parser.OFPActionOutput(out_port)]

        # Invia il pacchetto al destinatario o effettua flood
        payload = b"Forwarded from controller"
        data = msg.data + payload if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        # data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data
        )
        dp.send_msg(out)
        
        # pprint(f"\t[host_to_switch]", self.host_to_switch)
