import logging
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, ipv6
from ryu.topology import event
from ryu.topology.api import get_link, get_switch
from ryu.app.wsgi import WSGIApplication
from flow_allocator_handler_REST import FlowRequestHandler
import heapq
from path_finder import PathFinder
from time import sleep

from pprint import pprint


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

        # self.mac_to_host = {
        #     "h1":"02:98:a0:f3:45:07",
        #     "h2":"e2:8d:18:27:c8:87",
        #     "h3":"16:46:f6:62:b3:ab",
        #     "h4":"a6:0c:58:e9:86:2d",
        # }
        # self.host_to_switch = {
        #     "h1": 1,
        #     "h2": 2,
        #     "h3": 3,
        #     "h4": 4,
        # }
        # self.mac_to_switch ={
        #     "02:98:a0:f3:45:07": 1,
        #     "e2:8d:18:27:c8:87": 2,
        #     "16:46:f6:62:b3:ab": 3,
        #     "a6:0c:58:e9:86:2d": 4,
        # }
        
        self.host_to_switch = {}
        
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

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath  # Add datapath
            self.logger.info(f"Switch connected: dpid={datapath.id}")
            # self.logger.info(f"Datapaths: {self.datapaths[datapath.id]}")
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)  # Remove datapath
            self.logger.info(f"Switch disconnected: dpid={datapath.id}")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, MAIN_DISPATCHER)
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
        
        # Regola specifica per ARP
        # match_arp = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_ARP)
        # self.add_flow(datapath, 1, match_arp, actions)

        # Regola specifica per IPv4
        # match_ipv4 = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP)
        # self.add_flow(datapath, 1, match_ipv4, actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        self.logger.info(f"datapath.id={datapath.id}")
        # Create flow mod message
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match, instructions=inst
        )
        self.logger.debug(f"Flow added: match={match}, actions={actions}")
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
    
    def allocate_flow(self, src_mac, src_switch, src_port, dst_mac, bandwidth):
        """
        Allocates a flow from src_mac to dst_mac. If MAC addresses are unknown,
        it triggers the learning process and retries automatically.
        """
        # max_retries = 5
        max_retries = 1
        retry_interval = 1  # Tempo in secondi tra i tentativi

        for attempt in range(max_retries):
            if src_mac in self.host_to_switch and dst_mac in self.host_to_switch:
                # Entrambi i MAC sono noti: Procedi con l'allocazione
                self.logger.info(f"Attempt {attempt + 1}/{max_retries}: Allocating flow...")
                return self._allocate_flow_internal(src_mac, dst_mac, bandwidth)

            # Triggera il processo di apprendimento
            self.logger.warning(f"Attempt {attempt + 1}/{max_retries}: Learning MAC addresses...")
            # self.trigger_packet_in_for_learning(src_mac, src_switch, src_port, dst_mac)
            self.trigger_packet_in(src_switch, src_port, src_mac, dst_mac)

            # Attendi che il learning sia completato
            self.logger.info(f"Waiting for MAC learning...")
            sleep(retry_interval)

        # Dopo tutti i tentativi, se non abbiamo appreso i MAC, fallisce
        self.logger.error("MAC address learning failed. Unable to allocate flow.")
        return False
    
    def _allocate_flow_internal(self, src_mac, dst_mac, bandwidth):
        """
        Internal function to allocate a flow once MAC addresses are known.
        """
        src_switch = self.host_to_switch[src_mac]
        dst_switch = self.host_to_switch[dst_mac]

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

        
        # Ottieni src_port e dst_port dai dizionari
        src_port = self.host_to_switch[src_mac]['port']
        dst_port = self.host_to_switch[dst_mac]['port']

        # Installa le regole di flusso
        self.install_path_flows(path, src_mac, dst_mac, src_port, dst_port)
        self.install_path_flows(path[::-1], dst_mac, src_mac, dst_port, src_port)
        
        self.logger.info(f"Flow successfully allocated from {src_mac} to {dst_mac}.")
        return True

    def install_path_flows(self, path, src_mac, dst_mac, src_port, dst_port):
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

        # self.logger.info(f"Datapaths:")
        # # cycle through the datapaths and print datapath id and the ports
        # for datapath in self.datapaths.values():
        #     self.logger.info(f"Datapath ID: {datapath.id}")
        #     datapath_info = {
        #         "id": datapath.id,
        #         "ports": {port.port_no: port.hw_addr for port in datapath.ports.values()}
        #     }
        #     self.logger.info(f"Datapath Info:")
        #     pprint(datapath_info)

        
        
        return self.datapaths[switch_id]

    def trigger_packet_in(self, src_switch, src_port, src_mac, dst_mac):
        """
        Triggers ARP learning by flooding a broadcast or directed packet.
        Args:
            src_switch (int): Source switch ID.
            src_port (int): Source port number.
            src_mac (str): Source MAC address.
            dst_mac (str): Destination MAC address.
        """
        if src_switch not in self.datapaths:
            self.logger.error(f"Datapath {src_switch} not found.")
            return

        datapath = self.datapaths[src_switch]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Create a synthetic packet
        
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_IP,
                           src=src_mac, dst=dst_mac))
        pkt.add_protocol(b'Packet triggered from allocator')  # Add custom message to the payload
        pkt.serialize()

          # Simulate Packet-In message
        msg = parser.OFPPacketIn(datapath=datapath,
                                buffer_id=ofproto.OFP_NO_BUFFER,
                                total_len=len(pkt.data),
                                reason=ofproto.OFPR_NO_MATCH,
                                table_id=0,
                                cookie=0,
                                match=parser.OFPMatch(in_port=src_port),
                                data=pkt.data)
        # Manually invoke the packet_in_handler
        self.packet_in_handler(type("Event", (object,), {"msg": msg}))
        self.logger.info(f"Simulated Packet-In: {src_mac} -> {dst_mac} on Switch {src_switch}, Port {src_port}")


    # def trigger_packet_in_for_learning(self, src_mac, src_switch, src_port, dst_mac):
    #     """
    #     Sends packets for MAC learning using flooding.
    #     """
    #     for switch_id, datapath in self.datapaths.items():
    #         # Se entrambi i MAC sono sconosciuti, invia due pacchetti in broadcast
    #         if src_mac not in self.host_to_switch and dst_mac not in self.host_to_switch:
    #             self.trigger_packet_in(switch_id, src_mac, src_port, dst_mac)  # Broadcast from src_mac
    #             #self.trigger_packet_in(switch_id, dst_mac, src_mac)  # Broadcast from dst_mac
    #             # self.logger.info(f"Flooded broadcast packets from {src_mac} and {dst_mac} on switch {switch_id}")

    #         # Se conosci solo uno dei due MAC
    #         elif src_mac not in self.host_to_switch:
    #             self.trigger_packet_in(switch_id, src_mac, src_port, dst_mac)
    #             self.logger.info(f"Sent learning packet: {src_mac} -> {dst_mac} via Switch {switch_id}")

    #         elif dst_mac not in self.host_to_switch:
    #             self.trigger_packet_in(switch_id, src_mac, src_port, dst_mac)
    #             self.logger.info(f"Sent learning packet: {dst_mac} -> {src_mac} via Switch {switch_id}")


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
        
        # for protocol in pkt.protocols:
        #     if protocol is not ether_types.ETH_TYPE_LLDP:
        #         self.logger.info(f"Protocol detected: {type(protocol).__name__}")
        #         # stampa sorge e destinazione
        #         self.logger.info(f"Source: {eth.src}, Destination: {eth.dst}")

        
        # # print packet type
        # pkt_type = ""
        # if eth.ethertype == ether_types.ETH_TYPE_ARP:
        #     pkt_type = "ARP"
        # elif eth.ethertype == ether_types.ETH_TYPE_IP:
        #     pkt_type = "IP"
        # elif eth.ethertype == ether_types.ETH_TYPE_IPV6:
        #     pkt_type = "IPv6"
        # else:
        #     pkt_type = "Unknown"
            
        # self.logger.info(f"PacketIn received: {pkt_type}")
            
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # Ignore LLDP packets
        

        self.logger.info(f"PacketIn received: {eth.src} -> {eth.dst} on Switch {dpid}, Port {in_port}")
        
        src_mac = eth.src
        dst_mac = eth.dst

        # Aggiorna la struttura host_to_switch
        if src_mac not in self.host_to_switch:
            self.host_to_switch[src_mac] = {"dpid": dpid, "port": in_port}
            self.logger.info(f"Learned host: {src_mac} -> Switch {dpid}, Port {in_port}")

        # Controlla se l'host di destinazione è noto
        if dst_mac in self.host_to_switch:
            # Host conosciuto: determina la porta di uscita
            out_port = self.host_to_switch[dst_mac]["port"]
            self.logger.info(f"Forwarding packet from {src_mac} to {dst_mac} via Port {out_port}")
        else:
            # Host sconosciuto: flood
            out_port = ofproto.OFPP_FLOOD
            self.logger.info(f"Flooding packet from {src_mac} to {dst_mac}")

        # Definisce le azioni per il pacchetto
        actions = [parser.OFPActionOutput(out_port)]

        # Installa una regola di flusso se non stai effettuando flood
        # if out_port != ofproto.OFPP_FLOOD:
        #     match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
        #     self.add_flow(dp, 1, match, actions)

        # Invia il pacchetto al destinatario o effettua flood
        payload = b"Forwarded from controller"
        data = msg.data + payload if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        # data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data
        )
        dp.send_msg(out)
        
        pprint(self.host_to_switch)
