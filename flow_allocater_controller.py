from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.app.wsgi import WSGIApplication
from flow_allocator_handler_REST import FlowRequestHandler
import heapq
from path_finder import PathFinder


class FlowAllocator(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(FlowAllocator, self).__init__(*args, **kwargs)
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
        self.mac_to_switch ={
            "02:98:a0:f3:45:07": 1,
            "e2:8d:18:27:c8:87": 2,
            "16:46:f6:62:b3:ab": 3,
            "a6:0c:58:e9:86:2d": 4,
        }

        self.mac_to_port = {}  # Initialize MAC-to-port dictionary
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

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath  # Add datapath
            self.logger.info(f"Switch connected: dpid={datapath.id}")
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

    def allocate_flow(self, src_mac, dst_mac, bandwidth):
        """
        Allocates a flow from src_mac to dst_mac if a path with sufficient bandwidth exists.
        Triggers the packet_in handler by creating a fake packet.

        Args:
            src_mac (str): Source MAC address.
            dst_mac (str): Destination MAC address.
            bandwidth (int): Required bandwidth in Mbps.

        Returns:
            bool: True if the flow is successfully allocated, False otherwise.
        """
        self.logger.info(f"Allocating flow: src_mac={src_mac}, dst_mac={dst_mac}, bandwidth={bandwidth} Mbps")

        # Map MAC addresses to switch IDs
        if src_mac not in self.mac_to_switch or dst_mac not in self.mac_to_switch:
            self.logger.error("MAC address not associated with any switch.")
            return False

        src_switch = self.mac_to_switch[src_mac]
        dst_switch = self.mac_to_switch[dst_mac]

        # Step 1: Find the path with sufficient bandwidth
        self.logger.info(f"Checking residual capacities before pathfinding:")
        for link, capacity in self.flow_capacity.items():
            self.logger.info(f"Link: {link}, Residual Capacity: {capacity}")

        self.logger.info(f"Allocating flow: src_switch={src_switch}, dst_switch={dst_switch}, bandwidth={bandwidth} Mbps")
        path, available_bandwidth = self.path_finder.find_max_bandwidth_path(src_switch, dst_switch, bandwidth)
        if not path:
            self.logger.error("No path found with sufficient bandwidth.")
            return False

        self.logger.info(f"Path found: {path}, available bandwidth: {available_bandwidth} Mbps")

        # Step 2: Update residual capacities along the path
        for i in range(len(path) - 1):
            link = (path[i], path[i + 1])
            reverse_link = (path[i + 1], path[i])

            # Log residual capacities before the update
            self.logger.info(f"Before allocation: link={link}, capacity={self.flow_capacity[link]}")
            self.logger.info(f"Before allocation: reverse link={reverse_link}, capacity={self.flow_capacity[reverse_link]}")

            # Deduct the required bandwidth from the link capacities
            self.flow_capacity[link] -= bandwidth
            self.flow_capacity[reverse_link] -= bandwidth

            # Update the PathFinder
            self.path_finder.link_capacities[link] = self.flow_capacity[link]
            self.path_finder.link_capacities[reverse_link] = self.flow_capacity[reverse_link]

            # Log residual capacities after the update
            self.logger.info(f"After allocation: link={link}, capacity={self.flow_capacity[link]}")
            self.logger.info(f"After allocation: reverse link={reverse_link}, capacity={self.flow_capacity[reverse_link]}")

        # Step 3: Trigger the packet_in handler by creating a fake packet
        self.trigger_packet_in(path[0], src_mac, dst_mac)

        self.logger.info(f"Flow successfully allocated: src_mac={src_mac}, dst_mac={dst_mac}, bandwidth={bandwidth} Mbps")
        return True

    def get_datapath(self, switch_id):
        """
        Maps a switch ID to its datapath object.

        Args:
            switch_id (str): Switch ID.

        Returns:
            datapath: The OpenFlow datapath object for the switch.
        """
        return self.datapaths[switch_id]

    def trigger_packet_in(self, switch_id, src_mac, dst_mac):
        """
        Triggers the packet_in handler by creating a fake packet and sending it to the controller.

        Args:
            switch_id (str): The switch ID to trigger the event.
            src_mac (str): Source MAC address.
            dst_mac (str): Destination MAC address.
        """
        self.logger.info(f"calling the function trigger_packet_in ")
        datapath = self.get_datapath(switch_id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Create a fake Ethernet packet
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_IP, src=src_mac, dst=dst_mac))
        pkt.serialize()

        # Send PacketOut to the controller (to trigger packet_in)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data
        )
        datapath.send_msg(out)
        self.logger.info(f"PacketOut sent: switch={switch_id}, src_mac={src_mac}, dst_mac={dst_mac}")


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handles the PacketIn event when a switch forwards a packet to the controller.

        Args:
            ev: The event object containing the packet and metadata.
        """
        self.logger.info("PacketIn received!")
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        in_port = msg.match['in_port']

        # Extract Ethernet frame
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        # Ignore LLDP packets (used for topology discovery)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        dpid = datapath.id  # Datapath ID of the switch
        self.mac_to_port.setdefault(dpid, {})  # Initialize MAC-to-port mapping if not exists

        # Learn the source MAC-to-port mapping
        self.mac_to_port[dpid][src] = in_port

        # Check if the destination MAC is already learned
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            # Destination MAC unknown: Flood the packet
            out_port = ofproto.OFPP_FLOOD

        # Define actions
        actions = [parser.OFPActionOutput(out_port)]

        # Install flow rule if not flooding
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        # Send packet out (whether flooding or directed)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data
        )
        datapath.send_msg(out)